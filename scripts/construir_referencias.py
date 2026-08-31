"""Distribucion de yield por comuna, para medir valor relativo.

Cruza los dos modelos sobre el mismo conjunto de propiedades en venta: estima
precio y arriendo de cada una y calcula el yield bruto implicito. El resultado
se guarda en `modelos/referencias_yield.json` y lo consume
`api/inversion.valor_relativo()`.

Que es y que no es este numero:

- **Es** un yield *implicito por modelo*: lo que rentaria cada propiedad segun
  el modelo de arriendo, dividido por lo que valdria segun el de venta. Sirve
  para comparar propiedades entre si dentro de la misma comuna, que es
  exactamente el uso que se le da.
- **No es** un yield observado. Nadie publica la misma unidad en venta y en
  arriendo, asi que no hay forma de validarlo contra transacciones reales. Se
  usa como medida relativa, nunca como promesa de rentabilidad.

    ./.venv/Scripts/python.exe scripts/construir_referencias.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from api import modelos as M                                   # noqa: E402
from api.features import NUMERICAS, construir_features         # noqa: E402

SALIDA = RAIZ / "modelos" / "referencias_yield.json"
PERCENTILES = [10, 20, 30, 40, 50, 60, 70, 80, 90]


def main() -> int:
    db = RAIZ / "data" / "ofertas_unificado.sqlite"
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=15) as con:
        crudo = pd.read_sql_query(
            "SELECT * FROM ofertas WHERE operacion='venta'", con)

    df = crudo.replace("SIN_DATO", pd.NA)
    for c in NUMERICAS:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Mismo filtro de rango que uso el modelo de venta: fuera de el las
    # estimaciones son extrapolacion y contaminarian los percentiles.
    df = df[df["precio_uf"].between(500, 60_000)
            & df["m2_util"].between(20, 800)].copy()

    venta, arriendo = M.cargar("venta"), M.cargar("arriendo")
    datos = construir_features(df, anio=venta.anio)

    p_venta = venta.p["modelo"].predict(datos[venta.columnas])
    p_arriendo = arriendo.p["modelo"].predict(datos[arriendo.columnas])
    yld = 100 * (p_arriendo * 12) / (p_venta * venta.uf)

    d = pd.DataFrame({"comuna": df["comuna"].to_numpy(), "yield": yld})
    d = d[np.isfinite(d["yield"]) & d["yield"].between(0.5, 15)]

    salida = {"nota": "yield bruto implicito por los dos modelos, no observado",
              "uf_referencia": venta.uf, "n_total": int(len(d)), "comunas": {}}
    for comuna, g in d.groupby("comuna"):
        if len(g) < 50:
            continue
        salida["comunas"][str(comuna)] = {
            "n": int(len(g)),
            "mediana_yield": float(g["yield"].median()),
            "percentiles_yield": [float(np.percentile(g["yield"], p))
                                  for p in PERCENTILES],
        }
    salida["percentiles"] = PERCENTILES
    SALIDA.write_text(json.dumps(salida, indent=2, ensure_ascii=False),
                      encoding="utf-8")

    print(f"{len(d):,} propiedades cruzadas -> {SALIDA}")
    print(f"{'comuna':<14}{'n':>7}{'p10':>8}{'mediana':>10}{'p90':>8}")
    print("-" * 47)
    for c, v in sorted(salida["comunas"].items()):
        print(f"{c:<14}{v['n']:>7,}{v['percentiles_yield'][0]:>8.2f}"
              f"{v['mediana_yield']:>10.2f}{v['percentiles_yield'][-1]:>8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
