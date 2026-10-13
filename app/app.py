import os
import re
import time

import pandas as pd
import streamlit as st
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
from databricks.sdk.service.sql import StatementState

from ratelimit import MAX_QUESTION_CHARS, RateLimiter
from schema_context import SUMMARY_PROMPT, SYSTEM_PROMPT
from sql_guard import UnsafeSqlError, validate_and_limit

st.set_page_config(page_title="Cykelstaden - Malvin Portfolio Project", page_icon="🚲", layout="wide")

# Streamlit Community Cloud: lägg secrets i miljön om de inte redan finns där.
try:
    for _key, _val in st.secrets.items():
        if isinstance(_val, str):
            os.environ.setdefault(_key, _val)
except Exception:  # inga secrets konfigurerade (t.ex. i Databricks Apps)
    pass

_REQUIRED = ["DATABRICKS_WAREHOUSE_ID", "LLM_ENDPOINT"]
_missing = [k for k in _REQUIRED if not os.environ.get(k)]
if _missing:
    st.error(f"Appen saknar konfiguration: {', '.join(_missing)}. Lägg till dem under App settings → Secrets.")
    st.stop()

CATALOG = os.environ.get("CATALOG", "workspace")
SCHEMA = os.environ.get("SCHEMA", "cykelstaden")
WAREHOUSE_ID = os.environ["DATABRICKS_WAREHOUSE_ID"]
LLM_ENDPOINT = os.environ["LLM_ENDPOINT"]

EXAMPLES = [
    "Vilka 10 stationer har flest resor?",
    "Hur skiljer sig morgonrusningen mellan members och casual-användare?",
    "Hur har antalet resor utvecklats per vecka?",
    "Vilken är den vanligaste rutten?",
]


@st.cache_resource
def client() -> WorkspaceClient:
    # Inom Databricks Apps eller externt (DATABRICKS_HOST + DATABRICKS_CLIENT_ID/SECRET som secrets).
    return WorkspaceClient()


@st.cache_resource
def limiter() -> RateLimiter:
    return RateLimiter()


def chat(system: str, user: str) -> str:
    resp = client().serving_endpoints.query(
        name=LLM_ENDPOINT,
        messages=[
            ChatMessage(role=ChatMessageRole.SYSTEM, content=system),
            ChatMessage(role=ChatMessageRole.USER, content=user),
        ],
        max_tokens=800,
        temperature=0,
    )
    return resp.choices[0].message.content.strip()


_DONE = {StatementState.SUCCEEDED, StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED}


def run_sql(sql: str, max_wait_s: int = 240) -> pd.DataFrame:
    """Kör SQL och väntar klart, även om warehouse måste startas först (kan ta flera minuter)."""
    api = client().statement_execution
    res = api.execute_statement(
        statement=sql, warehouse_id=WAREHOUSE_ID, catalog=CATALOG, schema=SCHEMA, wait_timeout="30s"
    )
    deadline = time.monotonic() + max_wait_s
    while res.status.state not in _DONE:
        if time.monotonic() > deadline:
            raise TimeoutError("Databricks SQL warehouse startade inte i tid. Försök igen om en stund.")
        time.sleep(2)
        res = api.get_statement(res.statement_id)
    if res.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(res.status.error.message if res.status.error else str(res.status.state))
    cols = [c.name for c in res.manifest.schema.columns]
    rows = res.result.data_array if res.result and res.result.data_array else []
    df = pd.DataFrame(rows, columns=cols)
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass  # behåll textkolumner som de är
    return df


def strip_fences(text: str) -> str:
    return re.sub(r"^```(?:sql)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)


st.title("🚲 Cykelstaden - Malvin Portfolio Project")
st.caption("Ställ en fråga om Citi Bike-resor i New York (sep 2024). Svaren bygger på en ETL-pipeline i Databricks.")

if "question" not in st.session_state:
    st.session_state.question = ""

cols = st.columns(len(EXAMPLES))
for col, example in zip(cols, EXAMPLES):
    if col.button(example, width="stretch"):
        st.session_state.question = example

question = st.text_input("Din fråga", key="question", placeholder="t.ex. Vilka stationer är mest populära på morgonen?")

if st.button("Fråga", type="primary") and question.strip():
    if len(question) > MAX_QUESTION_CHARS:
        st.warning(f"Frågan är för lång (max {MAX_QUESTION_CHARS} tecken).")
        st.stop()
    blocked = limiter().check(st.session_state)
    if blocked:
        st.warning(blocked)
        st.stop()
    with st.spinner("Tänker..."):
        try:
            raw_sql = strip_fences(chat(SYSTEM_PROMPT, question))
            if raw_sql.strip() == "CANNOT_ANSWER":
                st.warning("Den frågan kan inte besvaras med datat som finns. Prova en annan formulering.")
                st.stop()
            safe_sql = validate_and_limit(raw_sql)
            df = run_sql(safe_sql)
            summary = chat(
                SUMMARY_PROMPT,
                f"Fråga: {question}\nSQL: {raw_sql}\nResultat (första 50 rader):\n{df.head(50).to_csv(index=False)}",
            )
        except UnsafeSqlError as e:
            st.error(f"Den genererade frågan avvisades av säkerhetskontrollen: {e}")
            st.stop()
        except Exception as e:  # noqa: BLE001 - visa fel för användaren
            st.error(f"Något gick fel: {e}")
            st.stop()

    st.subheader("Svar")
    st.write(summary)
    if not df.empty:
        st.dataframe(df, width="stretch")
        numeric = df.select_dtypes("number").columns
        if len(df.columns) >= 2 and len(numeric) >= 1 and len(df) > 1:
            label = next((c for c in df.columns if c not in numeric), df.columns[0])
            st.bar_chart(df.set_index(label)[numeric[0]])
    with st.expander("Visa genererad SQL"):
        st.code(raw_sql, language="sql")
