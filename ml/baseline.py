"""Regresion hedonica clasica: el piso de comparacion.

Su valor no es la precision, sino tres cosas:

  1. Un piso contra el que medir a los modelos de ML.
  2. La validacion de signos: mas m2 debe subir el precio y mas antiguedad
     bajarlo. Un signo invertido apunta a un problema en los datos, no en el
     modelo, y conviene detectarlo antes de entrenar nada complejo.
  3. La I de Moran sobre los residuos: si queda autocorrelacion espacial, es la
     justificacion empirica para meter lat/lon en los arboles.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.neighbors import NearestNeighbors

from ml import config, features

# Solo los signos robustos de la teoria hedonica. `dormitorios` NO esta:
# condicionado a la superficie suele salir negativo (mas piezas en los mismos
# metros = piezas mas chicas), y eso no es un bug de datos.
SIGNOS_ESPERADOS = {
    "log_m2_util": +1,
    "antiguedad": -1,
    "estacionamientos": +1,
    "bodegas": +1,
    "banos": +1,
}
SIGNOS_AMBIGUOS = {"dormitorios", "ratio_terraza", "densidad_banos", "m2_por_dormitorio"}

VARIABLES_HEDONICAS = [
    "log_m2_util", "dormitorios", "banos", "antiguedad",
    "estacionamientos", "bodegas",
]


@dataclass
class ResultadoBaseline:
    coeficientes: pd.DataFrame
    r2: float
    r2_ajustado: float
    n: int
    n_segmento: int
    vif: pd.Series
    moran_i: float | None
    moran_p: float | None
    incumplimientos: list[str]

    def a_dict(self) -> dict:
        return {
            "n": self.n, "n_segmento": self.n_segmento,
            "pct_casos_completos": round(100.0 * self.n / max(self.n_segmento, 1), 1),
            "r2": self.r2, "r2_ajustado": self.r2_ajustado,
            "coeficientes": self.coeficientes.to_dict("index"),
            "vif": {k: float(v) for k, v in self.vif.items()},
            "moran_i": self.moran_i, "moran_p": self.moran_p,
            "signos_incumplidos": self.incumplimientos,
        }

    def como_tabla(self) -> str:
        pct = 100.0 * self.n / max(self.n_segmento, 1)
        lineas = [f"Baseline hedonico  (n = {self.n:,}  R2 = {self.r2:.4f}  "
                  f"R2 aj = {self.r2_ajustado:.4f})",
                  f"OLS usa solo casos completos: {self.n:,} de {self.n_segmento:,} "
                  f"filas del segmento ({pct:.0f}%). El resto cae por listwise "
                  f"deletion, sobre todo por estacionamientos (53% de cobertura).",
                  f"Los modelos de ML si usan las {self.n_segmento:,}: el R2 de arriba "
                  f"NO es comparable directamente con sus metricas.", "-" * 78,
                  f"{'variable':<26}{'coef':>12}{'error est':>12}{'t':>10}{'p':>10}{'VIF':>8}"]
        for nombre, fila in self.coeficientes.iterrows():
            v = self.vif.get(nombre, float("nan"))
            vif_txt = f"{v:>8.2f}" if np.isfinite(v) else f"{'-':>8}"
            lineas.append(f"{nombre:<26}{fila['coef']:>12.4f}{fila['error_estandar']:>12.4f}"
                          f"{fila['t']:>10.2f}{fila['p']:>10.4f}{vif_txt}")
        lineas.append("-" * 78)
        if self.moran_i is not None:
            veredicto = ("queda autocorrelacion espacial: la ubicacion aporta senal "
                         "que el modelo lineal no captura"
                         if self.moran_p is not None and self.moran_p < 0.05
                         else "sin autocorrelacion espacial significativa")
            lineas.append(f"I de Moran sobre residuos: {self.moran_i:+.4f} "
                          f"(p = {self.moran_p:.3f}) -> {veredicto}")
        if self.incumplimientos:
            lineas.append("SIGNOS INCUMPLIDOS: " + ", ".join(self.incumplimientos))
        else:
            lineas.append("Todos los signos robustos son teoricamente correctos.")
        return "\n".join(lineas)


def calcular_vif(X: pd.DataFrame) -> pd.Series:
    """Factor de inflacion de varianza: VIF_j = 1 / (1 - R2_j).

    Se calcula regresando cada variable contra el resto. Por encima de 10 suele
    considerarse multicolinealidad problematica.
    """
    valores = {}
    columnas = list(X.columns)
    for col in columnas:
        otras = [c for c in columnas if c != col]
        if not otras:
            valores[col] = 1.0
            continue
        y = X[col].to_numpy(dtype=float)
        # Una columna constante no tiene varianza que explicar: su R2 saldria
        # 0/0. El VIF no esta definido, no vale 1.
        if np.allclose(y, y[0]):
            valores[col] = float("nan")
            continue
        A = sm.add_constant(X[otras].to_numpy(dtype=float), has_constant="add")
        try:
            r2 = sm.OLS(y, A).fit().rsquared
            valores[col] = float("inf") if r2 >= 1 - 1e-12 else 1.0 / (1.0 - r2)
        except Exception:
            valores[col] = float("nan")
    return pd.Series(valores)


def moran_i(residuos: np.ndarray, lat: np.ndarray, lon: np.ndarray, *,
            k: int = 8, n_perm: int = 999,
            semilla: int = config.RANDOM_STATE) -> tuple[float, float]:
    """I de Moran con pesos k-NN y p-valor por permutacion.

    Se implementa a mano en vez de traer libpysal: son pocas lineas y evita una
    dependencia mas. El p-valor sale por permutacion en lugar de por la varianza
    analitica, que asume normalidad.

    Positivo y significativo = los residuos se agrupan en el espacio, o sea que
    el modelo no esta capturando toda la ubicacion.
    """
    ok = np.isfinite(residuos) & np.isfinite(lat) & np.isfinite(lon)
    z = residuos[ok] - residuos[ok].mean()
    n = z.size
    if n < k + 2:
        return float("nan"), float("nan")

    # Proyeccion local a metros: a esta latitud un grado de longitud mide
    # cos(lat) veces lo que uno de latitud.
    escala = np.cos(np.deg2rad(np.abs(lat[ok]).mean()))
    coords = np.column_stack([lat[ok], lon[ok] * escala])

    vecinos = NearestNeighbors(n_neighbors=k + 1).fit(coords)
    _, idx = vecinos.kneighbors(coords)
    idx = idx[:, 1:]                       # descarta el punto consigo mismo

    def _i(valores: np.ndarray) -> float:
        # I = (n/W) * sum_ij w_ij z_i z_j / sum_i z_i^2. Con pesos
        # fila-estandarizados cada vecino pesa 1/k, de modo que W = n y el
        # factor n/W se cancela.
        vecindad = valores[idx].mean(axis=1)
        return float((valores @ vecindad) / (valores @ valores))

    observado = _i(z)
    rng = np.random.default_rng(semilla)
    nulos = np.array([_i(rng.permutation(z)) for _ in range(n_perm)])
    # p bilateral: proporcion de permutaciones tan extremas como la observada.
    p = (1 + np.sum(np.abs(nulos - nulos.mean()) >= abs(observado - nulos.mean()))) / (n_perm + 1)
    return observado, float(p)


def validar_signos(coeficientes: pd.DataFrame) -> list[str]:
    """Devuelve los incumplimientos de los signos teoricamente robustos."""
    fallos = []
    for variable, esperado in SIGNOS_ESPERADOS.items():
        if variable not in coeficientes.index:
            continue
        coef = coeficientes.loc[variable, "coef"]
        p = coeficientes.loc[variable, "p"]
        # Solo se reporta si ademas es significativo: un coeficiente no
        # significativo con el signo "equivocado" es ruido, no evidencia.
        if p < 0.05 and np.sign(coef) != esperado:
            fallos.append(f"{variable} (esperado {'+' if esperado > 0 else '-'}, "
                          f"obtenido {coef:+.4f}, p={p:.4f})")
    return fallos


def ajustar(df: pd.DataFrame, operacion: str, *, con_moran: bool = True) -> ResultadoBaseline:
    """Ajusta la hedonica log-log sobre el segmento y valida sus signos."""
    target = config.TARGET[operacion]
    completo = features.derivar(df)

    variables = [v for v in VARIABLES_HEDONICAS if v in completo.columns]
    X = completo[variables].apply(pd.to_numeric, errors="coerce")
    # Dummies de comuna (y de tipo si el segmento mezcla ambos).
    for col in ("comuna", "tipo"):
        if col in completo.columns and completo[col].nunique() > 1:
            X = pd.concat([X, pd.get_dummies(completo[col], prefix=col,
                                             drop_first=True, dtype=float)], axis=1)

    y = np.log(pd.to_numeric(completo[target], errors="coerce"))
    usable = X.notna().all(axis=1) & np.isfinite(y)
    X, y = X[usable], y[usable]
    if len(X) < 30:
        raise ValueError(f"muy pocas filas completas para el baseline: {len(X)}")

    modelo = sm.OLS(y.to_numpy(), sm.add_constant(X.to_numpy(dtype=float),
                                                  has_constant="add")).fit()
    nombres = ["const", *X.columns]
    coeficientes = pd.DataFrame({
        "coef": modelo.params, "error_estandar": modelo.bse,
        "t": modelo.tvalues, "p": modelo.pvalues,
    }, index=nombres)

    moran, moran_p = (None, None)
    if con_moran and {"lat", "lon"} <= set(completo.columns):
        sub = completo.loc[usable[usable].index]
        moran, moran_p = moran_i(modelo.resid,
                                 sub["lat"].to_numpy(dtype=float),
                                 sub["lon"].to_numpy(dtype=float))
        if not np.isfinite(moran):
            moran, moran_p = None, None

    return ResultadoBaseline(
        coeficientes=coeficientes,
        r2=float(modelo.rsquared), r2_ajustado=float(modelo.rsquared_adj),
        n=int(len(X)), n_segmento=int(len(df)), vif=calcular_vif(X),
        moran_i=moran, moran_p=moran_p,
        incumplimientos=validar_signos(coeficientes),
    )
