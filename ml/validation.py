"""Validacion cruzada espacial.

Un split aleatorio por fila es invalido en este dataset: 8.307 ubicaciones
distintas cubren 14.348 filas geolocalizadas, y el 56-62% de las filas comparte
coordenada con otra. Con `train_test_split` casi todo edificio grande queda
repartido entre train y test, el modelo memoriza el precio de la torre y el
MdAPE reportado sale optimista por un margen grande.

Se reportan tres esquemas, siempre juntos:

    aleatorio          KFold normal. Es la cota optimista.
    espacial           GroupKFold por edificio. Es la cifra honesta.
    espacial_estricto  Igual, pero las filas sin geo se quedan en train y se
                       excluyen del test. Acota el efecto de las 1.460 filas
                       cuya agrupacion no se puede verificar.

La diferencia entre el primero y el segundo es a la vez el chequeo de fuga y un
resultado documentable: si el espacial sale MEJOR que el aleatorio, hay un bug.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit, KFold, StratifiedGroupKFold

from ml import config
from ml.data import normalizar_texto

ESQUEMAS = ("aleatorio", "espacial", "espacial_estricto")


def clave_espacial(df: pd.DataFrame, *, decimales: int = config.GEO_DECIMALES) -> pd.Series:
    """Identificador del edificio de cada aviso, con cascada de respaldo.

    A 4 decimales la celda mide ~11 x 9 m, que es la huella de un edificio: la
    unidad de fuga que importa. A 3 decimales (~110 m) la celda es la manzana,
    el 89,7% de las filas queda encadenado y los folds se desbalancean, ademas
    de absorber variacion de microlocalizacion que si es aprendible.

    Cascada para las 1.460 filas sin coordenada (las 1.346 de chilepropiedades
    mas 114 de portalinmobiliario):

        geo valida        -> "g:<lat>,<lon>"
        sin geo, con dir  -> "d:<direccion normalizada>"
        sin nada          -> "u:<indice>"   (singleton)

    No se agrupa por `barrio`, que es lo que sugiere el documento de traspaso:
    377 grupos con 268 singletons desbalancean los folds, y peor, dejarian todo
    barrio del test como inedito, con lo que el target encoding devolveria el
    prior en el 100% de los casos. Eso no mide fuga espacial: mide el modelo sin
    la variable barrio, que es otra pregunta.
    """
    lat, lon = df.get("lat"), df.get("lon")
    if lat is None or lon is None:
        raise KeyError("faltan las columnas lat/lon")

    geo_ok = lat.notna() & lon.notna()
    claves = pd.Series(pd.NA, index=df.index, dtype="object")
    # Un solo paso de redondeo, via formato: encadenar .round() con el formato
    # redondea dos veces y en un borde exacto puede partir un grupo en dos.
    if geo_ok.any():
        fmt = f"{{:.{decimales}f}}".format
        claves[geo_ok] = ("g:" + lat[geo_ok].map(fmt) + "," + lon[geo_ok].map(fmt))

    sin_geo = ~geo_ok
    if "direccion" in df.columns and sin_geo.any():
        dirs = df.loc[sin_geo, "direccion"].map(normalizar_texto)
        con_dir = dirs != ""
        if con_dir.any():
            claves[dirs.index[con_dir]] = "d:" + dirs[con_dir]

    faltan = claves.isna()
    claves[faltan] = [f"u:{i}" for i in df.index[faltan]]
    return claves.astype("string")


@dataclass(frozen=True)
class ResumenGrupos:
    n_filas: int
    n_grupos: int
    n_grupos_multiples: int
    filas_en_grupo_multiple: int
    pct_filas_en_grupo_multiple: float
    grupo_maximo: int
    n_singletons: int
    por_fuente: dict

    def a_dict(self) -> dict:
        return {
            "n_filas": self.n_filas, "n_grupos": self.n_grupos,
            "n_grupos_multiples": self.n_grupos_multiples,
            "filas_en_grupo_multiple": self.filas_en_grupo_multiple,
            "pct_filas_en_grupo_multiple": round(self.pct_filas_en_grupo_multiple, 2),
            "grupo_maximo": self.grupo_maximo, "n_singletons": self.n_singletons,
            "por_fuente": self.por_fuente,
        }


def resumen_grupos(claves: pd.Series) -> ResumenGrupos:
    """Diagnostico de la estructura espacial. Sirve para justificar el redondeo."""
    tam = claves.value_counts()
    multiples = tam[tam > 1]
    return ResumenGrupos(
        n_filas=int(len(claves)),
        n_grupos=int(len(tam)),
        n_grupos_multiples=int(len(multiples)),
        filas_en_grupo_multiple=int(multiples.sum()),
        pct_filas_en_grupo_multiple=float(100.0 * multiples.sum() / len(claves)),
        grupo_maximo=int(tam.max()) if len(tam) else 0,
        n_singletons=int((tam == 1).sum()),
        por_fuente={
            "geo": int(claves.str.startswith("g:").sum()),
            "direccion": int(claves.str.startswith("d:").sum()),
            "singleton": int(claves.str.startswith("u:").sum()),
        },
    )


def _estratos(y: pd.Series | np.ndarray, n: int = 5) -> np.ndarray:
    """Quintiles del target, para que los folds sean comparables en precio."""
    serie = pd.Series(np.asarray(y, dtype=float))
    try:
        return pd.qcut(serie, n, labels=False, duplicates="drop").to_numpy()
    except ValueError:
        return np.zeros(len(serie), dtype=int)


def hacer_cv(esquema: str, *, n_splits: int = config.CV_N_SPLITS,
             semilla: int = config.RANDOM_STATE):
    """Devuelve el objeto de validacion cruzada del esquema pedido."""
    if esquema not in ESQUEMAS:
        raise ValueError(f"esquema invalido: {esquema}. Use uno de {ESQUEMAS}")
    if esquema == "aleatorio":
        return KFold(n_splits=n_splits, shuffle=True, random_state=semilla)
    return StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=semilla)


def particiones(df: pd.DataFrame, y, esquema: str, *,
                n_splits: int = config.CV_N_SPLITS,
                semilla: int = config.RANDOM_STATE):
    """Genera (train, test) posicionales segun el esquema.

    En `espacial_estricto` el fold de test se poda a las filas con geo valida,
    pero el train conserva todo: las filas sin coordenada aportan senal aunque
    no se pueda verificar que no filtran.
    """
    if esquema not in ESQUEMAS:
        raise ValueError(f"esquema invalido: {esquema}. Use uno de {ESQUEMAS}")

    n = len(df)
    indices = np.arange(n)
    cv = hacer_cv(esquema, n_splits=n_splits, semilla=semilla)

    if esquema == "aleatorio":
        yield from cv.split(indices)
        return

    claves = clave_espacial(df).to_numpy()
    if len(np.unique(claves)) < n_splits:
        raise ValueError(
            f"solo hay {len(np.unique(claves))} grupos espaciales para {n_splits} folds"
        )

    con_geo = clave_espacial(df).str.startswith("g:").to_numpy()
    for train, test in cv.split(indices, _estratos(y), groups=claves):
        if esquema == "espacial_estricto":
            test = test[con_geo[test]]
            if len(test) == 0:
                continue
        yield train, test


def verificar_disyuncion(df: pd.DataFrame, train: np.ndarray, test: np.ndarray) -> None:
    """Aborta si algun edificio aparece a la vez en train y test.

    Es la garantia que hace honesto al esquema espacial; se comprueba en cada
    fold durante el entrenamiento, no solo en los tests.
    """
    claves = clave_espacial(df).to_numpy()
    comunes = set(claves[train]) & set(claves[test])
    if comunes:
        muestra = sorted(comunes)[:5]
        raise AssertionError(
            f"{len(comunes)} grupos espaciales aparecen en train y test: {muestra}"
        )


def grupos_para_holdout(df: pd.DataFrame) -> np.ndarray:
    """Claves para GroupShuffleSplit (holdout externo previo al tuning)."""
    return clave_espacial(df).to_numpy()


def separar_holdout(df: pd.DataFrame, *, fraccion: float = 0.2,
                    semilla: int = config.RANDOM_STATE
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Aparta un conjunto final que no se toca hasta el ultimo paso.

    La validacion cruzada ya da metricas fuera de muestra: cada fila la predice
    un modelo que no la vio. Pero esas mismas metricas se usan para ELEGIR
    (que modelo gana, que hiperparametros), y elegir sobre una medicion la
    contamina como estimador de error futuro. Con 5 candidatos el sesgo es
    leve; con 40 combinaciones de tuning deja de serlo.

    El holdout se separa **por grupos espaciales**, no por filas: si un
    departamento de la torre queda en desarrollo y otro en el holdout, el
    holdout deja de ser independiente y no mide nada.

    Devuelve (indices_desarrollo, indices_holdout) posicionales.
    """
    if not 0.0 < fraccion < 1.0:
        raise ValueError(f"fraccion debe estar entre 0 y 1, no {fraccion}")

    grupos = clave_espacial(df).to_numpy()
    n_grupos = len(np.unique(grupos))
    if n_grupos < 10:
        raise ValueError(f"solo hay {n_grupos} grupos espaciales: muy pocos "
                         "para apartar un holdout representativo")

    separador = GroupShuffleSplit(n_splits=1, test_size=fraccion, random_state=semilla)
    desarrollo, holdout = next(separador.split(np.arange(len(df)), groups=grupos))
    return np.sort(desarrollo), np.sort(holdout)
