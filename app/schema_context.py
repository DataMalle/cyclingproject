"""Schemabeskrivning och prompts till LLM:en. Håll i synk med src/pipeline/03_gold_aggregate.py."""

SCHEMA_DESCRIPTION = """
Tabeller (Citi Bike NYC, resor i september 2024, ca 5 miljoner resor):

gold_trips_daily(trip_date DATE, member_casual STRING 'member'|'casual',
  rideable_type STRING 'classic_bike'|'electric_bike', trips BIGINT, avg_duration_min DOUBLE)
  -> resor per dag, användartyp och cykeltyp.

gold_trips_hourly(weekday STRING engelska dagsnamn t.ex. 'Monday', start_hour INT 0-23,
  member_casual STRING, trips BIGINT, avg_duration_min DOUBLE)
  -> resor per veckodag och timme.

gold_stations(station_name STRING, lat DOUBLE, lng DOUBLE, trips_started BIGINT, avg_duration_min DOUBLE)
  -> en rad per startstation.

gold_station_routes(start_station_name STRING, end_station_name STRING, trips BIGINT, avg_duration_min DOUBLE)
  -> populära rutter mellan stationer.
"""

EXAMPLES = """
Exempel:
Fråga: Vilka 5 stationer har flest resor?
SQL: SELECT station_name, trips_started FROM gold_stations ORDER BY trips_started DESC LIMIT 5

Fråga: Hur många resor görs per timme en måndag av members?
SQL: SELECT start_hour, SUM(trips) AS trips FROM gold_trips_hourly WHERE weekday = 'Monday' AND member_casual = 'member' GROUP BY start_hour ORDER BY start_hour

Fråga: Hur utvecklas antalet resor per dag?
SQL: SELECT trip_date, SUM(trips) AS trips FROM gold_trips_daily GROUP BY trip_date ORDER BY trip_date

Fråga: Hur många resor börjar vid Broadway?
SQL: SELECT SUM(trips_started) AS trips FROM gold_stations WHERE LOWER(station_name) LIKE '%broadway%'
"""

SYSTEM_PROMPT = f"""Du är en dataanalytiker som översätter frågor på svenska till Databricks SQL.
Regler:
- Svara ENDAST med en SQL-fråga. Ingen förklaring och inga markdown-staket.
- Exakt ett SELECT-uttryck. Använd bara tabellerna nedan, utan katalog- eller schemaprefix.
- Ge kolumnerna läsbara alias (t.ex. trips, avg_duration_min). Sortera resultatet och använd LIMIT när det är rimligt.
- Jämför text skiftlägesokänsligt (LOWER eller ILIKE), särskilt stationsnamn.
- Om frågan inte kan besvaras med tabellerna, svara med exakt: CANNOT_ANSWER
{SCHEMA_DESCRIPTION}{EXAMPLES}"""

SUMMARY_PROMPT = """Du får en användarfråga, SQL, en resultattabell och förräknade fakta (högst, lägst, summa).
Svara på svenska i två till tre korta meningar som bara bygger på det underlaget.
- Återge siffror exakt som de står i underlaget, med mellanslag som tusentalsavgränsare. Korta aldrig ner eller avrunda tal.
- Använd de förräknade fakta för högsta, lägsta och summa istället för att räkna själv.
- Nämn det viktigaste först. Hitta aldrig på siffror som inte finns i underlaget."""
