"""Geocoding con Nominatim (OpenStreetMap) — gratis, sin API key.

Política de uso: https://operations.osmfoundation.org/policies/nominatim/
- User-Agent identificable obligatorio.
- Máximo ~1 request/segundo.
- Cachear resultados para no repetir llamadas (importante en pruebas).
"""
from __future__ import annotations

import math
import time
from functools import lru_cache
from typing import Optional

import httpx

from app.config import get_settings

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_last_call_ts = 0.0


def _respect_rate_limit() -> None:
    """Garantiza ~1 req/s hacia Nominatim."""
    global _last_call_ts
    elapsed = time.monotonic() - _last_call_ts
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
    _last_call_ts = time.monotonic()


@lru_cache(maxsize=256)
def geocode(direccion: str, comuna: Optional[str] = None) -> Optional[dict]:
    """Convierte una dirección en coordenadas y comuna. None si no se encuentra."""
    settings = get_settings()
    query = direccion if not comuna else f"{direccion}, {comuna}"
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "countrycodes": "cl",
        "limit": 1,
    }
    headers = {"User-Agent": settings.nominatim_user_agent}

    _respect_rate_limit()
    try:
        resp = httpx.get(NOMINATIM_URL, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    if not data:
        return None

    item = data[0]
    address = item.get("address", {})
    # En Chile la comuna (admin_level 8) suele mapear a suburb/city_district/municipality.
    # `city` trae la ciudad mayor (p. ej. "Santiago"), por eso va más abajo en la prioridad.
    # Si el usuario entregó la comuna explícitamente, esa manda (más confiable para CEAD).
    comuna_detectada = (
        comuna
        or address.get("municipality")
        or address.get("city_district")
        or address.get("suburb")
        or address.get("town")
        or address.get("city")
        or address.get("county")
    )
    return {
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
        "comuna": comuna_detectada,
        "region": address.get("state"),
        "display_name": item.get("display_name"),
    }


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos puntos (fórmula de haversine)."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
