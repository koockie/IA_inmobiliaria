"""
DESCUBRIMIENTO API #7 — Google Maps Platform (Geocoding + Places New)
=====================================================================
¿Qué es?   Geocoding API (dirección -> lat/lon + comuna) y Places API New
           (searchNearby: lugares cercanos por tipo). Reemplaza a OSM.
¿Cuesta?   Requiere API key con BILLING activo. Tiene topes gratis mensuales por SKU.
           La key se lee desde .env (NO se hardcodea).
Docs:      https://developers.google.com/maps/documentation/places/web-service/nearby-search

Requisitos en Google Cloud:
  1. Crear proyecto y activar facturación.
  2. Habilitar "Geocoding API" y "Places API (New)".
  3. Crear API key y ponerla en .env como GOOGLE_MAPS_API_KEY.

Ejecutar:  python apis/07_google_places.py
Salida:    consola + apis/outputs/google_geocoding.json y google_places.json
"""
import json
import os
import urllib.parse
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not API_KEY:
    raise SystemExit("Falta GOOGLE_MAPS_API_KEY en .env.")

out_dir = Path(__file__).parent / "outputs"
out_dir.mkdir(exist_ok=True)

# ---- 1) GEOCODING v4: dirección -> coordenadas + comuna ----
# Endpoint NUEVO (la Demo Key lo soporta sin billing).
DIRECCION = "Av. Apoquindo 4000, Las Condes, Santiago, Chile"
print(f"[Geocoding v4] {DIRECCION}\n")
geo_resp = httpx.get(
    "https://geocode.googleapis.com/v4/geocode/address/" + urllib.parse.quote(DIRECCION),
    headers={
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": "results.location,results.formattedAddress,results.addressComponents",
    },
    timeout=20,
)
geo_resp.raise_for_status()
geo = geo_resp.json()
(out_dir / "google_geocoding.json").write_text(
    json.dumps(geo, ensure_ascii=False, indent=2), encoding="utf-8"
)

results = geo.get("results") or []
if results:
    res = results[0]
    loc = res["location"]
    lat, lon = loc["latitude"], loc["longitude"]
    print("  lat/lon:", lat, lon)
    for comp in res.get("addressComponents", []):
        if "administrative_area_level_3" in comp["types"]:
            print("  comuna:", comp["longText"])
        if "neighborhood" in comp["types"]:
            print("  barrio:", comp["longText"])
    print("  dirección formateada:", res.get("formattedAddress"))
else:
    print("  respuesta:", geo)
    raise SystemExit("Geocoding v4 falló; revisa la key.")

# ---- 2) PLACES (New) searchNearby: colegios cercanos ----
print("\n[Places searchNearby] colegios a 1 km...\n")
places_resp = httpx.post(
    "https://places.googleapis.com/v1/places:searchNearby",
    headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.location,places.primaryType",
    },
    json={
        "includedTypes": ["school", "primary_school", "secondary_school"],
        "maxResultCount": 10,
        "rankPreference": "DISTANCE",
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": 1000.0}
        },
        "languageCode": "es",
        "regionCode": "CL",
    },
    timeout=30,
)
places_resp.raise_for_status()
places = places_resp.json()
(out_dir / "google_places.json").write_text(
    json.dumps(places, ensure_ascii=False, indent=2), encoding="utf-8"
)

items = places.get("places", [])
print(f"  Google devolvió {len(items)} colegios (los más cercanos primero):")
for p in items[:5]:
    print("   -", (p.get("displayName") or {}).get("text"), f"({p.get('primaryType')})")

print("\n== JSONs guardados en apis/outputs/google_geocoding.json y google_places.json ==")
