"""
DESCUBRIMIENTO API #1 — Nominatim (OpenStreetMap)
=================================================
¿Qué es?   Geocoding: convierte una dirección de texto en coordenadas (lat/lon)
           y nos dice la comuna, región, etc.
¿Cuesta?   GRATIS, sin API key. Solo exige un header User-Agent identificable
           y respetar ~1 request por segundo.
Docs:      https://nominatim.org/release-docs/latest/api/Search/

Ejecutar:  python apis/01_nominatim_geocoding.py
Salida:    consola + apis/outputs/nominatim.json
"""
import json
from pathlib import Path

import httpx

# ---- Parámetros hardcodeados (cambia esto para experimentar) ----
DIRECCION = "Av. Apoquindo 4000, Las Condes, Santiago, Chile"

URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "inmobiliaria-poc/0.1 (descubrimiento-apis)"}
PARAMS = {
    "q": DIRECCION,
    "format": "jsonv2",
    "addressdetails": 1,   # para que devuelva comuna/región desglosadas
    "countrycodes": "cl",  # limitar a Chile
    "limit": 1,
}

print(f"Consultando Nominatim por: {DIRECCION}\n")
resp = httpx.get(URL, params=PARAMS, headers=HEADERS, timeout=20)
resp.raise_for_status()
data = resp.json()

# Guardar la salida cruda para mostrarla a los compañeros
out_dir = Path(__file__).parent / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / "nominatim.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
)

# Mostrar lo más relevante por consola
if data:
    item = data[0]
    addr = item.get("address", {})
    print("== LO QUE NOS INTERESA ==")
    print("lat:", item["lat"])
    print("lon:", item["lon"])
    print("comuna (suburb):", addr.get("suburb"))
    print("ciudad (city):", addr.get("city"))
    print("región (state):", addr.get("state"))
    print("display_name:", item["display_name"])
    print("\n== JSON COMPLETO guardado en apis/outputs/nominatim.json ==")
else:
    print("No se encontró la dirección.")
