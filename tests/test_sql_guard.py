import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from sql_guard import UnsafeSqlError, validate_and_limit  # noqa: E402


def test_allows_simple_select_and_adds_limit():
    out = validate_and_limit("SELECT station_name FROM gold_stations ORDER BY trips_started DESC LIMIT 10;")
    assert out.endswith("LIMIT 500")


def test_allows_cte():
    sql = "WITH t AS (SELECT * FROM gold_trips_daily) SELECT SUM(trips) FROM t"
    assert "gold_trips_daily" in validate_and_limit(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE gold_stations",
        "DELETE FROM gold_stations",
        "SELECT * FROM silver_trips",
        "SELECT * FROM system.information_schema.tables",
        "SELECT 1; DROP TABLE gold_stations",
        "INSERT INTO gold_stations VALUES (1)",
    ],
)
def test_rejects_unsafe(sql):
    with pytest.raises(UnsafeSqlError):
        validate_and_limit(sql)
