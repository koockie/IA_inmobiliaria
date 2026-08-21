"""Registro de modelos con interfaz comun.

Todos comparten la misma firma (`fit`/`predict`), el mismo split y las mismas
metricas, para que la comparacion sea justa.

Cada modelo se envuelve en un TransformedTargetRegressor que entrena sobre
log(precio) y exponencia al predecir. Eso hace estructuralmente imposible el
error de "evaluar en escala log": `predict()` devuelve siempre UF o CLP.

Nota sobre la retransformacion: exp(media de logs) estima la MEDIANA
condicional, no la media. Es exactamente lo que miden MdAPE, PPE10 y COD, asi
que no se aplica la correccion de smearing de Duan; hacerlo mejoraria el sesgo
en media y empeoraria el MdAPE, que es la metrica que importa en tasacion.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Callable, Literal

import numpy as np
from sklearn.base import BaseEstimator
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from ml import config
from ml.features import EspecFeatures, construir_preprocesador

Familia = Literal["lineal", "arbol_nan", "arbol_imputa"]


def _hay(paquete: str) -> bool:
    return importlib.util.find_spec(paquete) is not None


@dataclass(frozen=True)
class EspecModelo:
    nombre: str
    familia: Familia
    construir: Callable[[int], BaseEstimator]
    espacio: dict = field(default_factory=dict)
    shap_nativo: bool = False
    cuantiles: bool = False
    requiere: str | None = None

    @property
    def disponible(self) -> bool:
        return self.requiere is None or _hay(self.requiere)


def _ridge(semilla: int) -> BaseEstimator:
    return Ridge(alpha=1.0, random_state=semilla)


def _random_forest(semilla: int) -> BaseEstimator:
    return RandomForestRegressor(
        n_estimators=300, min_samples_leaf=2, max_features="sqrt",
        n_jobs=-1, random_state=semilla)


def _hist_gradient(semilla: int) -> BaseEstimator:
    return HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.06, max_leaf_nodes=31,
        min_samples_leaf=20, l2_regularization=1.0, random_state=semilla)


def _xgboost(semilla: int) -> BaseEstimator:
    from xgboost import XGBRegressor
    return XGBRegressor(
        n_estimators=600, learning_rate=0.05, max_depth=6,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        reg_lambda=1.0, n_jobs=-1, random_state=semilla, tree_method="hist")


def _lightgbm(semilla: int) -> BaseEstimator:
    from lightgbm import LGBMRegressor
    return LGBMRegressor(
        n_estimators=700, learning_rate=0.05, num_leaves=31,
        min_child_samples=20, subsample=0.8, subsample_freq=1,
        colsample_bytree=0.8, reg_lambda=1.0,
        n_jobs=-1, random_state=semilla, verbose=-1)


REGISTRO: dict[str, EspecModelo] = {
    "ridge": EspecModelo(
        "ridge", "lineal", _ridge,
        espacio={"regressor__modelo__alpha": [0.1, 0.3, 1.0, 3.0, 10.0, 30.0]},
        shap_nativo=False),
    "random_forest": EspecModelo(
        "random_forest", "arbol_imputa", _random_forest,
        espacio={"regressor__modelo__n_estimators": [200, 400, 600],
                 "regressor__modelo__min_samples_leaf": [1, 2, 5, 10],
                 "regressor__modelo__max_features": ["sqrt", 0.3, 0.5]}),
    "hist_gradient": EspecModelo(
        "hist_gradient", "arbol_nan", _hist_gradient,
        espacio={"regressor__modelo__learning_rate": [0.03, 0.06, 0.1],
                 "regressor__modelo__max_leaf_nodes": [15, 31, 63],
                 "regressor__modelo__min_samples_leaf": [10, 20, 40],
                 "regressor__modelo__l2_regularization": [0.0, 1.0, 5.0]},
        cuantiles=True),
    "xgboost": EspecModelo(
        "xgboost", "arbol_nan", _xgboost, requiere="xgboost", shap_nativo=True,
        espacio={"regressor__modelo__learning_rate": [0.03, 0.05, 0.1],
                 "regressor__modelo__max_depth": [4, 6, 8],
                 "regressor__modelo__min_child_weight": [1, 5, 10],
                 "regressor__modelo__subsample": [0.7, 0.8, 1.0],
                 "regressor__modelo__colsample_bytree": [0.7, 0.8, 1.0]},
        cuantiles=True),
    "lightgbm": EspecModelo(
        "lightgbm", "arbol_nan", _lightgbm, requiere="lightgbm", shap_nativo=True,
        espacio={"regressor__modelo__learning_rate": [0.03, 0.05, 0.1],
                 "regressor__modelo__num_leaves": [15, 31, 63, 127],
                 "regressor__modelo__min_child_samples": [10, 20, 40],
                 "regressor__modelo__subsample": [0.7, 0.8, 1.0],
                 "regressor__modelo__colsample_bytree": [0.7, 0.8, 1.0]},
        cuantiles=True),
}


def modelos_disponibles() -> list[str]:
    """Solo los que tienen su dependencia instalada."""
    return [n for n, e in REGISTRO.items() if e.disponible]


def resolver(nombres: str | list[str]) -> list[str]:
    """Acepta 'todos', una lista o una cadena separada por comas."""
    if isinstance(nombres, str):
        nombres = list(modelos_disponibles()) if nombres == "todos" else \
            [n.strip() for n in nombres.split(",") if n.strip()]
    desconocidos = [n for n in nombres if n not in REGISTRO]
    if desconocidos:
        raise ValueError(f"modelos desconocidos: {desconocidos}. "
                         f"Disponibles: {modelos_disponibles()}")
    faltantes = [n for n in nombres if not REGISTRO[n].disponible]
    if faltantes:
        raise ValueError(f"faltan dependencias para: {faltantes}")
    return nombres


def construir(nombre: str, espec: EspecFeatures, *,
              semilla: int = config.RANDOM_STATE) -> TransformedTargetRegressor:
    """Pipeline completo listo para `fit`, con el target en log.

    Las tres capas, de fuera hacia dentro:
        TransformedTargetRegressor(log/exp)
          Pipeline
            ColumnTransformer   <- imputacion, one-hot y target encoding
            estimador
    """
    modelo = REGISTRO[nombre]
    interno = Pipeline([
        ("prep", construir_preprocesador(espec, modelo.familia)),
        ("modelo", modelo.construir(semilla)),
    ])
    return TransformedTargetRegressor(
        regressor=interno, func=np.log, inverse_func=np.exp, check_inverse=False)
