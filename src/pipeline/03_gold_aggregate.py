# Databricks notebook source
# MAGIC %md
# MAGIC # Gold: aggregat som appen frågar mot
# MAGIC Tabell- och kolumnkommentarer är dokumentation och samtidigt kontext till LLM:en.
# MAGIC Håll dem i synk med `app/schema_context.py`.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "cykelstaden")
target = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"

# Gemensam vy med bara de kolumner som aggregaten behöver (kolumnbeskärning sker sedan automatiskt i Delta).
spark.sql(f"""
CREATE OR REPLACE TEMPORARY VIEW trips AS
SELECT start_date, start_hour, weekday, member_casual, rideable_type, duration_min,
       start_station_name, end_station_name, start_lat, start_lng
FROM {target}.silver_trips
""")

# COMMAND ----------

GOLD = {
    "gold_trips_daily": (
        "Antal resor och medelrestid per dag, användartyp och cykeltyp",
        """SELECT start_date AS trip_date, member_casual, rideable_type,
                  COUNT(*) AS trips, ROUND(AVG(duration_min), 1) AS avg_duration_min
           FROM trips GROUP BY start_date, member_casual, rideable_type""",
        {
            "trip_date": "Dag",
            "member_casual": "member eller casual",
            "rideable_type": "classic_bike eller electric_bike",
            "trips": "Antal resor",
            "avg_duration_min": "Medelrestid i minuter",
        },
    ),
    "gold_trips_hourly": (
        "Antal resor per veckodag, timme på dygnet och användartyp",
        """SELECT weekday, start_hour, member_casual,
                  COUNT(*) AS trips, ROUND(AVG(duration_min), 1) AS avg_duration_min
           FROM trips GROUP BY weekday, start_hour, member_casual""",
        {
            "weekday": "Engelskt dagsnamn",
            "start_hour": "Timme 0-23",
            "member_casual": "member eller casual",
            "trips": "Antal resor",
            "avg_duration_min": "Medelrestid i minuter",
        },
    ),
    "gold_stations": (
        "Statistik per startstation: antal resor, medelrestid och position",
        """SELECT start_station_name AS station_name,
                  ROUND(AVG(start_lat), 5) AS lat, ROUND(AVG(start_lng), 5) AS lng,
                  COUNT(*) AS trips_started, ROUND(AVG(duration_min), 1) AS avg_duration_min
           FROM trips WHERE start_station_name IS NOT NULL AND start_station_name <> ''
           GROUP BY start_station_name""",
        {
            "station_name": "Stationens namn",
            "lat": "Latitud",
            "lng": "Longitud",
            "trips_started": "Antal resor som startar här",
            "avg_duration_min": "Medelrestid i minuter",
        },
    ),
    "gold_station_routes": (
        "Antal resor mellan par av start- och slutstation",
        """SELECT start_station_name, end_station_name,
                  COUNT(*) AS trips, ROUND(AVG(duration_min), 1) AS avg_duration_min
           FROM trips
           WHERE start_station_name IS NOT NULL AND end_station_name IS NOT NULL
             AND start_station_name <> '' AND end_station_name <> ''
           GROUP BY start_station_name, end_station_name""",
        {
            "start_station_name": "Startstation",
            "end_station_name": "Slutstation",
            "trips": "Antal resor",
            "avg_duration_min": "Medelrestid i minuter",
        },
    ),
}

for table, (comment, select_sql, columns) in GOLD.items():
    # CREATE OR REPLACE ersätter atomiskt, så appen läser aldrig en halvfärdig tabell, och behåller behörigheter.
    spark.sql(f"CREATE OR REPLACE TABLE {target}.{table} COMMENT '{comment}' AS {select_sql}")
    for column, text in columns.items():
        spark.sql(f"COMMENT ON COLUMN {target}.{table}.{column} IS '{text}'")
    n = spark.table(f"{target}.{table}").count()
    assert n > 0, f"{table} blev tom"
    print(f"{table}: {n} rader")
