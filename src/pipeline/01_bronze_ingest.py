# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze: ladda ner Citi Bike-filer och skriv rådata till Delta
# MAGIC Källa: https://s3.amazonaws.com/tripdata/ (öppen data). Rådata sparas oförändrad plus metadata.

# COMMAND ----------

import io
import urllib.request
import zipfile

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "cykelstaden")
dbutils.widgets.text("months", "202409")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
months = [m.strip() for m in dbutils.widgets.get("months").split(",") if m.strip()]

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.raw")
raw_dir = f"/Volumes/{catalog}/{schema}/raw"

# COMMAND ----------

# Ladda ner och packa upp varje månad. Hoppar över redan nedladdade månader (idempotent).
for month in months:
    target = f"{raw_dir}/{month}"
    if dbutils.fs.ls(raw_dir) and any(f.name.rstrip("/") == month for f in dbutils.fs.ls(raw_dir)):
        print(f"{month}: finns redan, hoppar över")
        continue
    url = f"https://s3.amazonaws.com/tripdata/{month}-citibike-tripdata.zip"
    print(f"{month}: hämtar {url}")
    with urllib.request.urlopen(url, timeout=300) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.endswith(".csv") and not name.startswith("__MACOSX"):
                out = f"{target}/{name.split('/')[-1]}"
                dbutils.fs.mkdirs(target)
                with open(out, "wb") as fh:
                    fh.write(zf.read(name))

# COMMAND ----------

df = (
    spark.read.option("header", True)
    .option("inferSchema", False)  # rådata som strängar; typning sker i silver
    .csv(f"{raw_dir}/*/*.csv")
    .withColumn("_source_file", F.col("_metadata.file_path"))
    .withColumn("_ingested_at", F.current_timestamp())
)

df.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(
    f"{catalog}.{schema}.bronze_trips"
)
print(spark.table(f"{catalog}.{schema}.bronze_trips").count(), "rader i bronze_trips")
