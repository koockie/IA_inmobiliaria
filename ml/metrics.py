"""Metricas de tasacion masiva (AVM), en escala original.

Todas las funciones esperan precios en UF o CLP, NUNCA logaritmos. En tasacion
se usa la mediana y no la media porque unos pocos outliers distorsionan el
promedio; por eso la metrica principal es MdAPE y no MAPE.

Referencia de rangos: IAAO, Standard on Ratio Studies.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml import config


def _arrays(y_real, y_pred) -> tuple[np.ndarray, np.ndarray]:
    """Valida y alinea. Descarta pares no finitos o con real <= 0."""
    y = np.asarray(y_real, dtype=float).ravel()
    p = np.asarray(y_pred, dtype=float).ravel()
    if y.shape != p.shape:
        raise ValueError(f"formas distintas: {y.shape} vs {p.shape}")
    ok = np.isfinite(y) & np.isfinite(p) & (y > 0)
    if not ok.any():
        raise ValueError("no queda ningun par valido (real > 0 y finito)")
    return y[ok], p[ok]


def validar_escala(y_real, operacion: str) -> None:
    """Aborta si los valores parecen estar en escala logaritmica.

    Es la barrera contra el error mas costoso del proyecto: un R2 de 0,9 medido
    sobre log(precio) puede corresponder a un error enorme en pesos. Una venta
    mediana son ~3.450 UF y un arriendo ~470.000 CLP; sus logaritmos son ~8,1 y
    ~13,1. Si la mediana cae en ese rango, alguien olvido exponenciar.
    """
    y = np.asarray(y_real, dtype=float).ravel()
    y = y[np.isfinite(y)]
    if y.size == 0:
        return
    minimo = 100.0 if operacion == "venta" else 50_000.0
    if float(np.median(y)) < minimo:
        raise ValueError(
            f"la mediana de y es {np.median(y):.4g}, demasiado baja para {operacion}: "
            "parece escala logaritmica. Las metricas deben calcularse en UF/CLP."
        )


# --------------------------------------------------------------------------
# Error porcentual
# --------------------------------------------------------------------------
def ape(y_real, y_pred) -> np.ndarray:
    """Error porcentual absoluto, elemento a elemento."""
    y, p = _arrays(y_real, y_pred)
    return 100.0 * np.abs(p - y) / y


def mdape(y_real, y_pred) -> float:
    """Error porcentual absoluto MEDIANO. Metrica principal. Meta < 15%."""
    return float(np.median(ape(y_real, y_pred)))


def mape(y_real, y_pred) -> float:
    """Media de los errores porcentuales. La distorsionan los outliers."""
    return float(np.mean(ape(y_real, y_pred)))


def ppe(y_real, y_pred, tolerancia: float = 10.0) -> float:
    """Porcentaje de predicciones dentro de +/- tolerancia. PPE10 es la meta > 50%."""
    e = ape(y_real, y_pred)
    # Borde inclusivo: un error de exactamente 10,0% cuenta como acierto.
    return float(100.0 * np.mean(e <= tolerancia + 1e-9))


# --------------------------------------------------------------------------
# Uniformidad y equidad vertical (IAAO)
# --------------------------------------------------------------------------
def ratios(y_real, y_pred) -> np.ndarray:
    """Ratio estimado/real. En nomenclatura IAAO, tasado sobre venta."""
    y, p = _arrays(y_real, y_pred)
    return p / y


def mediana_ratio(y_real, y_pred) -> float:
    """Nivel de tasacion. Deberia estar cerca de 1,00."""
    return float(np.median(ratios(y_real, y_pred)))


def cod(y_real, y_pred) -> float:
    """Coeficiente de dispersion: uniformidad horizontal.

    Desviacion absoluta media respecto de la mediana de los ratios, en
    porcentaje. IAAO: 5-15 aceptable, 5-10 en vivienda homogenea.
    """
    r = ratios(y_real, y_pred)
    med = float(np.median(r))
    return float(100.0 * np.mean(np.abs(r - med)) / med)


def prd(y_real, y_pred) -> float:
    """Price-Related Differential: equidad vertical.

    media(ratio) dividido por el ratio ponderado. Por encima de 1,03 indica
    regresividad: el modelo sobrevalora las baratas y subvalora las caras.
    IAAO: 0,98 a 1,03.
    """
    y, p = _arrays(y_real, y_pred)
    return float(np.mean(p / y) / (p.sum() / y.sum()))


@dataclass(frozen=True)
class ResultadoPRB:
    coef: float
    error_estandar: float
    t: float
    ic95: tuple[float, float]

    def __float__(self) -> float:
        return self.coef


def prb(y_real, y_pred) -> ResultadoPRB:
    """Price-Related Bias: sesgo vertical, mas robusto que PRD.

    Mide el cambio porcentual del ratio ante una duplicacion del valor. No
    depende de una particion en estratos ni se distorsiona con colas pesadas,
    que son las dos debilidades del PRD.

    IAAO: aceptable -0,05 a +0,05; inaceptable fuera de -0,10 a +0,10.
    Se devuelve con intervalo de confianza porque un PRB de -0,04 con IC
    [-0,12, 0,04] no permite concluir nada.
    """
    y, p = _arrays(y_real, y_pred)
    r = p / y
    med = float(np.median(r))
    dependiente = (r - med) / med
    # Valor de referencia: mezcla del precio real y del estimado deflactado al nivel.
    independiente = np.log(0.5 * y + 0.5 * p / med) / np.log(2.0)

    n = y.size
    nan = float("nan")
    if n < 3:
        return ResultadoPRB(nan, nan, nan, (nan, nan))

    x_centrado = independiente - independiente.mean()
    sxx = float(x_centrado @ x_centrado)
    if sxx == 0:
        return ResultadoPRB(nan, nan, nan, (nan, nan))

    coef = float(x_centrado @ (dependiente - dependiente.mean()) / sxx)
    intercepto = float(dependiente.mean() - coef * independiente.mean())
    residuos = dependiente - (intercepto + coef * independiente)
    sigma2 = float(residuos @ residuos) / (n - 2)
    se = float(np.sqrt(sigma2 / sxx))
    t = coef / se if se > 0 else nan
    return ResultadoPRB(coef, se, t, (coef - 1.96 * se, coef + 1.96 * se))


# --------------------------------------------------------------------------
# Complementarias
# --------------------------------------------------------------------------
def mae(y_real, y_pred) -> float:
    y, p = _arrays(y_real, y_pred)
    return float(np.mean(np.abs(p - y)))


def rmse(y_real, y_pred) -> float:
    y, p = _arrays(y_real, y_pred)
    return float(np.sqrt(np.mean((p - y) ** 2)))


def r2(y_real, y_pred) -> float:
    y, p = _arrays(y_real, y_pred)
    ss_res = float(((y - p) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return float("nan") if ss_tot == 0 else 1.0 - ss_res / ss_tot


def sesgo_pct(y_real, y_pred) -> float:
    """Error porcentual medio con signo. Positivo = el modelo sobrevalora."""
    y, p = _arrays(y_real, y_pred)
    return float(100.0 * np.mean((p - y) / y))


def tabla_metricas(y_real, y_pred, *, operacion: str | None = None) -> dict:
    """Todas las metricas de una prediccion. Es la unidad de reporte del proyecto."""
    if operacion is not None:
        validar_escala(y_real, operacion)
    y, p = _arrays(y_real, y_pred)
    resultado_prb = prb(y, p)
    return {
        "n": int(y.size),
        "mdape": mdape(y, p),
        "mape": mape(y, p),
        "ppe10": ppe(y, p, 10.0),
        "ppe20": ppe(y, p, 20.0),
        "cod": cod(y, p),
        "prd": prd(y, p),
        "prb": resultado_prb.coef,
        "prb_ic95": list(resultado_prb.ic95),
        "mediana_ratio": mediana_ratio(y, p),
        "mae": mae(y, p),
        "rmse": rmse(y, p),
        "r2": r2(y, p),
        "sesgo_pct": sesgo_pct(y, p),
    }


def metricas_por_grupo(y_real, y_pred, grupos, *, minimo: int = 30) -> pd.DataFrame:
    """MdAPE y PPE10 desglosados. Para el chequeo de error homogeneo por comuna."""
    df = pd.DataFrame({
        "y": np.asarray(y_real, dtype=float).ravel(),
        "p": np.asarray(y_pred, dtype=float).ravel(),
        "g": np.asarray(grupos).ravel(),
    })
    filas = []
    for nombre, sub in df.groupby("g", observed=True):
        if len(sub) < minimo:
            continue
        filas.append({
            "grupo": nombre,
            "n": len(sub),
            "mdape": mdape(sub["y"], sub["p"]),
            "ppe10": ppe(sub["y"], sub["p"]),
            "mediana_ratio": mediana_ratio(sub["y"], sub["p"]),
        })
    if not filas:
        return pd.DataFrame(columns=["grupo", "n", "mdape", "ppe10", "mediana_ratio"])
    return pd.DataFrame(filas).sort_values("mdape").reset_index(drop=True)


def cumple_iaao(metricas: dict) -> dict:
    """Contrasta contra los rangos del estandar IAAO."""
    return {
        "cod": config.IAAO_COD[0] <= metricas["cod"] <= config.IAAO_COD[1],
        "prd": config.IAAO_PRD[0] <= metricas["prd"] <= config.IAAO_PRD[1],
        "prb": config.IAAO_PRB[0] <= metricas["prb"] <= config.IAAO_PRB[1],
    }
