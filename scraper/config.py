"""Configuración del scraper de ofertas inmobiliarias.

Uso académico/POC. robots.txt de ambos sitios revisado (2026-06): las rutas usadas están
permitidas. Rate-limit conservador para no molestar a los sitios.
"""
from __future__ import annotations

from pathlib import Path

# Comunas objetivo (slug interno -> slug en la URL de PortalInmobiliario)
COMUNAS_PI: dict[str, str] = {
    "macul": "macul-metropolitana",
    "la-florida": "la-florida-metropolitana",
    "nunoa": "nunoa-metropolitana",
    "san-miguel": "san-miguel-metropolitana",
}

OPERACIONES = ["venta", "arriendo"]
TIPOS = ["casa", "departamento"]

# Cortesía
RATE_MIN_S = 1.5
RATE_MAX_S = 2.5
TIMEOUT_S = 30
MAX_RETRIES = 3

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Salidas
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "ofertas.sqlite"
CSV_PATH = DATA_DIR / "dataset_ofertas.csv"

# PortalInmobiliario
PI_BASE = "https://www.portalinmobiliario.com"
PI_PAGE_SIZE = 48  # avisos orgánicos por página (paginación _Desde_N)
