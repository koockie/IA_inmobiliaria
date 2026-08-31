"""API de analisis de inversion inmobiliaria.

    ./.venv/Scripts/python.exe -m uvicorn api.main:app --reload

Tres endpoints y una idea: el backend manda los atributos que extrajo del aviso
y recibe de vuelta el analisis completo. Todo lo que devuelve viene acompanado
de su incertidumbre; no hay ningun numero presentado como certeza.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import informe as INF
from . import inversion as INV
from . import modelos as M

RAIZ = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="Analisis de inversion inmobiliaria",
    version="1.0.0",
    description="Estima precio de venta y arriendo de una propiedad en Macul, "
                "La Florida, Nunoa o San Miguel, y evalua si conviene como "
                "inversion para mantenerla y venderla a futuro.",
)


# ---------------------------------------------------------------------------
# Esquemas
# ---------------------------------------------------------------------------
class Propiedad(BaseModel):
    """Atributos de la propiedad. Solo `m2_util` es obligatorio: lo que falte
    queda en NaN y baja el nivel de confianza declarado en la respuesta."""
    m2_util: float = Field(..., gt=0, description="Superficie util en m2")
    tipo: Literal["departamento", "casa"] = "departamento"
    comuna: str | None = Field(None, examples=["nunoa"])
    m2_total: float | None = None
    dormitorios: float | None = None
    banos: float | None = None
    estacionamientos: float | None = None
    bodegas: float | None = None
    ano_construccion: float | None = None
    gastos_comunes_clp: float | None = None
    lat: float | None = None
    lon: float | None = None
    servicios_cercanos: dict[str, Any] | str | None = Field(
        None, description="JSON de Google Places, tal como lo guarda el scraper")

    def a_atributos(self) -> dict:
        return self.model_dump()


class PeticionEstimacion(BaseModel):
    propiedad: Propiedad
    precio_pedido_uf: float | None = Field(
        None, gt=0, description="Si se envia, se juzga si esta caro o barato")


class PeticionAnalisis(BaseModel):
    propiedad: Propiedad
    precio_pedido_uf: float = Field(..., gt=0)
    # Todos los supuestos son opcionales: si no vienen se usan los declarados
    # en `inversion.Supuestos`, que estan documentados y son editables.
    supuestos: dict[str, float] | None = None
    n_simulaciones: int = Field(4000, ge=200, le=20000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/salud")
def salud() -> dict:
    """Comprobacion de vida: carga los dos modelos y responde con sus metricas."""
    v, a = M.cargar("venta"), M.cargar("arriendo")
    return {"estado": "ok",
            "modelos": {"venta": {"mdape_pct": v.mdape, "n_features": len(v.columnas)},
                        "arriendo": {"mdape_pct": a.mdape, "n_features": len(a.columnas)}},
            "uf_referencia": v.uf,
            "comunas_cubiertas": sorted(a.comunas) if a.comunas else []}


@app.get("/modelos/{nombre}")
def ficha(nombre: str) -> dict:
    """La ficha completa del modelo: metricas, variables y sesgos declarados."""
    ruta = RAIZ / "modelos" / f"{nombre}.json"
    if nombre not in ("venta", "arriendo") or not ruta.exists():
        raise HTTPException(404, "modelo no encontrado")
    return json.loads(ruta.read_text(encoding="utf-8"))


@app.post("/estimar")
def estimar(p: PeticionEstimacion) -> dict:
    """Precio de venta y arriendo esperados, con rango y nivel de confianza."""
    at = p.propiedad.a_atributos()
    est = M.estimar_ambos(at)
    salida: dict = {"venta": est["venta"].a_dict(),
                    "arriendo": est["arriendo"].a_dict()}
    salida["arriendo"]["valor_uf"] = round(
        est["arriendo"].valor / M.cargar("venta").uf, 2)
    if p.precio_pedido_uf is not None:
        salida["juicio_de_precio"] = M.veredicto_precio(p.precio_pedido_uf,
                                                        est["venta"])
    return salida


@app.post("/analizar")
def analizar(p: PeticionAnalisis) -> dict:
    """El informe completo: cuanto vale, cuanto renta y si conviene tenerla."""
    at = p.propiedad.a_atributos()
    est = M.estimar_ambos(at)
    mv, ma = M.cargar("venta"), M.cargar("arriendo")

    s = INV.Supuestos(**(p.supuestos or {}))
    analisis = INV.analizar(
        precio_pedido_uf=p.precio_pedido_uf,
        estimacion_venta_uf=est["venta"].valor,
        arriendo_estimado_clp=est["arriendo"].valor,
        uf=mv.uf,
        sigma_venta=mv.sigma_log,
        sigma_arriendo=ma.sigma_log,
        comuna=at.get("comuna"),
        s=s,
        n_simulaciones=p.n_simulaciones,
    )
    return {
        "tasacion": {"venta": est["venta"].a_dict(),
                     "arriendo": est["arriendo"].a_dict()},
        "juicio_de_precio": M.veredicto_precio(p.precio_pedido_uf, est["venta"]),
        "inversion": analisis,
        "advertencias": _advertencias(est),
    }


@app.post("/informe", response_class=HTMLResponse)
def informe(p: PeticionAnalisis) -> str:
    """El mismo analisis, renderizado como el informe que ve el usuario final."""
    return INF.render(analizar(p), p.propiedad.a_atributos(), documento=True)


def _advertencias(est: dict[str, M.Estimacion]) -> list[str]:
    """Lo que el informe tiene que decir aunque nadie lo pregunte."""
    avisos = [
        "Las estimaciones son de precio PEDIDO, no de cierre: en Chile el cierre "
        "suele quedar entre un 5 % y un 15 % por debajo.",
        "El modelo no estima plusvalía. El análisis entrega la plusvalía que "
        "haría falta para que la inversión funcione, no un pronóstico de que "
        "vaya a ocurrir.",
        "Cobertura geográfica limitada a Macul, La Florida, Ñuñoa y San Miguel.",
    ]
    for op, e in est.items():
        for m in e.motivos:
            avisos.append(f"[{op}] {m}")
    return avisos
