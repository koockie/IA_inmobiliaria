"""Construccion de variables, compartida por los dos modelos y por la API.

Por que existe este modulo: hasta ahora `construir_features()` vivia dentro de
cada notebook. El pipeline guardado en el .joblib empieza DESPUES de ese paso,
asi que la API tendria que reimplementarlo a mano y cualquier diferencia
silenciosa -- un `log1p` que falta, un `fillna` distinto -- degradaria la
prediccion sin lanzar ningun error.

Este archivo es la unica definicion. `qa/qa_modelos.py` comprueba celda a celda
que produce exactamente lo mismo que los notebooks sobre datos reales.

Genera el superconjunto de columnas de los dos modelos; cada uno se queda con
las suyas segun la lista `columnas` que trae su paquete.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

CATEGORIAS_POI = ["metro", "salud", "comercio", "universidad",
                  "educacion", "parque", "supermercado"]

ANIO_REFERENCIA = 2026

# Columnas crudas que los notebooks convierten a numerico antes de nada.
NUMERICAS = ["precio_uf", "precio_clp", "m2_util", "m2_total", "dormitorios", "banos",
             "estacionamientos", "bodegas", "ano_construccion", "antiguedad_anos",
             "gastos_comunes_clp", "lat", "lon"]


def abrir_servicios(serie: pd.Series) -> pd.DataFrame:
    """El JSON de servicios_cercanos -> columnas numericas."""
    filas = []
    for s in serie:
        d: dict = {}
        if isinstance(s, str) and s not in ("", "SIN_DATO"):
            j = json.loads(s)
            for cat in CATEGORIAS_POI:
                v = j.get(cat)
                d[f"dist_{cat}_m"] = v["mas_cercano_m"] if v else np.nan
                d[f"n_{cat}_1km"] = v["n_1km"] if v else np.nan
            d["servicios_truncado"] = float(j.get("_truncado", False))
        elif isinstance(s, dict):          # la API puede pasar el dict ya parseado
            for cat in CATEGORIAS_POI:
                v = s.get(cat)
                d[f"dist_{cat}_m"] = v["mas_cercano_m"] if v else np.nan
                d[f"n_{cat}_1km"] = v["n_1km"] if v else np.nan
            d["servicios_truncado"] = float(s.get("_truncado", False))
        else:
            for cat in CATEGORIAS_POI:
                d[f"dist_{cat}_m"] = np.nan
                d[f"n_{cat}_1km"] = np.nan
            d["servicios_truncado"] = np.nan
        filas.append(d)
    return pd.DataFrame(filas, index=serie.index)


def construir_features(d: pd.DataFrame, anio: int = ANIO_REFERENCIA) -> pd.DataFrame:
    """Las tres familias de atributos del marco hedonico, mas los indicadores
    de ausencia que usa el modelo de arriendo.

    Replica exactamente lo que hacen `modelo_venta.ipynb` y
    `modelo_arriendo.ipynb`. Cualquier cambio aqui invalida los .joblib ya
    entrenados: reentrenar antes de tocarlo.
    """
    d = d.copy()
    dorm = d["dormitorios"].fillna(1).clip(lower=1)

    # --- estructurales ---
    d["antiguedad"] = anio - d["ano_construccion"]
    d["log_m2_util"] = np.log(d["m2_util"])
    d["ratio_terraza"] = ((d["m2_total"] - d["m2_util"]) / d["m2_total"]).where(
        d["m2_total"].notna() & (d["m2_total"] > 0))
    d["m2_por_dormitorio"] = d["m2_util"] / dorm
    d["densidad_banos"] = d["banos"] / dorm
    d["es_casa"] = (d["tipo"] == "casa").astype(float)
    d["tiene_estacionamiento"] = (d["estacionamientos"].fillna(0) > 0).astype(float)
    d["tiene_bodega"] = (d["bodegas"].fillna(0) > 0).astype(float)

    # --- ubicacion y vecindario ---
    d["sin_geo"] = (d["lat"].isna() | d["lon"].isna()).astype(float)
    d = pd.concat([d, abrir_servicios(d["servicios_cercanos"])], axis=1)
    d["sin_servicios"] = d[f"dist_{CATEGORIAS_POI[0]}_m"].isna().astype(float)
    for cat in CATEGORIAS_POI:
        d[f"log_dist_{cat}"] = np.log1p(d[f"dist_{cat}_m"])
    return d


def preparar_entrada(atributos: dict, columnas: list[str],
                     anio: int = ANIO_REFERENCIA) -> pd.DataFrame:
    """Un diccionario de atributos crudos -> la fila que espera el modelo.

    Rellena con NaN todo lo que falte: los modelos de arboles lo manejan de
    forma nativa y la API baja la confianza en consecuencia.
    """
    fila = pd.DataFrame([atributos])
    for c in NUMERICAS + ["servicios_cercanos", "tipo", "comuna"]:
        if c not in fila.columns:
            fila[c] = np.nan
    for c in NUMERICAS:
        fila[c] = pd.to_numeric(fila[c], errors="coerce")
    fila = construir_features(fila, anio=anio)
    for c in columnas:
        if c not in fila.columns:
            fila[c] = np.nan
    return fila[list(columnas)]


def normalizar_comuna(texto: str | None) -> str | None:
    """'Ñuñoa' / 'NUNOA' / 'La Florida' -> el slug que vio el modelo."""
    if texto is None or (isinstance(texto, float) and np.isnan(texto)):
        return None
    t = str(texto).strip().lower()
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n",
                  "ü": "u", " ": "-", "_": "-"}
    for a, b in reemplazos.items():
        t = t.replace(a, b)
    return t or None
