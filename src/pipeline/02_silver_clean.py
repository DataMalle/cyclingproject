# Databricks notebook source
# MAGIC %md
# MAGIC # Silver: typning, rensning och härledda kolumner

# COMMAND ----------

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "cykelstaden")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

bronze = spark.table(f"{catalog}.{schema}.bronze_trips")

# COMMAND ----------

typed = (
    bronze.select(
        "ride_id",
        F.col("rideable_type"),
        F.to_timestamp("started_at").alias("started_at"),
        F.to_timestamp("ended_at").alias("ended_at"),
        F.trim("start_station_name").alias("start_station_name"),
        F.trim("end_station_name").alias("end_station_name"),
        F.col("start_lat").cast("double").alias("start_lat"),
        F.col("start_lng").cast("double").alias("start_lng"),
        F.col("end_lat").cast("double").alias("end_lat"),
        F.col("end_lng").cast("double").alias("end_lng"),
        F.col("member_casual"),
    )
    .withColumn(
        "duration_min",
        (F.unix_timestamp("ended_at") - F.unix_timestamp("started_at")) / 60.0,
    )
)

clean = (
    typed.dropDuplicates(["ride_id"])
    .filter(F.col("ride_id").isNotNull())
    .filter(F.col("started_at").isNotNull() & F.col("ended_at").isNotNull())
    .filter(F.col("duration_min").between(1, 24 * 60))  # tar bort felmätningar och > 24 h
    .filter(F.col("member_casual").isin("member", "casual"))
    .withColumn("start_date", F.to_date("started_at"))
    .withColumn("start_hour", F.hour("started_at"))
    .withColumn("weekday", F.date_format("started_at", "EEEE"))
)

# COMMAND ----------

clean.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(
    f"{catalog}.{schema}.silver_trips"
)

n_in = bronze.count()
n_out = spark.table(f"{catalog}.{schema}.silver_trips").count()
print(f"Bronze: {n_in}, Silver: {n_out}, borttagna: {n_in - n_out}")
assert n_out > 0, "Silver är tom - något är fel i rensningen"
assert n_out / n_in > 0.5, "Mer än hälften av raderna filtrerades bort - kontrollera källan"
