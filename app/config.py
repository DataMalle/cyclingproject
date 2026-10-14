"""Konfiguration från miljövariabler (Streamlit-secrets läggs i miljön av app.py)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Obligatorisk konfiguration saknas."""


@dataclass(frozen=True)
class Settings:
    warehouse_id: str
    llm_endpoint: str
    catalog: str = "workspace"
    schema: str = "cykelstaden"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    missing = [k for k in ("DATABRICKS_WAREHOUSE_ID", "LLM_ENDPOINT") if not env.get(k)]
    if missing:
        raise ConfigError(", ".join(missing))
    return Settings(
        warehouse_id=env["DATABRICKS_WAREHOUSE_ID"],
        llm_endpoint=env["LLM_ENDPOINT"],
        catalog=env.get("CATALOG", "workspace"),
        schema=env.get("SCHEMA", "cykelstaden"),
    )
