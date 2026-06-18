"""Geocoding con Google Maps Platform — Geocoding API v4.

Usa el endpoint NUEVO (geocode.googleapis.com/v4), que la "Demo Key" de Google soporta
sin necesidad de billing. En Chile la comuna mapea a administrative_area_level_3 (o locality)
y la región a administrative_area_level_1. La v4 además entrega el barrio (neighborhood).
"""
from __future__ import annotations

import math
import urllib.parse
from functools import lru_cache
from typing import Optional

import httpx

from app.config import get_settings

GEOCODE_V4_URL = "https://geocode.googleapis.com/v4/geocode/address/"
FIELD_MASK = "results.location,results.formattedAddress,results.addressComponents"


def _component(components: list[dict], wanted_type: str) -> Optional[str]:
    """Devuelve el longText del primer addressComponent con el tipo pedido."""
    for comp in components:
        if wanted_type in comp.get("types", []):
            return comp.get("longText")
    return None


def parse_geocode_result(result: dict) -> dict:
    """Normaliza un resultado de la Geocoding API v4 al formato que usa el grafo."""
    location = result["location"]
    components = result.get("addressComponents", [])
    comuna = (
        _component(components, "administrative_area_level_3")
        or _component(components, "locality")
        or _component(components, "administrative_area_level_2")
    )
    region = _component(components, "administrative_area_level_1")
    barrio = _component(components, "neighborhood")
    return {
        "lat": location["latitude"],
        "lon": location["longitude"],
        "comuna": comuna,
        "region": region,
        "barrio": barrio,
        "display_name": result.get("formattedAddress"),
    }


@lru_cache(maxsize=256)
def geocode(direccion: str, comuna: Optional[str] = None) -> Optional[dict]:
    """Convierte una dirección en coordenadas y comuna. None si no se encuentra."""
    settings = get_settings()
    if not settings.google_maps_api_key:
        return None

    partes = [direccion]
    if comuna:
        partes.append(comuna)
    partes.append("Chile")
    query = ", ".join(partes)

    url = GEOCODE_V4_URL + urllib.parse.quote(query)
    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    try:
        resp = httpx.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    results = data.get("results") or []
    if not results:
        return None

    parsed = parse_geocode_result(results[0])
    # Si el usuario entregó comuna explícita, esa manda (más confiable para CEAD).
    if comuna:
        parsed["comuna"] = comuna
    return parsed


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos puntos (fórmula de haversine)."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
