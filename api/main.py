"""API de tasacion inmobiliaria.

    ./.venv/Scripts/python.exe -m uvicorn api.main:app --reload

Sirve los dos modelos entrenados y nada mas: recibe los atributos de una
propiedad y devuelve el precio de venta y el arriendo esperados, cada uno con
su rango y su nivel de confianza. Toda la logica de negocio -- financiamiento,
rentabilidad, informe -- vive fuera de este servicio.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import modelos as M

RAIZ = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="Tasacion inmobiliaria",
    version="2.0.0",
    description="Estima precio de venta (UF) y arriendo (CLP) de una propiedad "
                "en Macul, La Florida, Nunoa o San Miguel.",
)


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
    salida["advertencias"] = _advertencias(est)
    return salida


def _advertencias(est: dict[str, M.Estimacion]) -> list[str]:
    """Los limites del modelo, que el consumidor tiene que declarar aunque no
    los pregunte."""
    avisos = [
        "Las estimaciones son de precio PEDIDO, no de cierre: en Chile el cierre "
        "suele quedar entre un 5 % y un 15 % por debajo.",
        "Cobertura geografica limitada a Macul, La Florida, Nunoa y San Miguel.",
    ]
    for op, e in est.items():
        for m in e.motivos:
            avisos.append(f"[{op}] {m}")
    return avisos
