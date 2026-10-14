# Databricks notebook source
# MAGIC %md
# MAGIC # Silver: typning, rensning och inkrementell MERGE
# MAGIC Bara rader som lästs in sedan förra körningen bearbetas. Datakvalitet säkras med Delta-constraints
# MAGIC (databasen vägrar skriva ogiltiga rader) och kontroller av hur stor andel som filtrerades bort.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.utils import AnalysisException

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "cykelstaden")
target = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {target}.silver_trips (
  ride_id STRING NOT NULL COMMENT 'Unikt resa-id',
  rideable_type STRING COMMENT 'classic_bike eller electric_bike',
  started_at TIMESTAMP COMMENT 'Starttid',
  ended_at TIMESTAMP COMMENT 'Sluttid',
  start_station_name STRING, end_station_name STRING,
  start_lat DOUBLE, start_lng DOUBLE, end_lat DOUBLE, end_lng DOUBLE,
  member_casual STRING COMMENT 'member (prenumerant) eller casual (enstaka)',
  duration_min DOUBLE COMMENT 'Restid i minuter',
  start_date DATE, start_hour INT, weekday STRING COMMENT 'Engelskt dagsnamn',
  _ingested_at TIMESTAMP COMMENT 'När raden lästes in i bronze'
)
COMMENT 'Rensade och typade Citi Bike-resor, en rad per ride_id'
""")

for name, rule in {
    "valid_duration": "duration_min BETWEEN 1 AND 1440",
    "valid_user_type": "member_casual IN ('member', 'casual')",
    "valid_hour": "start_hour BETWEEN 0 AND 23",
}.items():
    try:
        spark.sql(f"ALTER TABLE {target}.silver_trips ADD CONSTRAINT {name} CHECK ({rule})")
    except AnalysisException as e:
        if "already exists" not in str(e).lower():
            raise

# COMMAND ----------

last_ingested = spark.sql(
    f"SELECT COALESCE(MAX(_ingested_at), TIMESTAMP'1970-01-01') AS t FROM {target}.silver_trips"
).first()["t"]
new_rows = spark.table(f"{target}.bronze_trips").filter(F.col("_ingested_at") > F.lit(last_ingested))
n_in = new_rows.count()
print(f"Nya bronze-rader sedan {last_ingested}: {n_in}")

# COMMAND ----------

if n_in > 0:
    typed = new_rows.select(
        "ride_id",
        "rideable_type",
        F.to_timestamp("started_at").alias("started_at"),
        F.to_timestamp("ended_at").alias("ended_at"),
        F.trim("start_station_name").alias("start_station_name"),
        F.trim("end_station_name").alias("end_station_name"),
        F.col("start_lat").cast("double").alias("start_lat"),
        F.col("start_lng").cast("double").alias("start_lng"),
        F.col("end_lat").cast("double").alias("end_lat"),
        F.col("end_lng").cast("double").alias("end_lng"),
        "member_casual",
        "_ingested_at",
    ).withColumn("duration_min", (F.unix_timestamp("ended_at") - F.unix_timestamp("started_at")) / 60.0)

    clean = (
        typed.filter(F.col("ride_id").isNotNull() & F.col("started_at").isNotNull() & F.col("ended_at").isNotNull())
        .filter(F.col("duration_min").between(1, 24 * 60))  # tar bort felmätningar och resor över ett dygn
        .filter(F.col("member_casual").isin("member", "casual"))
        .dropDuplicates(["ride_id"])
        .withColumn("start_date", F.to_date("started_at"))
        .withColumn("start_hour", F.hour("started_at"))
        .withColumn("weekday", F.date_format("started_at", "EEEE"))
    )
    clean.createOrReplaceTempView("silver_batch")

    # MERGE gör omkörningar säkra: ett redan inläst ride_id skrivs aldrig två gånger.
    spark.sql(f"""
        MERGE INTO {target}.silver_trips t
        USING silver_batch s ON t.ride_id = s.ride_id
        WHEN NOT MATCHED THEN INSERT *
    """)

    n_kept = clean.count()
    kept_ratio = n_kept / n_in
    print(f"Behöll {n_kept} av {n_in} rader ({kept_ratio:.1%}), borttagna: {n_in - n_kept}")
    assert n_kept > 0, "Hela batchen filtrerades bort - kontrollera källan"
    assert kept_ratio > 0.9, f"Bara {kept_ratio:.1%} av raderna behölls - kontrollera källan"

print("Rader i silver_trips:", spark.table(f"{target}.silver_trips").count())
