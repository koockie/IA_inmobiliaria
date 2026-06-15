"""Puntos de interés cercanos vía Overpass API (OpenStreetMap) — gratis, sin key.

Una sola consulta combinada alrededor del punto; luego clasificamos cada elemento por
sus tags en categorías de interés para inversión (colegios, locomoción, abastecimiento,
áreas verdes, salud). Devolvemos conteo por categoría y distancia al más cercano.
"""
from __future__ import annotations

from typing import Optional

import httpx

from app.config import get_settings
from app.tools.geocoding import haversine_m

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Cada categoría: lista de (key, value) que la identifican en OSM.
CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "colegios": [
        ("amenity", "school"),
        ("amenity", "kindergarten"),
        ("amenity", "college"),
        ("amenity", "university"),
    ],
    "locomocion": [
        ("highway", "bus_stop"),
        ("amenity", "bus_station"),
        ("railway", "station"),
        ("railway", "subway_entrance"),
    ],
    "abastecimiento": [
        ("shop", "supermarket"),
        ("amenity", "marketplace"),
    ],
    "areas_verdes": [
        ("leisure", "park"),
        ("landuse", "recreation_ground"),
    ],
    "salud": [
        ("amenity", "hospital"),
        ("amenity", "clinic"),
        ("amenity", "pharmacy"),
    ],
}


def _build_query(lat: float, lon: float, radius_m: int) -> str:
    """Arma una query Overpass con todas las categorías en una sola petición."""
    parts: list[str] = []
    for pairs in CATEGORIES.values():
        for key, value in pairs:
            for kind in ("node", "way"):
                parts.append(f'{kind}["{key}"="{value}"](around:{radius_m},{lat},{lon});')
    body = "".join(parts)
    return f"[out:json][timeout:25];({body});out center tags;"


def _classify(tags: dict) -> Optional[str]:
    """Devuelve la categoría a la que pertenece un elemento según sus tags."""
    for category, pairs in CATEGORIES.items():
        for key, value in pairs:
            if tags.get(key) == value:
                return category
    return None


def fetch_pois(lat: float, lon: float, radius_m: int = 1000) -> dict:
    """Conteo y distancia mínima por categoría dentro del radio indicado."""
    query = _build_query(lat, lon, radius_m)
    headers = {"User-Agent": get_settings().nominatim_user_agent}
    try:
        resp = httpx.post(OVERPASS_URL, data={"data": query}, headers=headers, timeout=40)
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": f"Overpass no disponible: {exc}", "radio_m": radius_m}

    result: dict[str, dict] = {
        cat: {"conteo": 0, "mas_cercano_m": None, "ejemplos": []} for cat in CATEGORIES
    }

    for el in elements:
        tags = el.get("tags", {})
        category = _classify(tags)
        if not category:
            continue
        # nodos traen lat/lon; ways traen 'center'
        el_lat = el.get("lat") or (el.get("center") or {}).get("lat")
        el_lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if el_lat is None or el_lon is None:
            continue
        dist = round(haversine_m(lat, lon, el_lat, el_lon))

        bucket = result[category]
        bucket["conteo"] += 1
        if bucket["mas_cercano_m"] is None or dist < bucket["mas_cercano_m"]:
            bucket["mas_cercano_m"] = dist
        name = tags.get("name")
        if name and len(bucket["ejemplos"]) < 3:
            bucket["ejemplos"].append({"nombre": name, "distancia_m": dist})

    return {"radio_m": radius_m, "categorias": result}
