import pytest

from sql_guard import MAX_ROWS, UnsafeSqlError, validate_and_limit


def test_appends_limit_and_keeps_order_by_in_same_level():
    out = validate_and_limit("SELECT station_name FROM gold_stations ORDER BY trips_started DESC;")
    assert out.endswith(f"LIMIT {MAX_ROWS}")
    assert "ORDER BY trips_started DESC" in out.split("LIMIT")[0]
    assert "SELECT * FROM" not in out  # ingen wrapper som kan tappa sorteringen


def test_keeps_small_existing_limit():
    sql = "SELECT station_name FROM gold_stations LIMIT 10"
    assert validate_and_limit(sql) == sql


def test_caps_large_existing_limit():
    out = validate_and_limit("SELECT station_name FROM gold_stations LIMIT 100000")
    assert out.rstrip().endswith(f"LIMIT {MAX_ROWS}")
    assert "100000" in out  # inre frågan är oförändrad, den yttre cappar


def test_line_comment_cannot_swallow_limit():
    out = validate_and_limit("SELECT station_name FROM gold_stations -- kommentar")
    assert out.rstrip().endswith(f"LIMIT {MAX_ROWS}") and "\nLIMIT" in out


def test_union_is_wrapped():
    sql = "SELECT station_name FROM gold_stations UNION ALL SELECT station_name FROM gold_stations"
    assert validate_and_limit(sql).rstrip().endswith(f"LIMIT {MAX_ROWS}")


def test_allows_cte_and_project_qualified_names():
    assert validate_and_limit("WITH t AS (SELECT * FROM gold_trips_daily) SELECT SUM(trips) FROM t")
    assert validate_and_limit("SELECT * FROM workspace.cykelstaden.gold_stations")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE gold_stations",
        "DELETE FROM gold_stations",
        "INSERT INTO gold_stations VALUES (1)",
        "SELECT 1; DROP TABLE gold_stations",
        "SELECT * FROM silver_trips",
        "SELECT * FROM system.information_schema.tables",
        "SELECT * FROM other_catalog.other_schema.gold_stations",
        "SELECT * FROM workspace.other_schema.gold_stations",
        "SELECT * FROM read_files('s3://bucket/x')",
        "SELECT reflect('java.lang.Runtime', 'getRuntime') FROM gold_stations",
        "SELECT current_user() FROM gold_stations",
        "",
        "   ;  ",
    ],
)
def test_rejects_unsafe(sql):
    with pytest.raises(UnsafeSqlError):
        validate_and_limit(sql)
