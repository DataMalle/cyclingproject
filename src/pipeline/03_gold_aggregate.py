# Databricks notebook source
# MAGIC %md
# MAGIC # Gold: affärsklara aggregat som appen frågar mot
# MAGIC Tabell- och kolumnbeskrivningar läggs som kommentarer. Håll dem i synk med `app/schema_context.py`.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "cykelstaden")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
silver = f"{catalog}.{schema}.silver_trips"

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.{schema}.gold_trips_daily
COMMENT 'Antal resor och medelrestid per dag, användartyp och cykeltyp'
AS SELECT
  start_date AS trip_date,
  member_casual,
  rideable_type,
  COUNT(*) AS trips,
  ROUND(AVG(duration_min), 1) AS avg_duration_min
FROM {silver}
GROUP BY start_date, member_casual, rideable_type
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.{schema}.gold_trips_hourly
COMMENT 'Antal resor per veckodag, timme på dygnet och användartyp'
AS SELECT
  weekday,
  start_hour,
  member_casual,
  COUNT(*) AS trips,
  ROUND(AVG(duration_min), 1) AS avg_duration_min
FROM {silver}
GROUP BY weekday, start_hour, member_casual
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.{schema}.gold_stations
COMMENT 'Statistik per startstation: antal resor, medelrestid och position'
AS SELECT
  start_station_name AS station_name,
  ROUND(AVG(start_lat), 5) AS lat,
  ROUND(AVG(start_lng), 5) AS lng,
  COUNT(*) AS trips_started,
  ROUND(AVG(duration_min), 1) AS avg_duration_min
FROM {silver}
WHERE start_station_name IS NOT NULL AND start_station_name <> ''
GROUP BY start_station_name
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.{schema}.gold_station_routes
COMMENT 'Antal resor mellan par av start- och slutstation'
AS SELECT
  start_station_name,
  end_station_name,
  COUNT(*) AS trips,
  ROUND(AVG(duration_min), 1) AS avg_duration_min
FROM {silver}
WHERE start_station_name IS NOT NULL AND end_station_name IS NOT NULL
  AND start_station_name <> '' AND end_station_name <> ''
GROUP BY start_station_name, end_station_name
""")

# COMMAND ----------

for t in ["gold_trips_daily", "gold_trips_hourly", "gold_stations", "gold_station_routes"]:
    print(t, spark.table(f"{catalog}.{schema}.{t}").count())
