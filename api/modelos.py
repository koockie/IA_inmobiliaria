"""Carga de los modelos entrenados y estimacion con intervalo coherente.

Envuelve los paquetes `modelos/venta.joblib` y `modelos/arriendo.joblib` en una
sola interfaz y corrige dos cosas que la auditoria QA encontro en los artefactos
tal como salen de los notebooks:

1. **Intervalo incoherente.** Los modelos cuantilicos se entrenan por separado
   del modelo puntual, asi que en un 1,4 % (arriendo) y un 2,4 % (venta) de los
   casos la estimacion puntual cae FUERA de su propio rango. Mostrar
   "estimamos 4.100 UF, rango 4.200-4.900" destruye la credibilidad del informe.
   Aqui el rango se ensancha hasta contener siempre el punto: solo puede
   aumentar la cobertura, nunca reducirla.

2. **Comuna sin normalizar.** El modelo vio slugs (`nunoa`, `la-florida`). Si el
   backend pasa "Ñuñoa", el OneHotEncoder lo trata como categoria desconocida y
   la estimacion pierde el bloque de ubicacion sin avisar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np

from .features import normalizar_comuna, preparar_entrada

RAIZ = Path(__file__).resolve().parent.parent
DIR_MODELOS = RAIZ / "modelos"


@dataclass
class Estimacion:
    valor: float
    rango: tuple[float, float]
    unidad: str
    confianza: str
    motivos: list[str] = field(default_factory=list)
    error_tipico_pct: float = 0.0
    cobertura_rango_pct: float = 80.0

    def a_dict(self) -> dict:
        return {"valor": round(self.valor, 2), "unidad": self.unidad,
                "rango": [round(self.rango[0], 2), round(self.rango[1], 2)],
                "confianza": self.confianza,
                "motivos_menor_confianza": self.motivos,
                "error_tipico_pct": round(self.error_tipico_pct, 1),
                "cobertura_rango_pct": self.cobertura_rango_pct}


class ModeloTasacion:
    """Un paquete .joblib listo para estimar."""

    def __init__(self, ruta: Path, unidad: str):
        self.p = joblib.load(ruta)
        self.unidad = unidad
        self.columnas = list(self.p["columnas"])
        self.mdape = float(self.p["mdape"])
        self.uf = float(self.p["uf_referencia"])
        self.anio = int(self.p["anio_referencia"])
        self.mdape_casa = float(self.p.get("mdape_casa", self.mdape))
        self.mdape_sin_geo = float(self.p.get("mdape_sin_geo", self.mdape))
        self.celdas = self.p.get("celdas_train") or set()
        self.comunas = self.p.get("comunas_train") or set()

    # -- sigma del error, para propagarlo en la simulacion ------------------
    @property
    def sigma_log(self) -> float:
        """Desviacion del error multiplicativo implicada por el MdAPE.

        Si el error relativo es lognormal, `exp(e)` con `e ~ N(0, s)`, entonces
        la mediana de |e| es 0,6745*s. Invertir esa relacion da la escala del
        ruido con la que hay que simular, en vez de inventar una.
        """
        return (self.mdape / 100.0) / 0.6745

    def estimar(self, atributos: dict) -> Estimacion:
        at = dict(atributos)
        at["comuna"] = normalizar_comuna(at.get("comuna"))
        entrada = preparar_entrada(at, self.columnas, anio=self.anio)

        punto = float(self.p["modelo"].predict(entrada)[0])
        c = float(self.p["correccion_conforme"])
        lo = float(self.p["cuantil_bajo"].predict(entrada)[0]) - c
        hi = float(self.p["cuantil_alto"].predict(entrada)[0]) + c
        # Coherencia: el rango tiene que contener siempre a su propio punto.
        lo, hi = max(0.0, min(lo, punto)), max(hi, punto)

        motivos, error = [], self.mdape
        es_casa = str(at.get("tipo", "")).strip().lower() == "casa"
        lat, lon = at.get("lat"), at.get("lon")
        tiene_geo = lat is not None and lon is not None and np.isfinite(
            float(lat) if lat is not None else np.nan)

        if es_casa:
            motivos.append("es una casa: el modelo se entrenó con muy pocas")
            error = max(error, self.mdape_casa)
        if not tiene_geo:
            motivos.append("sin coordenadas: se estima sin ubicación fina ni servicios cercanos")
            error = max(error, self.mdape_sin_geo)
        elif self.celdas:
            celda = f"{round(float(lat), 3)},{round(float(lon), 3)}"
            if celda not in self.celdas:
                motivos.append("barrio inédito: sin avisos de entrenamiento a menos de ~110 m")
        if self.comunas and at.get("comuna") not in self.comunas:
            motivos.append("comuna fuera de las cuatro cubiertas por el modelo")

        if es_casa or len(motivos) >= 2:
            confianza = "baja"
        elif motivos:
            confianza = "media"
        else:
            confianza = "alta"

        return Estimacion(valor=punto, rango=(lo, hi), unidad=self.unidad,
                          confianza=confianza, motivos=motivos,
                          error_tipico_pct=error)


_cache: dict[str, ModeloTasacion] = {}


def cargar(nombre: str) -> ModeloTasacion:
    """`cargar("venta")` / `cargar("arriendo")`, cacheado por proceso."""
    if nombre not in _cache:
        unidad = "UF" if nombre == "venta" else "CLP"
        _cache[nombre] = ModeloTasacion(DIR_MODELOS / f"{nombre}.joblib", unidad)
    return _cache[nombre]


def estimar_ambos(atributos: dict) -> dict[str, Estimacion]:
    """Las dos estimaciones para la misma propiedad."""
    return {"venta": cargar("venta").estimar(atributos),
            "arriendo": cargar("arriendo").estimar(atributos)}


def veredicto_precio(pedido_uf: float, estimacion: Estimacion) -> dict:
    """Compara el precio pedido con el estimado, en unidades de error del modelo.

    Los cortes no son numeros redondos: si el modelo se equivoca un 8,8 % de
    forma tipica, una brecha del 5 % no significa nada. Solo a partir de un
    error tipico la diferencia empieza a ser senal.
    """
    brecha = 100 * (pedido_uf - estimacion.valor) / estimacion.valor
    z = brecha / max(estimacion.error_tipico_pct, 1e-9)
    if z <= -2.0:
        etiqueta, detalle = "MUY BARATO", "muy por debajo de lo esperado"
    elif z <= -1.0:
        etiqueta, detalle = "BARATO", "bajo el precio de mercado"
    elif z < 1.0:
        etiqueta, detalle = "EN PRECIO", "dentro del rango de mercado"
    elif z < 2.0:
        etiqueta, detalle = "CARO", "sobre el precio de mercado"
    else:
        etiqueta, detalle = "MUY CARO", "muy por encima de lo esperado"
    return {"precio_pedido_uf": round(pedido_uf, 1),
            "brecha_pct": round(brecha, 1),
            "errores_tipicos": round(z, 2),
            "veredicto": etiqueta, "detalle": detalle,
            "dentro_del_rango": bool(estimacion.rango[0] <= pedido_uf
                                     <= estimacion.rango[1])}
