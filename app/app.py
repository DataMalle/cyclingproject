"""Cykelstaden: ställ frågor på svenska om Citi Bike-data (Streamlit-gränssnitt)."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

import pandas as pd
import streamlit as st
from databricks.sdk import WorkspaceClient

from config import ConfigError, Settings, load_settings
from llm import CannotAnswerError, LlmError, SqlAgent, databricks_chat, normalize_question
from ratelimit import MAX_QUESTION_CHARS, RateLimiter
from sql_guard import MAX_ROWS, UnsafeSqlError, validate_and_limit
from style import hero, inject_style
from viz import chart_spec, render_chart
from warehouse import Warehouse, WarehouseError

st.set_page_config(page_title="Cykelstaden - Malvin Portfolio Project", page_icon="🚲", layout="wide")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("cykelstaden")

REPO_URL = "https://github.com/DataMalle/cyclingproject"
EXAMPLES = [
    "Vilka 10 stationer har flest resor?",
    "Hur skiljer sig morgonrusningen mellan members och casual-användare?",
    "Hur utvecklas antalet resor per dag?",
    "Vilken är den vanligaste rutten?",
]


# --- Tjänster och cache -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Services:
    settings: Settings
    warehouse: Warehouse
    agent: SqlAgent
    limiter: RateLimiter


def _load_streamlit_secrets_into_env() -> None:
    """Streamlit Community Cloud: lägg secrets i miljön så att Databricks-SDK:t hittar dem."""
    try:
        for key, value in st.secrets.items():
            if isinstance(value, str):
                os.environ.setdefault(key, value)
    except Exception:
        pass


@st.cache_resource
def services() -> Services:
    settings = load_settings()
    client = WorkspaceClient()
    warehouse = Warehouse(client, settings.warehouse_id, settings.catalog, settings.schema)
    # Väck warehouse i bakgrunden medan besökaren läser sidan, så att första frågan går snabbare.
    threading.Thread(target=lambda: _safe_prewarm(warehouse), daemon=True).start()
    return Services(settings, warehouse, SqlAgent(databricks_chat(client, settings.llm_endpoint)), RateLimiter())


def _safe_prewarm(warehouse: Warehouse) -> None:
    try:
        warehouse.query("SELECT 1", attempts=1)
    except Exception as e:
        log.info("Förvärmning misslyckades (ofarligt): %s", e)


@st.cache_data(ttl=3600, max_entries=512, show_spinner=False)
def cached_sql(question_key: str, _question: str) -> str:
    """SQL per normaliserad fråga. _question (ej hashad) behåller stora bokstäver i stationsnamn."""
    return services().agent.generate_sql(_question)


@st.cache_data(ttl=1800, max_entries=512, show_spinner=False)
def cached_query(sql: str) -> pd.DataFrame:
    return services().warehouse.query(sql)


@st.cache_data(ttl=3600, max_entries=512, show_spinner=False)
def cached_summary(question_key: str, sql: str, _question: str, _df: pd.DataFrame) -> str:
    return services().agent.summarize(_question, sql, _df)


@st.cache_data(ttl=3600, show_spinner=False)
def dataset_overview() -> dict:
    wh = services().warehouse
    totals = wh.query("SELECT SUM(trips_started) AS trips, COUNT(*) AS stations FROM gold_stations").iloc[0]
    span = wh.query("SELECT MIN(trip_date) AS first_day, MAX(trip_date) AS last_day FROM gold_trips_daily").iloc[0]
    return {
        "trips": int(totals["trips"]),
        "stations": int(totals["stations"]),
        "first_day": span["first_day"],
        "last_day": span["last_day"],
    }


# --- Gränssnitt ---------------------------------------------------------------------------------------------------


_MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def _short_date(day: pd.Timestamp) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]}"


def _thousands(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def render_overview(slot) -> None:
    try:
        o = dataset_overview()
    except Exception as e:
        log.warning("Kunde inte hämta dataöversikt: %s", e)
        return
    with slot:
        c1, c2, c3 = st.columns(3)
        c1.metric("Resor i datat", f"{o['trips'] / 1e6:.2f} M".replace(".", ","))
        c2.metric("Stationer", _thousands(o["stations"]))
        c3.metric(f"Period {o['last_day']:%Y}", f"{_short_date(o['first_day'])} – {_short_date(o['last_day'])}")


def _column_config(df: pd.DataFrame) -> dict:
    """Tusentalsavgränsare på tal och rena datum utan klockslag."""
    config: dict = {c: st.column_config.NumberColumn(format="localized") for c in df.select_dtypes("number").columns}
    for col in df.select_dtypes("datetime").columns:
        if (df[col].dt.normalize() == df[col]).all():
            config[col] = st.column_config.DateColumn(format="YYYY-MM-DD")
    return config


def render_result(df: pd.DataFrame, sql: str) -> None:
    with st.container(border=True, key="card_data"):
        spec = chart_spec(df)
        if spec:
            render_chart(spec, df)
        if df.empty:
            st.info("Frågan gav inga rader.")
        else:
            note = f"{len(df)} rader" + (f", visar de första {MAX_ROWS}" if len(df) >= MAX_ROWS else "")
            st.caption(note)
            st.dataframe(df, hide_index=True, width="stretch", column_config=_column_config(df))
    with st.expander("Visa genererad SQL"):
        st.code(sql, language="sql")


def answer_question(svc: Services, question: str) -> None:
    key = normalize_question(question)
    schema_args = {"catalog": svc.settings.catalog, "schema": svc.settings.schema}
    try:
        with st.status("Arbetar på din fråga …", expanded=False) as status:
            status.update(label="Översätter frågan till SQL …")
            sql = cached_sql(key, question)
            safe_sql = validate_and_limit(sql, **schema_args)
            status.update(label="Kör mot Databricks …")
            try:
                df = cached_query(safe_sql)
            except WarehouseError as first_error:
                # LLM:en får se felet och rätta sin SQL en gång innan vi ger upp.
                log.info("SQL misslyckades, ber modellen rätta: %s", first_error)
                status.update(label="Rättar SQL och försöker igen …")
                sql = svc.agent.generate_sql(question, previous_sql=sql, error=str(first_error))
                safe_sql = validate_and_limit(sql, **schema_args)
                df = cached_query(safe_sql)
            status.update(label="Klar", state="complete")
    except CannotAnswerError:
        st.warning(
            "Den frågan kan inte besvaras med datat som finns (Citi Bike-resor, stationer och rutter). "
            "Prova en annan formulering."
        )
        return
    except UnsafeSqlError as e:
        log.warning("SQL avvisad av säkerhetskontrollen: %s", e)
        st.error("Den genererade frågan avvisades av säkerhetskontrollen. Prova att formulera om frågan.")
        return
    except (WarehouseError, LlmError) as e:
        log.exception("Fråga misslyckades")
        st.error("Något gick fel när frågan skulle besvaras. Försök igen om en stund.")
        with st.expander("Teknisk detalj"):
            st.code(str(e)[:500])
        return

    answer = st.container(border=True, key="card_answer")
    with answer:
        st.markdown("**Svar**")
        placeholder = st.empty()
        placeholder.caption("Sammanfattar …")
    render_result(df, sql)  # tabellen visas direkt, sammanfattningen fylls i när den är klar
    try:
        placeholder.markdown(cached_summary(key, safe_sql, question, df))
    except Exception as e:
        log.warning("Sammanfattning misslyckades: %s", e)
        placeholder.caption("Sammanfattningen kunde inte skapas, men resultatet visas nedan.")


def _pick_example() -> None:
    choice = st.session_state.get("example_pick")
    if choice:
        st.session_state["q_text"] = choice
        st.session_state["run_now"] = True


def main() -> None:
    inject_style()
    hero(
        "Cykelstaden",
        "Malvin Portfolio Project · Ställ frågor på svenska om 5 miljoner Citi Bike-resor. "
        "Svaren kommer från en ETL-pipeline i Databricks.",
        "Live · Databricks + LLM",
    )
    _load_streamlit_secrets_into_env()
    try:
        svc = services()
    except ConfigError as e:
        st.error(f"Appen saknar konfiguration: {e}. Lägg till dem under App settings → Secrets.")
        st.stop()

    overview_slot = st.container()  # fylls sist, så att sidan inte väntar på ett kallt warehouse

    st.pills("Prova en fråga", EXAMPLES, key="example_pick", on_change=_pick_example, label_visibility="collapsed")
    with st.form("ask_form", border=False):
        col_input, col_button = st.columns([6, 1], vertical_alignment="bottom")
        question = col_input.text_input(
            "Din fråga",
            key="q_text",
            placeholder="t.ex. Vilka stationer är mest populära på morgonen?",
            label_visibility="collapsed",
        )
        submitted = col_button.form_submit_button("Fråga", type="primary", width="stretch")
    run_now = st.session_state.pop("run_now", False)

    if (submitted or run_now) and question.strip():
        if len(question) > MAX_QUESTION_CHARS:
            st.warning(f"Frågan är för lång (max {MAX_QUESTION_CHARS} tecken).")
        elif blocked := svc.limiter.check(st.session_state):
            st.warning(blocked)
        else:
            answer_question(svc, question.strip())

    render_overview(overview_slot)
    st.caption(
        f"Data: Citi Bike System Data, september 2024. Frågorna översätts av en LLM, så kontrollera SQL:en "
        f"vid tveksamhet. [Källkod]({REPO_URL})"
    )


main()
