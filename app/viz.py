"""Val och rendering av diagram utifrån formen på ett frågeresultat."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import altair as alt
import pandas as pd
import streamlit as st

from style import TEAL

MAX_CATEGORIES = 30


@dataclass(frozen=True)
class ChartSpec:
    kind: Literal["line", "hbar", "bar"]
    x: str
    y: str


def chart_spec(df: pd.DataFrame) -> ChartSpec | None:
    """Väljer diagramtyp: tidsserie -> linje, kategori -> liggande staplar, heltalsaxel (t.ex. timme) -> staplar."""
    if df is None or len(df) < 2:
        return None
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    if not numeric:
        return None
    temporal = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    if temporal:
        y = next((c for c in numeric if c != temporal[0]), None)
        return ChartSpec("line", temporal[0], y) if y else None
    categorical = [c for c in df.columns if c not in numeric]
    if categorical and len(df) <= MAX_CATEGORIES:
        return ChartSpec("hbar", categorical[0], numeric[0])
    first = numeric[0]
    if len(numeric) >= 2 and pd.api.types.is_integer_dtype(df[first]) and df[first].nunique() <= 40:
        return ChartSpec("bar", first, numeric[1])
    return None


def render_chart(spec: ChartSpec, df: pd.DataFrame) -> None:
    tooltip = [alt.Tooltip(field=spec.x), alt.Tooltip(field=spec.y)]
    base = alt.Chart(df)
    if spec.kind == "line":
        chart = base.mark_line(color=TEAL, strokeWidth=2).encode(
            x=alt.X(field=spec.x, type="temporal", title=None, axis=alt.Axis(format="%d %b", labelOverlap=True)),
            y=alt.Y(field=spec.y, type="quantitative", title=spec.y),
            tooltip=tooltip,
        )
    elif spec.kind == "hbar":
        chart = base.mark_bar(color=TEAL, cornerRadiusEnd=3).encode(
            y=alt.Y(
                field=spec.x,
                type="nominal",
                sort="-x",
                title=None,
                axis=alt.Axis(labelLimit=320, labelOverlap=False),
            ),
            x=alt.X(field=spec.y, type="quantitative", title=spec.y),
            tooltip=tooltip,
        )
    else:
        chart = base.mark_bar(color=TEAL, cornerRadiusEnd=3).encode(
            x=alt.X(field=spec.x, type="ordinal", title=spec.x),
            y=alt.Y(field=spec.y, type="quantitative", title=spec.y),
            tooltip=tooltip,
        )
    st.altair_chart(chart.properties(height=max(220, 32 * len(df)) if spec.kind == "hbar" else 280), width="stretch")
