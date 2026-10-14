"""Validering av LLM-genererad SQL.

Tillåter exakt ett skrivskyddat SELECT-uttryck mot en fast lista av gold-tabeller och
begränsar antalet rader. Allt annat avvisas innan det når SQL warehouse.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = frozenset({"gold_trips_daily", "gold_trips_hourly", "gold_stations", "gold_station_routes"})
# Funktioner som kan läcka information eller köra kod. Tabellåtkomst stoppas separat via ALLOWED_TABLES.
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "reflect",
        "try_reflect",
        "java_method",
        "http_request",
        "read_files",
        "secret",
        "current_user",
        "session_user",
        "is_member",
    }
)
FORBIDDEN_STATEMENTS = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Merge)
MAX_ROWS = 500


class UnsafeSqlError(ValueError):
    """SQL som inte uppfyller säkerhetsreglerna."""


def validate_and_limit(sql: str, *, catalog: str = "workspace", schema: str = "cykelstaden") -> str:
    """Returnerar säker SQL med radgräns, eller kastar UnsafeSqlError."""
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise UnsafeSqlError("Tom SQL")
    try:
        statements = sqlglot.parse(sql, read="databricks")
    except sqlglot.errors.ParseError as e:
        raise UnsafeSqlError(f"Kunde inte tolka SQL: {e}") from e

    if len(statements) != 1 or statements[0] is None:
        raise UnsafeSqlError("Endast ett SQL-uttryck tillåts")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union)):
        raise UnsafeSqlError("Endast SELECT tillåts")
    if tree.find(*FORBIDDEN_STATEMENTS):
        raise UnsafeSqlError("Skrivande eller administrativa uttryck är inte tillåtna")

    for func in tree.find_all(exp.Func):
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if name in FORBIDDEN_FUNCTIONS:
            raise UnsafeSqlError(f"Funktionen '{name}' är inte tillåten")

    cte_names = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if table.name in cte_names and not table.db:
            continue
        if table.name not in ALLOWED_TABLES:
            raise UnsafeSqlError(f"Tabellen '{table.name or 'okänd'}' är inte tillåten")
        if (table.db and table.db != schema) or (table.catalog and table.catalog != catalog):
            raise UnsafeSqlError("Tabeller utanför projektets schema är inte tillåtna")

    return _with_row_limit(sql, tree)


def _with_row_limit(sql: str, tree: exp.Expression) -> str:
    """Lägger på LIMIT utan att ändra sortering (ORDER BY ligger kvar i samma frågenivå)."""
    if isinstance(tree, exp.Select):
        limit = tree.args.get("limit")
        if limit is None:
            return f"{sql}\nLIMIT {MAX_ROWS}"
        if limit.expression.is_int and int(limit.expression.name) <= MAX_ROWS:
            return sql
    return f"SELECT * FROM (\n{sql}\n) LIMIT {MAX_ROWS}"
