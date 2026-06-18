"""
 Tavily es como un navegador para buscar en la web para la IA.
le mandas una pregunta en texto y te devuelve resultados web ya "limpios" (título, contenido, url),
           listos para que un modelo los resuma.
Tier gratis ~1000 créditos/mes (sin tarjeta). Cada búsqueda gasta 1 crédito.
Docs:      https://docs.tavily.com/ (necesita api key actualmente a mi cta marcelofernandez)

probar:  python apis/03_tavily_search.py
Salida:    consola + apis/outputs/tavily.json
"""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()  # lee TAVILY_API_KEY desde el archivo .env

API_KEY = os.getenv("TAVILY_API_KEY")
if not API_KEY:
    raise SystemExit("Falta TAVILY_API_KEY en .env")

# ---- Parámetro hardcodeado: la pregunta que queremos investigar ----
QUERY = "nuevos proyectos inmobiliarios y permisos de edificación en Las Condes 2025"

URL = "https://api.tavily.com/search"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}
BODY = {
    "query": QUERY,
    "max_results": 3,
    "search_depth": "basic",
}

print(f"Buscando en Tavily: {QUERY}\n")
resp = httpx.post(URL, json=BODY, headers=HEADERS, timeout=30)
resp.raise_for_status()
data = resp.json()

out_dir = Path(__file__).parent / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / "tavily.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
)

print(f"== Tavily devolvió {len(data.get('results', []))} resultados ==\n")
for i, r in enumerate(data.get("results", []), 1):
    print(f"[{i}] {r.get('title')}")
    print(f"    url: {r.get('url')}")
    print(f"    {(r.get('content') or '')[:160]}...\n")

print("== JSON COMPLETO guardado en apis/outputs/tavily.json ==")
