# Cykelstaden

ETL-pipeline i Databricks (Citi Bike NYC) plus en Databricks App där användaren ställer frågor på svenska.
Frågan översätts av en LLM till SQL, valideras som skrivskyddad och körs mot gold-tabellerna.

```
S3 (öppen data) -> Volume -> bronze_trips -> silver_trips -> gold_* -> Databricks App (LLM -> SQL)
```

## Struktur
- `databricks.yml`, `resources/` – Asset Bundle (job + app)
- `src/pipeline/` – bronze, silver, gold (Databricks-notebooks i .py-format)
- `app/` – Streamlit-app, SQL-vakt (`sql_guard.py`) och schemakontext för LLM:en
- `tests/` – tester för SQL-vakten (`pip install pytest sqlglot && pytest`)

## Deploy
```bash
databricks auth login --host https://<ditt-workspace>.cloud.databricks.com
databricks bundle validate -var warehouse_id=<id>
databricks bundle deploy -var warehouse_id=<id>
databricks bundle run cykelstaden_etl
databricks bundle run cykelstaden_app
```
Appens URL visas under Compute > Apps i workspacet.

## Att verifiera mot Free Edition
- Att serverless når `s3.amazonaws.com` (annars: ladda upp CSV till Volume `raw` manuellt).
- Att endpointen i `llm_endpoint` finns under Serving; byt namn vid behov.
- Vem som kan öppna appens URL (kräver normalt inloggning i workspacet).
