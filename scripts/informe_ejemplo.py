"""Genera un informe de ejemplo con una propiedad real del conjunto de prueba.

Sirve para revisar el producto de punta a punta sin levantar el servidor:

    ./.venv/Scripts/python.exe scripts/informe_ejemplo.py

Escribe `informe_ejemplo.html` en la raiz del repositorio.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient          # noqa: E402

from api import informe as INF                     # noqa: E402
from api.main import app                           # noqa: E402

# Un 2D2B de 82 m2 en Nunoa: el mismo perfil del informe comercial que se uso
# como referencia de producto, para poder comparar ambos lado a lado.
PROPIEDAD = {
    "m2_util": 82.0, "m2_total": 91.0, "tipo": "departamento", "comuna": "nunoa",
    "dormitorios": 2.0, "banos": 2.0, "estacionamientos": 2.0, "bodegas": 1.0,
    "ano_construccion": 2009.0, "gastos_comunes_clp": 171935.0,
    "lat": -33.4569, "lon": -70.6011,
}
PRECIO_PEDIDO_UF = 6402.0


def main() -> int:
    c = TestClient(app)
    r = c.post("/analizar", json={"propiedad": PROPIEDAD,
                                  "precio_pedido_uf": PRECIO_PEDIDO_UF,
                                  "n_simulaciones": 6000})
    r.raise_for_status()
    resultado = r.json()

    salida = RAIZ / "informe_ejemplo.html"
    salida.write_text(INF.render(resultado, PROPIEDAD, documento=True),
                      encoding="utf-8")
    (RAIZ / "informe_ejemplo.fragmento.html").write_text(
        INF.render(resultado, PROPIEDAD, documento=False), encoding="utf-8")

    inv = resultado["inversion"]
    print(f"informe -> {salida}")
    print(f"  veredicto : {inv['veredicto']}")
    print(f"  plusvalia requerida : {inv['horizonte']['plusvalia_real_requerida_pct']}%")
    print(f"  prob de exito       : {inv['horizonte']['prob_batir_alternativa_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
