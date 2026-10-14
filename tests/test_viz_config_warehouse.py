import pandas as pd
import pytest

from config import ConfigError, load_settings
from viz import chart_spec
from warehouse import _is_transient, to_frame

# --- diagramval ---


def test_time_series_gets_line_chart():
    df = pd.DataFrame({"trip_date": pd.to_datetime(["2024-09-01", "2024-09-02"]), "trips": [10, 20]})
    spec = chart_spec(df)
    assert (spec.kind, spec.x, spec.y) == ("line", "trip_date", "trips")


def test_category_gets_horizontal_bars():
    df = pd.DataFrame({"station_name": ["A", "B", "C"], "trips": [3, 2, 1]})
    assert chart_spec(df).kind == "hbar"


def test_integer_axis_like_hour_gets_vertical_bars():
    df = pd.DataFrame({"start_hour": list(range(24)), "trips": list(range(24))})
    spec = chart_spec(df)
    assert (spec.kind, spec.x, spec.y) == ("bar", "start_hour", "trips")


@pytest.mark.parametrize(
    "df",
    [
        pd.DataFrame({"trips": [5]}),  # en rad
        pd.DataFrame({"name": ["a", "b"]}),  # inga numeriska kolumner
        pd.DataFrame({"name": [f"s{i}" for i in range(31)], "n": range(31)}),  # för många kategorier
    ],
)
def test_no_chart_when_it_would_not_help(df):
    assert chart_spec(df) is None


# --- konfiguration ---


def test_load_settings_defaults():
    s = load_settings({"DATABRICKS_WAREHOUSE_ID": "w", "LLM_ENDPOINT": "e"})
    assert (s.warehouse_id, s.llm_endpoint, s.catalog, s.schema) == ("w", "e", "workspace", "cykelstaden")


def test_load_settings_lists_everything_missing():
    with pytest.raises(ConfigError) as e:
        load_settings({})
    assert "DATABRICKS_WAREHOUSE_ID" in str(e.value) and "LLM_ENDPOINT" in str(e.value)


# --- warehouse ---


def test_to_frame_types_numbers_and_dates():
    df = to_frame(
        [("name", "STRING"), ("trips", "LONG"), ("avg", "DOUBLE"), ("day", "DATE")],
        [["W 21 St", "17441", "12.5", "2024-09-01"], ["B 14", None, "3.0", "2024-09-02"]],
    )
    assert pd.api.types.is_numeric_dtype(df["trips"]) and pd.api.types.is_numeric_dtype(df["avg"])
    assert pd.api.types.is_datetime64_any_dtype(df["day"])
    assert df["name"].iloc[0] == "W 21 St"
    assert pd.isna(df["trips"].iloc[1])


def test_to_frame_empty_result_keeps_columns():
    df = to_frame([("a", "LONG")], [])
    assert list(df.columns) == ["a"] and df.empty


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Databricks SQL warehouse startade inte i tid", True),
        ("Request timeout", True),
        ("[UNRESOLVED_COLUMN] column x not found", False),
    ],
)
def test_transient_error_detection(message, expected):
    assert _is_transient(RuntimeError(message)) is expected
