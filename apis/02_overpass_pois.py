"""
DESCUBRIMIENTO API #2 — Overpass (OpenStreetMap)
================================================
¿Qué es?   Consulta puntos de interés (POIs) cerca de una coordenada: colegios,
           paradas de bus / metro, supermercados, parques, hospitales, etc.
¿Cuesta?   GRATIS, sin API key. OJO: exige header User-Agent o devuelve 406.
           Tiene rate limit, conviene no spamearlo.
Lenguaje:  Overpass QL (un mini lenguaje de consulta). 'around:RADIO,LAT,LON'.
Docs:      https://wiki.openstreetmap.org/wiki/Overpass_API

Ejecutar:  python apis/02_overpass_pois.py
Salida:    consola + apis/outputs/overpass.json
"""
import json
from pathlib import Path

import httpx

# ---- Parámetros hardcodeados (coordenadas de Apoquindo 4000) ----
LAT, LON = -33.4122219, -70.5792485
RADIO_M = 1000  # buscar dentro de 1 km

URL = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "inmobiliaria-poc/0.1 (descubrimiento-apis)"}

# Query Overpass QL: buscar colegios, paradas de bus, metro y supermercados.
# 'out center tags' => devuelve coordenadas + etiquetas de cada elemento.
QUERY = f"""
[out:json][timeout:25];
(
  node["amenity"="school"](around:{RADIO_M},{LAT},{LON});
  node["highway"="bus_stop"](around:{RADIO_M},{LAT},{LON});
  node["railway"="subway_entrance"](around:{RADIO_M},{LAT},{LON});
  node["shop"="supermarket"](around:{RADIO_M},{LAT},{LON});
  node["leisure"="park"](around:{RADIO_M},{LAT},{LON});
);
out center tags;
"""

print(f"Consultando Overpass alrededor de ({LAT}, {LON}) en {RADIO_M} m...\n")
resp = httpx.post(URL, data={"data": QUERY}, headers=HEADERS, timeout=40)
resp.raise_for_status()
data = resp.json()

out_dir = Path(__file__).parent / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / "overpass.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
)

elements = data.get("elements", [])
print(f"== Overpass devolvió {len(elements)} elementos ==\n")

# Resumen simple: contar por tipo y mostrar algunos nombres
print("Primeros 10 elementos con nombre:")
mostrados = 0
for el in elements:
    tags = el.get("tags", {})
    nombre = tags.get("name")
    if not nombre:
        continue
    tipo = tags.get("amenity") or tags.get("highway") or tags.get("railway") \
        or tags.get("shop") or tags.get("leisure")
    print(f"  - {nombre}  ({tipo})")
    mostrados += 1
    if mostrados >= 10:
        break

print("\n== JSON COMPLETO guardado en apis/outputs/overpass.json ==")
