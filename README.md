# Cykelstaden – Malvin Portfolio Project

**Live demo:** https://cykelstaden-malvin.streamlit.app/

En end-to-end dataprojekt-demo: en ETL-pipeline i Databricks över öppen Citi Bike-data (New York, september 2024,
cirka 5 miljoner resor) och en webbapp där vem som helst kan ställa frågor på svenska om datat.
Frågan översätts av en LLM till SQL, valideras som skrivskyddad och körs mot Databricks.

> Första besöket kan ta en stund: appen somnar vid inaktivitet och Databricks SQL warehouse behöver väckas.

## Arkitektur

```
Citi Bike (öppen data) -> Volume -> bronze_trips -> silver_trips -> gold_* (4 tabeller)   [Databricks Job]
                                                                       |
Besökare -> Streamlit-app -> LLM (Databricks Model Serving) -> SQL-vakt -> SQL warehouse   [Streamlit Community Cloud]
```

- **Bronze:** rådata oförändrad plus metadata.
- **Silver:** typning, dubblettborttagning, filtrering av felaktiga resor och härledda kolumner.
- **Gold:** affärsklara aggregat (resor per dag, per timme, per station, per rutt).
- **Orkestrering:** Databricks Job via Asset Bundle (`databricks.yml`, `resources/`).
- **Frågelagret:** LLM genererar SQL, `app/sql_guard.py` tillåter bara ett SELECT mot de fyra gold-tabellerna
  och lägger på en radgräns. Appen har ratebegränsning per session och per dygn.
- **Säkerhet:** den publika appen använder en egen service principal med enbart SELECT på gold-tabellerna.

## Struktur
- `databricks.yml`, `resources/` – Asset Bundle (job och Databricks App)
- `src/pipeline/` – bronze, silver, gold (Databricks-notebooks i .py-format)
- `app/` – Streamlit-app, SQL-vakt, ratebegränsning och schemakontext för LLM:en
- `tests/` – tester för SQL-vakten och ratebegränsningen (`pip install pytest sqlglot && pytest`)

## Köra själv
```bash
databricks auth login --host https://<ditt-workspace>.cloud.databricks.com
databricks bundle deploy --var warehouse_id=<warehouse-id>
databricks bundle run cykelstaden_etl
```
Ladda upp Citi Bike-CSV-filer till Volume `workspace.cykelstaden.raw/<YYYYMM>/` om ditt workspace blockerar
utgående trafik till S3 (som Databricks Free Edition gör). Den publika appen kräver secrets enligt
`app/.streamlit/secrets.toml.example`.

## Kända begränsningar
- Bara september 2024 är laddad.
- Frågorna körs på en liten Databricks Free Edition-miljö med kvoter.
- LLM-genererad SQL kan bli fel eller för enkel; det genererade SQL-uttrycket visas under varje svar.

Datakälla: [Citi Bike System Data](https://citibikenyc.com/system-data).
