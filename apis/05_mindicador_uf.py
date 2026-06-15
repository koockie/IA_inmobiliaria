"""
DESCUBRIMIENTO API #5 (BONUS cuantitativo) — mindicador.cl
==========================================================
¿Qué es?   Indicadores económicos de Chile en tiempo real: UF, UTM, dólar, euro,
           IPC, etc. En Chile las propiedades se transan en UF, así que esto sirve
           para normalizar precios y cálculos (cap rate, plusvalía).
¿Cuesta?   GRATIS, sin API key.
Docs:      https://mindicador.cl/

Ejecutar:  python apis/05_mindicador_uf.py
Salida:    consola + apis/outputs/mindicador.json
"""
import json
from pathlib import Path

import httpx

URL = "https://mindicador.cl/api"

print("Consultando indicadores económicos de Chile (mindicador.cl)...\n")
resp = httpx.get(URL, timeout=20)
resp.raise_for_status()
data = resp.json()

out_dir = Path(__file__).parent / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / "mindicador.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
)

print("== INDICADORES DE HOY ==")
for clave in ("uf", "utm", "dolar", "euro", "ipc"):
    ind = data.get(clave, {})
    print(f"  {ind.get('nombre', clave):<28} {ind.get('valor')}  ({ind.get('unidad_medida')})")

print("\n== JSON COMPLETO guardado en apis/outputs/mindicador.json ==")
