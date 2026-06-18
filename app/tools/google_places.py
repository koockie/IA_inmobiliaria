"""Puntos de interés cercanos vía Google Places API (New) — searchNearby.

Reemplaza a Overpass. Se hace una consulta por categoría (rankPreference=DISTANCE),
que devuelve hasta 20 lugares ordenados del más cercano al más lejano dentro del radio.
Se conserva el MISMO formato de salida que la versión Overpass para no tocar el synthesizer:
{radio_m, categorias: {cat: {conteo, mas_cercano_m, ejemplos:[{nombre, distancia_m}]}}}.

Nota: el conteo está topado en 20 por categoría (límite de la API por request).
Requiere `GOOGLE_MAPS_API_KEY` con billing activo.
"""
from __future__ import annotations

import httpx

from app.config import get_settings
from app.tools.google_geocoding import haversine_m

SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

# Categoría interna -> tipos de lugar de Google (includedTypes).
# OJO: "university" va en su propia categoría para que los edificios universitarios NO
# aparezcan listados como colegios.
CATEGORIES: dict[str, list[str]] = {
    "colegios": ["primary_school", "secondary_school", "school", "preschool"],
    "universidades": ["university"],
    "locomocion": ["bus_stop", "bus_station", "transit_station", "subway_station",
                   "train_station", "light_rail_station"],
    "abastecimiento": ["supermarket", "grocery_store"],
    "areas_verdes": ["park"],
    "salud": ["hospital", "pharmacy", "doctor"],
}

# Campos que pedimos (obligatorio el FieldMask en Places API New).
FIELD_MASK = "places.displayName,places.location,places.primaryType"


def _search_category(lat: float, lon: float, radius_m: int, types: list[str], headers: dict) -> list[dict]:
    body = {
        "includedTypes": types,
        "maxResultCount": 20,
        "rankPreference": "DISTANCE",
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": float(radius_m)}
        },
        "languageCode": "es",
        "regionCode": "CL",
    }
    resp = httpx.post(SEARCH_NEARBY_URL, json=body, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get("places", [])


def fetch_pois(lat: float, lon: float, radius_m: int = 1000) -> dict:
    """Conteo y distancia mínima por categoría dentro del radio indicado."""
    settings = get_settings()
    if not settings.google_maps_api_key:
        return {"error": "Falta GOOGLE_MAPS_API_KEY.", "radio_m": radius_m}

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    result: dict[str, dict] = {}
    for category, types in CATEGORIES.items():
        bucket = {"conteo": 0, "mas_cercano_m": None, "ejemplos": []}
        try:
            places = _search_category(lat, lon, radius_m, types, headers)
        except (httpx.HTTPError, ValueError) as exc:
            bucket["error"] = f"Google Places no disponible: {exc}"
            result[category] = bucket
            continue

        for place in places:
            loc = place.get("location", {})
            p_lat, p_lon = loc.get("latitude"), loc.get("longitude")
            if p_lat is None or p_lon is None:
                continue
            dist = round(haversine_m(lat, lon, p_lat, p_lon))
            bucket["conteo"] += 1
            if bucket["mas_cercano_m"] is None or dist < bucket["mas_cercano_m"]:
                bucket["mas_cercano_m"] = dist
            nombre = (place.get("displayName") or {}).get("text")
            if nombre and len(bucket["ejemplos"]) < 5:
                bucket["ejemplos"].append({
                    "nombre": nombre,
                    "distancia_m": dist,
                    "tipo": place.get("primaryType"),
                })
        result[category] = bucket

    return {
        "radio_m": radius_m,
        "categorias": result,
        "nota_conteo": "El conteo está topado en 20 por categoría (límite por consulta).",
        "fuente": {"nombre": "Google Places API (New)", "url": "https://maps.google.com"},
    }
