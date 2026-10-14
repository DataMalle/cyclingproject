"""LLM-lagret: fråga till SQL, självkorrigering och sammanfattning."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from schema_context import SUMMARY_PROMPT, SYSTEM_PROMPT

log = logging.getLogger("cykelstaden.llm")

ChatFn = Callable[[str, str], str]


class CannotAnswerError(Exception):
    """Frågan kan inte besvaras med datat som finns."""


class LlmError(RuntimeError):
    """LLM-anropet misslyckades."""


def normalize_question(text: str) -> str:
    """Normaliserad cache-nyckel: gemener och enkla blanksteg."""
    return " ".join(text.lower().split())


def strip_fences(text: str) -> str:
    return re.sub(r"^```(?:sql)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE).strip()


def databricks_chat(client: WorkspaceClient, endpoint: str, *, attempts: int = 2) -> ChatFn:
    """Chatt mot en Databricks Model Serving-endpoint, med ett omförsök vid tillfälliga fel."""

    def chat(system: str, user: str) -> str:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = client.serving_endpoints.query(
                    name=endpoint,
                    messages=[
                        ChatMessage(role=ChatMessageRole.SYSTEM, content=system),
                        ChatMessage(role=ChatMessageRole.USER, content=user),
                    ],
                    max_tokens=700,
                    temperature=0,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                last = e
                log.warning("LLM-försök %d/%d misslyckades: %s", attempt + 1, attempts, e)
                time.sleep(2)
        raise LlmError(str(last)) from last

    return chat


@dataclass(frozen=True)
class SqlAgent:
    chat: ChatFn

    def generate_sql(self, question: str, *, previous_sql: str | None = None, error: str | None = None) -> str:
        """Skriver SQL för frågan. Med previous_sql/error ombeds modellen rätta ett misslyckat försök."""
        user = question
        if previous_sql and error:
            user = (
                f"{question}\n\nDin förra SQL misslyckades.\nSQL:\n{previous_sql}\nFel: {error[:300]}\n"
                "Skriv en korrigerad SQL-fråga."
            )
        sql = strip_fences(self.chat(SYSTEM_PROMPT, user))
        if sql.strip().upper() == "CANNOT_ANSWER":
            raise CannotAnswerError
        return sql

    def summarize(self, question: str, sql: str, df: pd.DataFrame) -> str:
        return self.chat(SUMMARY_PROMPT, f"Fråga: {question}\nSQL: {sql}\n\n{describe_result(df)}")


def _fmt(value: object) -> str:
    """Tal med mellanslag som tusentalsavgränsare, så att modellen inte tappar siffror."""
    if value is None or isinstance(value, bool | np.bool_) or pd.isna(value):
        return str(value)
    if isinstance(value, int | float | np.integer | np.floating):  # numpy-tal är inte Pythons int/float
        number = float(value)
        return f"{number:,.0f}".replace(",", " ") if number.is_integer() else f"{number:,.1f}".replace(",", " ")
    return str(value)


def describe_result(df: pd.DataFrame, max_rows: int = 30) -> str:
    """Resultatet som formaterad tabell plus förräknade fakta (max, min, summa).

    Små språkmodeller räknar och läser långa tal opålitligt, så siffrorna räknas här och modellen får bara återge dem.
    """
    if df.empty:
        return "Resultat: inga rader."
    lines = [f"Resultat: {len(df)} rader (visar de första {min(len(df), max_rows)})."]
    header = " | ".join(df.columns)
    rows = [" | ".join(_fmt(v) for v in row) for row in df.head(max_rows).itertuples(index=False, name=None)]
    lines += [header, *rows, "", "Förräknade fakta:"]
    label_col = next((c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])), df.columns[0])
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]) or col == label_col:
            continue
        top, bottom = df.loc[df[col].idxmax()], df.loc[df[col].idxmin()]
        lines.append(
            f"- {col}: högst {_fmt(top[col])} ({label_col} = {_fmt(top[label_col])}), "
            f"lägst {_fmt(bottom[col])} ({label_col} = {_fmt(bottom[label_col])}), summa {_fmt(df[col].sum())}"
        )
    return "\n".join(lines)
