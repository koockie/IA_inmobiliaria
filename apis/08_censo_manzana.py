"""
Censo 2024 INE a nivel MANZANA (ArcGIS FeatureServer)
Este script: dada una coordenada, consulta la capa y muestra los atributos de esa manzana.
NO ESTA FUNCIONANDOOO

Ejecutar:  python apis/08_censo_manzana.py
Salida:    consola + apis/outputs/censo_manzana.json
"""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# Coordenada de prueba 
LAT, LON = -33.4122219, -70.5792485

# Confirmar y pegar la URL real de la capa (o setear INE_ARCGIS_LAYER_URL en .env)
LAYER_URL = os.getenv("INE_ARCGIS_LAYER_URL", "")

out_dir = Path(__file__).parent / "outputs"
out_dir.mkdir(exist_ok=True)

if not LAYER_URL:
    print("""
No hay URL de capa configurada todavía.

PASOS PARA CONFIRMARLA:
  1. Entra a https://geoine-ine-chile.opendata.arcgis.com
  2. Busca "Manzana Entidad Censo 2024" (o similar).
  3. Abre el dataset -> sección "View API Resources" / "I want to use this".
  4. Copia la URL del GeoService / FeatureServer (termina en /FeatureServer).
  5. Pégala en .env como INE_ARCGIS_LAYER_URL=...   (agrega /0 si apunta al server)

Mientras tanto, este script no puede consultar nada.
""")
    raise SystemExit(0)

# ArcGIS REST: query por punto con intersección, salida GeoJSON.
query_url = LAYER_URL.rstrip("/") + "/query"
params = {
    "f": "geojson",
    "geometry": f"{LON},{LAT}",
    "geometryType": "esriGeometryPoint",
    "inSR": "4326",
    "spatialRel": "esriSpatialRelIntersects",
    "outFields": "*",
    "returnGeometry": "false",
}

print(f"Consultando manzana del Censo 2024 en ({LAT}, {LON})...\n")
resp = httpx.get(query_url, params=params, timeout=25)
resp.raise_for_status()
data = resp.json()
(out_dir / "censo_manzana.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
)

features = data.get("features", [])
if not features:
    print("El punto no cayó en ninguna manzana (o la capa/URL no es la correcta).")
else:
    props = features[0].get("properties", {})
    print(f"Manzana encontrada con {len(props)} atributos. Primeros 15:")
    for i, (k, v) in enumerate(props.items()):
        if i >= 15:
            break
        print(f"   {k}: {v}")
    print("\n== JSON completo en apis/outputs/censo_manzana.json ==")
