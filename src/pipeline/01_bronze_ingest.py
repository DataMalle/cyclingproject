# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze: inkrementell ingest av Citi Bike-filer
# MAGIC Rådata ligger i en Unity Catalog-volym (`raw/<YYYYMM>/*.csv`). `COPY INTO` läser bara in filer som inte redan
# MAGIC lästs, så körningen är idempotent och en ny månad kostar bara den månaden.
# MAGIC
# MAGIC Notebooken försöker även hämta månaderna från källan. Det blockeras i Databricks Free Edition, och då används
# MAGIC filer som laddats upp manuellt till volymen.

# COMMAND ----------

import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "cykelstaden")
dbutils.widgets.text("months", "202409")  # kommaseparerade YYYYMM att försöka hämta
dbutils.widgets.dropdown("full_refresh", "false", ["false", "true"])  # true: bygg om bronze och silver från början

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
months = [m.strip() for m in dbutils.widgets.get("months").split(",") if m.strip()]
full_refresh = dbutils.widgets.get("full_refresh") == "true"

target = f"{catalog}.{schema}"
raw_dir = Path(f"/Volumes/{catalog}/{schema}/raw")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {target}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {target}.raw")

if full_refresh:
    # Bronze och silver byggs om från rådatafilerna. Gold ersätts i sista steget.
    spark.sql(f"DROP TABLE IF EXISTS {target}.silver_trips")
    spark.sql(f"DROP TABLE IF EXISTS {target}.bronze_trips")
    print("full_refresh: bronze och silver raderade och byggs om")

# COMMAND ----------


def download_month(month: str) -> None:
    """Strömmar zip-filen till disk och packar upp CSV-filerna i volymen (utan att läsa allt i minnet)."""
    month_dir = raw_dir / month
    if month_dir.exists() and any(month_dir.glob("*.csv")):
        print(f"{month}: finns redan i volymen")
        return
    url = f"https://s3.amazonaws.com/tripdata/{month}-citibike-tripdata.zip"
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / f"{month}.zip"
        with urllib.request.urlopen(url, timeout=300) as resp, open(zip_path, "wb") as out:
            shutil.copyfileobj(resp, out, length=1024 * 1024)
        month_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.endswith(".csv") and not name.startswith("__MACOSX"):
                    with zf.open(name) as src, open(month_dir / Path(name).name, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
    print(f"{month}: hämtad från {url}")


for month in months:
    try:
        download_month(month)
    except OSError as e:  # URLError ärver från OSError: blockerad utgående trafik eller 404
        print(f"{month}: kunde inte hämtas ({e}). Använder filer som redan ligger i volymen.")

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {target}.bronze_trips (
  ride_id STRING, rideable_type STRING, started_at STRING, ended_at STRING,
  start_station_name STRING, start_station_id STRING, end_station_name STRING, end_station_id STRING,
  start_lat STRING, start_lng STRING, end_lat STRING, end_lng STRING, member_casual STRING,
  _source_file STRING COMMENT 'Filen raden lästes från',
  _ingested_at TIMESTAMP COMMENT 'När raden lästes in'
)
COMMENT 'Rå Citi Bike-resor, oförändrade (alla värden som text). Typning sker i silver.'
""")

# Explicit kolumnlista: inget beroende av schemainferens, och snabbare än inferSchema.
spark.sql(f"""
COPY INTO {target}.bronze_trips
FROM (
  SELECT ride_id, rideable_type, started_at, ended_at,
         start_station_name, start_station_id, end_station_name, end_station_id,
         start_lat, start_lng, end_lat, end_lng, member_casual,
         _metadata.file_path AS _source_file, current_timestamp() AS _ingested_at
  FROM '{raw_dir}'
)
FILEFORMAT = CSV
PATTERN = '*/*.csv'
FORMAT_OPTIONS ('header' = 'true', 'inferSchema' = 'false')
""")

print("Rader i bronze_trips:", spark.table(f"{target}.bronze_trips").count())
