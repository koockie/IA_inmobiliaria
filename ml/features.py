"""Features derivadas y preprocesamiento.

Todo el preprocesamiento vive dentro de un ColumnTransformer, que a su vez vive
dentro de un Pipeline. Asi la imputacion, el agrupamiento de la cola larga de
barrios y el target encoding se ajustan SOLO con el fold de entrenamiento, sin
que haya una ruta para hacerlo mal.

La otra defensa es `remainder="drop"`: si una columna prohibida sobrevive por
descuido en el DataFrame, nunca llega al estimador.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler, TargetEncoder

from ml import config

NUMERICAS_BASE = [
    "m2_util", "m2_total", "dormitorios", "banos", "estacionamientos",
    "bodegas", "gastos_comunes_clp", "lat", "lon",
]
DERIVADAS = [
    "log_m2_util", "ratio_terraza", "antiguedad", "densidad_banos", "m2_por_dormitorio",
]
FLAGS = [
    "tiene_estacionamiento", "tiene_bodega", "estacionamientos_informado",
    "gc_informado", "m2_total_igual_util", "m2_inconsistente", "geo_valida",
]
ONEHOT = ["comuna", "tipo"]
TARGET_ENC = ["comuna_barrio"]


@dataclass(frozen=True)
class EspecFeatures:
    numericas: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    onehot: list[str] = field(default_factory=list)
    target_enc: list[str] = field(default_factory=list)

    @property
    def todas(self) -> list[str]:
        return [*self.numericas, *self.flags, *self.onehot, *self.target_enc]

    def a_dict(self) -> dict:
        return {"numericas": self.numericas, "flags": self.flags,
                "onehot": self.onehot, "target_encoding": self.target_enc}


def clave_barrio(df: pd.DataFrame) -> pd.Series:
    """Concatena comuna y barrio.

    El dataset tiene 366 nombres de barrio pero 377 pares (comuna, barrio): once
    nombres se repiten entre comunas. Codificar por nombre suelto mezclaria
    barrios homonimos de comunas con niveles de precio muy distintos (la mediana
    de Nunoa-depto son 86,8 UF/m2 contra 58,3 en San Miguel).
    """
    comuna = df["comuna"].fillna("sin_comuna").astype(str)
    barrio = df["barrio"].fillna("sin_barrio").astype(str) if "barrio" in df else "sin_barrio"
    return (comuna + "|" + barrio).astype("string")


def derivar(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega las columnas derivadas. Funcion pura: devuelve un DataFrame nuevo."""
    m2_util = df["m2_util"]
    m2_total = df.get("m2_total", pd.Series(np.nan, index=df.index))
    dormitorios = df.get("dormitorios", pd.Series(np.nan, index=df.index))
    estac = df.get("estacionamientos", pd.Series(np.nan, index=df.index))
    bodegas = df.get("bodegas", pd.Series(np.nan, index=df.index))
    gastos = df.get("gastos_comunes_clp", pd.Series(np.nan, index=df.index))
    ano = df.get("ano_construccion", pd.Series(np.nan, index=df.index))

    # Denominador acotado a 1: `dormitorios = 0` es valido (monoambiente) y
    # dividir por el daria infinito.
    dorm_seguro = dormitorios.fillna(1).clip(lower=1)
    con_terraza = m2_total.notna() & (m2_total > 0)

    nuevas = {
        "log_m2_util": np.log(m2_util.where(m2_util > 0)),
        "ratio_terraza": ((m2_total - m2_util) / m2_total).where(con_terraza),
        "antiguedad": config.ANIO_REFERENCIA - ano,
        "densidad_banos": df.get("banos", pd.Series(np.nan, index=df.index)) / dorm_seguro,
        "m2_por_dormitorio": m2_util / dorm_seguro,
        # El faltante es informativo: estacionamientos solo tiene 53% de
        # cobertura, y no informarlo suele significar que no hay.
        "tiene_estacionamiento": (estac.fillna(0) > 0).astype("int8"),
        "tiene_bodega": (bodegas.fillna(0) > 0).astype("int8"),
        "estacionamientos_informado": estac.notna().astype("int8"),
        "gc_informado": gastos.notna().astype("int8"),
        # En 3.175 filas (22,5%) m2_total es una copia de m2_util, asi que ahi
        # no aporta informacion independiente.
        "m2_total_igual_util": (m2_total == m2_util).fillna(False).astype("int8"),
        "comuna_barrio": clave_barrio(df),
    }
    # `m2_inconsistente` y `geo_valida` los fija data.aplicar_filtros; si se
    # llama a derivar() por separado, se rellenan con el valor neutro.
    for col, defecto in (("m2_inconsistente", 0), ("geo_valida", 1)):
        if col not in df.columns:
            nuevas[col] = np.int8(defecto)
    return df.assign(**nuevas)


class AgrupadorCola(BaseEstimator, TransformerMixin):
    """Colapsa las categorias raras en OTROS, aprendiendo el corte solo del train.

    268 de los 377 pares (comuna, barrio) son singleton y el 86% de los barrios
    cubre apenas el 2,8% de los avisos. Contar las frecuencias sobre el dataset
    completo seria una fuga sutil: la presencia de un barrio en el fold de test
    influiria en si sobrevive como categoria propia en el train.
    """

    def __init__(self, min_freq: int = config.BARRIO_MIN_FREQ, etiqueta: str = "OTROS"):
        self.min_freq = min_freq
        self.etiqueta = etiqueta

    def fit(self, X, y=None):
        X = pd.DataFrame(X)
        self.categorias_ = {}
        for col in X.columns:
            conteo = X[col].astype("string").value_counts()
            self.categorias_[col] = set(conteo[conteo >= self.min_freq].index)
        self.n_features_in_ = X.shape[1]
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        return self

    def transform(self, X):
        X = pd.DataFrame(X).copy()
        for col in X.columns:
            permitidas = self.categorias_.get(col, set())
            serie = X[col].astype("string")
            X[col] = serie.where(serie.isin(permitidas), self.etiqueta).astype(str)
        return X

    def get_feature_names_out(self, input_features=None):
        return np.asarray(input_features if input_features is not None
                          else self.feature_names_in_, dtype=object)


def espec_features(operacion: str, tipo: str = "todos", *,
                   incluir_sitio: bool = False) -> EspecFeatures:
    """Columnas que entran al modelo para un segmento dado.

    `sitio` queda fuera del modelo desplegado: la API no puede suministrarlo en
    inferencia (el usuario no sabe de que portal saldria su aviso). Se activa
    solo para la corrida diagnostica que mide el sesgo de fuente.
    """
    onehot = list(ONEHOT)
    if tipo != "todos":
        onehot.remove("tipo")          # constante dentro del segmento
    if incluir_sitio:
        onehot.append("sitio")
    return EspecFeatures(
        numericas=[*NUMERICAS_BASE, *DERIVADAS],
        flags=list(FLAGS),
        onehot=onehot,
        target_enc=list(TARGET_ENC),
    )


def _validar_sin_prohibidas(espec: EspecFeatures) -> None:
    filtradas = set(espec.todas) & config.COLUMNAS_PROHIBIDAS
    if filtradas:
        raise ValueError(f"columnas prohibidas en las features: {sorted(filtradas)}")


def construir_preprocesador(espec: EspecFeatures, familia: str) -> ColumnTransformer:
    """Arma el ColumnTransformer segun como el modelo trate los faltantes.

    familia:
      lineal        imputa la mediana, marca el faltante y escala
      arbol_nan     deja el NaN intacto: LightGBM, XGBoost y HistGradient lo
                    aprenden como categoria, y en `estacionamientos` (47% de
                    faltantes) la ausencia es senal, no ruido
      arbol_imputa  imputa sin escalar (RandomForest no admite NaN)
    """
    _validar_sin_prohibidas(espec)

    if familia == "lineal":
        pipe_num = Pipeline([
            ("imputar", SimpleImputer(strategy="median", add_indicator=True)),
            ("escalar", StandardScaler()),
        ])
    elif familia == "arbol_imputa":
        pipe_num = Pipeline([
            ("imputar", SimpleImputer(strategy="median", add_indicator=True)),
        ])
    elif familia == "arbol_nan":
        pipe_num = "passthrough"
    else:
        raise ValueError(f"familia desconocida: {familia}")

    # El TargetEncoder de sklearn hace cross-fitting interno (cv=5): las
    # codificaciones que ve el modelo durante el entrenamiento ya son
    # out-of-fold, que es justo la parte que mas se implementa mal a mano.
    # smooth="auto" aplica el suavizado empirico-bayesiano, que colapsa las
    # categorias raras hacia el prior global.
    # sklearn 1.9 depreco `random_state` en TargetEncoder: la forma soportada de
    # fijar el barajado es pasarle el generador de CV ya construido.
    pipe_barrio = Pipeline([
        ("cola", AgrupadorCola(min_freq=config.BARRIO_MIN_FREQ)),
        ("te", TargetEncoder(
            target_type="continuous", smooth="auto",
            cv=KFold(n_splits=5, shuffle=True, random_state=config.RANDOM_STATE))),
    ])

    return ColumnTransformer(
        transformers=[
            ("num", pipe_num, espec.numericas),
            ("flag", "passthrough", espec.flags),
            ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist",
                                  min_frequency=0.01, sparse_output=False),
             espec.onehot),
            ("barrio", pipe_barrio, espec.target_enc),
        ],
        # Nunca "passthrough": es lo que impide que una columna prohibida que
        # sobreviva en el DataFrame llegue al estimador.
        remainder="drop",
        verbose_feature_names_out=True,
    )


# Columnas crudas que `derivar` necesita para poder construir las derivadas.
REQUERIDAS = ["m2_util", "comuna"]


def preparar_matriz(df: pd.DataFrame, espec: EspecFeatures) -> pd.DataFrame:
    """Deriva y selecciona las columnas del modelo, en orden estable."""
    ausentes = [c for c in REQUERIDAS if c not in df.columns]
    if ausentes:
        raise KeyError(f"faltan columnas para el modelo: {ausentes}")

    completo = derivar(df)
    faltan = [c for c in espec.todas if c not in completo.columns]
    if faltan:
        raise KeyError(f"faltan columnas para el modelo: {faltan}")
    X = completo[espec.todas].copy()
    for col in espec.numericas:
        X[col] = pd.to_numeric(X[col], errors="coerce").astype("float64")
    for col in espec.flags:
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0).astype("float64")
    for col in [*espec.onehot, *espec.target_enc]:
        X[col] = X[col].astype("string").fillna("desconocido").astype(str)
    return X
