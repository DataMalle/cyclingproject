"""Körning av SQL mot ett Databricks SQL warehouse, med väntan på kallstart och omförsök."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

log = logging.getLogger("cykelstaden.warehouse")

_DONE = {StatementState.SUCCEEDED, StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED}
_NUMERIC = {"BYTE", "SHORT", "INT", "LONG", "FLOAT", "DOUBLE", "DECIMAL"}
_TEMPORAL = {"DATE", "TIMESTAMP", "TIMESTAMP_NTZ"}


class WarehouseError(RuntimeError):
    """SQL kunde inte köras (fel i frågan, behörighet eller warehouse som inte startade)."""


def to_frame(columns: Sequence[tuple[str, str]], rows: Sequence[Sequence[str | None]]) -> pd.DataFrame:
    """Bygger en typad DataFrame av Databricks JSON_ARRAY-resultat (alla värden kommer som strängar)."""
    df = pd.DataFrame(list(rows), columns=[name for name, _ in columns])
    for name, type_name in columns:
        if type_name in _NUMERIC:
            df[name] = pd.to_numeric(df[name], errors="coerce")
        elif type_name in _TEMPORAL:
            df[name] = pd.to_datetime(df[name], errors="coerce", utc=False)
    return df


@dataclass(frozen=True)
class Warehouse:
    client: WorkspaceClient
    warehouse_id: str
    catalog: str
    schema: str

    def query(self, sql: str, *, max_wait_s: int = 240, attempts: int = 3) -> pd.DataFrame:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                return self._query_once(sql, max_wait_s)
            except WarehouseError as e:
                last = e
                if not _is_transient(e):
                    break  # fel i själva frågan blir inte bättre av att försöka igen
            except Exception as e:
                last = e
            log.warning("SQL-försök %d/%d misslyckades: %s", attempt + 1, attempts, last)
            time.sleep(3 * (attempt + 1))
        raise WarehouseError(str(last)) from last

    def _query_once(self, sql: str, max_wait_s: int) -> pd.DataFrame:
        api = self.client.statement_execution
        res = api.execute_statement(
            statement=sql, warehouse_id=self.warehouse_id, catalog=self.catalog, schema=self.schema, wait_timeout="30s"
        )
        deadline = time.monotonic() + max_wait_s
        while res.status.state not in _DONE:  # warehouse startar: vänta istället för att ge upp
            if time.monotonic() > deadline:
                raise WarehouseError("Databricks SQL warehouse startade inte i tid")
            time.sleep(2)
            res = api.get_statement(res.statement_id)
        if res.status.state != StatementState.SUCCEEDED:
            msg = res.status.error.message if res.status.error else str(res.status.state)
            raise WarehouseError(msg)
        columns = [(c.name, getattr(c.type_name, "value", str(c.type_name))) for c in res.manifest.schema.columns]
        rows = res.result.data_array if res.result and res.result.data_array else []
        return to_frame(columns, rows)


def _is_transient(error: Exception) -> bool:
    text = str(error).lower()
    return any(s in text for s in ("startade inte", "temporarily", "timeout", "unavailable", "starting", "rate limit"))
