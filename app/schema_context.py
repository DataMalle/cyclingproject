"""Schemabeskrivning som skickas till LLM:en. Håll i synk med src/pipeline/03_gold_aggregate.py."""

SCHEMA_DESCRIPTION = """
Tabeller (Citi Bike NYC, resor sep 2024):

gold_trips_daily(trip_date DATE, member_casual STRING 'member'|'casual', rideable_type STRING
  'classic_bike'|'electric_bike', trips BIGINT, avg_duration_min DOUBLE)
  -> resor per dag, användartyp och cykeltyp.

gold_trips_hourly(weekday STRING engelska dagsnamn t.ex. 'Monday', start_hour INT 0-23,
  member_casual STRING, trips BIGINT, avg_duration_min DOUBLE)
  -> resor per veckodag och timme.

gold_stations(station_name STRING, lat DOUBLE, lng DOUBLE, trips_started BIGINT, avg_duration_min DOUBLE)
  -> en rad per startstation.

gold_station_routes(start_station_name STRING, end_station_name STRING, trips BIGINT, avg_duration_min DOUBLE)
  -> populära rutter mellan stationer.
"""

SYSTEM_PROMPT = f"""Du är en dataanalytiker som översätter frågor till Databricks SQL.
Regler:
- Svara ENDAST med en SQL-fråga, ingen förklaring och inga markdown-staket.
- Skriv exakt ett SELECT-uttryck. Använd bara tabellerna nedan, utan katalog- eller schemaprefix.
- Använd aggregering och ORDER BY/LIMIT när det är rimligt.
- Om frågan inte kan besvaras med tabellerna, svara med exakt: CANNOT_ANSWER
{SCHEMA_DESCRIPTION}"""

SUMMARY_PROMPT = """Du får en användarfråga, SQL och resultatrader. Svara kort och sakligt på svenska
med några meningar baserat enbart på resultatet. Hitta inte på siffror."""
