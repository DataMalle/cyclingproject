"""Validerar att LLM-genererad SQL är ett enda skrivskyddat SELECT mot tillåtna tabeller."""
import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {
    "gold_trips_daily",
    "gold_trips_hourly",
    "gold_stations",
    "gold_station_routes",
}

MAX_ROWS = 500


class UnsafeSqlError(ValueError):
    pass


def validate_and_limit(sql: str) -> str:
    """Returnerar säker SQL med LIMIT, eller kastar UnsafeSqlError."""
    sql = sql.strip().rstrip(";")
    try:
        statements = sqlglot.parse(sql, read="databricks")
    except sqlglot.errors.ParseError as e:
        raise UnsafeSqlError(f"Kunde inte tolka SQL: {e}") from e

    if len(statements) != 1 or statements[0] is None:
        raise UnsafeSqlError("Endast ett SQL-uttryck tillåts")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.With)) and not tree.find(exp.Select):
        raise UnsafeSqlError("Endast SELECT tillåts")
    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Merge)
    if tree.find(*forbidden):
        raise UnsafeSqlError("Skrivande eller administrativa uttryck är inte tillåtna")

    cte_names = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name
        if name in cte_names:
            continue
        if name not in ALLOWED_TABLES:
            raise UnsafeSqlError(f"Tabellen '{name}' är inte tillåten")

    return f"SELECT * FROM ({sql}) LIMIT {MAX_ROWS}"
