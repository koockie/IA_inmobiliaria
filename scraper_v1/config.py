"""Configuración del scraper v1 (excluye proyectos).

Hereda comunas y parámetros de red de `scraper.config` para no duplicar criterios,
pero escribe en archivos NUEVOS para no pisar el dataset anterior.
"""
from __future__ import annotations

from scraper.config import (  # noqa: F401  (re-export intencional)
    COMUNAS_PI, MAX_RETRIES, OPERACIONES, PI_BASE, PI_PAGE_SIZE, RATE_MAX_S,
    RATE_MIN_S, TIMEOUT_S, TIPOS, USER_AGENT,
)
from scraper.config import DATA_DIR

# Salidas propias del v1
DB_PATH = DATA_DIR / "ofertas_v1.sqlite"
CSV_PATH = DATA_DIR / "dataset_ofertas_v1.csv"
EXCLUIDOS_CSV = DATA_DIR / "proyectos_excluidos_v1.csv"

# Una ficha real pesa ~470 KB; si llega mucho menos, el portal está bloqueando.
TAM_MINIMO_FICHA = 100_000
