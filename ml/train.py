"""CLI de entrenamiento y comparacion de modelos.

    python -m ml.train --operacion venta --tipo departamento --modelos todos --cv ambos

Compara todos los modelos con el mismo split y las mismas metricas, en los tres
esquemas de validacion, y guarda un artefacto JSON con todo lo necesario para
reproducir el resultado.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import baseline, config, data, features, metrics, models, validation

ESQUEMAS_CLI = {
    "espacial": ["espacial"],
    "aleatorio": ["aleatorio"],
    "ambos": ["aleatorio", "espacial"],
    "todos": ["aleatorio", "espacial", "espacial_estricto"],
}


@dataclass
class ResultadoModelo:
    modelo: str
    esquema: str
    metricas: dict
    segundos: float
    hiperparametros: dict = field(default_factory=dict)
    por_fold: list = field(default_factory=list)


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5,
                              check=True).stdout.strip()
    except Exception:
        return None


def _versiones() -> dict:
    import sklearn
    vers = {"python": platform.python_version(), "pandas": pd.__version__,
            "numpy": np.__version__, "scikit_learn": sklearn.__version__,
            "shap": None}
    for paquete in ("lightgbm", "xgboost", "statsmodels"):
        try:
            vers[paquete] = __import__(paquete).__version__
        except Exception:
            vers[paquete] = None
    return vers


def evaluar_modelo(nombre: str, df: pd.DataFrame, X: pd.DataFrame, y: np.ndarray,
                   espec: features.EspecFeatures, esquema: str, *,
                   operacion: str, n_splits: int, semilla: int,
                   verificar: bool = True) -> ResultadoModelo:
    """Validacion cruzada con predicciones fuera de fold agrupadas.

    Las metricas se calculan sobre el conjunto de predicciones out-of-fold, no
    promediando las de cada fold: la mediana de las medianas no es la mediana.
    """
    inicio = time.perf_counter()
    pred = np.full(len(y), np.nan)
    por_fold = []

    for i, (train, test) in enumerate(validation.particiones(
            df, y, esquema, n_splits=n_splits, semilla=semilla)):
        if verificar and esquema != "aleatorio":
            validation.verificar_disyuncion(df, train, test)
        modelo = models.construir(nombre, espec, semilla=semilla)
        modelo.fit(X.iloc[train], y[train])
        p = modelo.predict(X.iloc[test])
        pred[test] = p
        por_fold.append({"fold": i, "n_test": int(len(test)),
                         "mdape": metrics.mdape(y[test], p),
                         "ppe10": metrics.ppe(y[test], p)})

    evaluadas = ~np.isnan(pred)
    tabla = metrics.tabla_metricas(y[evaluadas], pred[evaluadas], operacion=operacion)
    return ResultadoModelo(nombre, esquema, tabla, time.perf_counter() - inicio,
                           por_fold=por_fold)


def _tabla_comparativa(resultados: list[ResultadoModelo]) -> str:
    cab = (f"{'modelo':<16}{'esquema':<20}{'n':>7}{'MdAPE':>8}{'PPE10':>8}{'PPE20':>8}"
           f"{'COD':>8}{'PRD':>8}{'PRB':>8}{'R2':>8}{'seg':>7}")
    lineas = [cab, "-" * len(cab)]
    for r in sorted(resultados, key=lambda r: (r.esquema, r.metricas["mdape"])):
        m = r.metricas
        lineas.append(
            f"{r.modelo:<16}{r.esquema:<20}{m['n']:>7,}{m['mdape']:>8.2f}"
            f"{m['ppe10']:>8.1f}{m['ppe20']:>8.1f}{m['cod']:>8.2f}{m['prd']:>8.3f}"
            f"{m['prb']:>8.3f}{m['r2']:>8.3f}{r.segundos:>7.1f}")
    return "\n".join(lineas)


def _chequeos_de_sanidad(resultados: list[ResultadoModelo], operacion: str) -> list[str]:
    """Lista de sanidad de PLAN_MODELO_ML.md seccion 7."""
    avisos = []
    por_esquema = {}
    for r in resultados:
        por_esquema.setdefault(r.esquema, []).append(r)

    for esquema, grupo in por_esquema.items():
        for r in grupo:
            if r.metricas["mdape"] < config.MDAPE_SOSPECHOSO:
                avisos.append(
                    f"SOSPECHA DE LEAKAGE: {r.modelo}/{esquema} tiene MdAPE "
                    f"{r.metricas['mdape']:.2f}% (< {config.MDAPE_SOSPECHOSO}%). "
                    "Auditar antes de dar el resultado por bueno.")

    if {"aleatorio", "espacial"} <= set(por_esquema):
        mejor = {e: min(g, key=lambda r: r.metricas["mdape"])
                 for e, g in por_esquema.items()}
        delta = mejor["espacial"].metricas["mdape"] - mejor["aleatorio"].metricas["mdape"]
        if delta < 0:
            avisos.append(
                f"EL SPLIT ESPACIAL DA MEJOR QUE EL ALEATORIO (delta {delta:+.2f} pts). "
                "Debe ser al reves: revisar la clave de agrupacion, hay un bug.")

    for r in resultados:
        if not metrics.cumple_iaao(r.metricas)["prd"]:
            avisos.append(
                f"{r.modelo}/{r.esquema}: PRD {r.metricas['prd']:.3f} fuera de "
                f"{config.IAAO_PRD} (sesgo sistematico por rango de precio).")

    meta = config.META_MDAPE_VENTA if operacion == "venta" else config.META_MDAPE_ARRIENDO
    espaciales = por_esquema.get("espacial", [])
    if espaciales:
        mejor_esp = min(espaciales, key=lambda r: r.metricas["mdape"])
        if mejor_esp.metricas["mdape"] > meta:
            avisos.append(
                f"El mejor MdAPE espacial ({mejor_esp.metricas['mdape']:.2f}%) no "
                f"alcanza la meta de {meta}% para {operacion}.")
    return avisos


def _diagnostico(df: pd.DataFrame, y: np.ndarray, X: pd.DataFrame,
                 espec: features.EspecFeatures, nombre: str, *,
                 n_splits: int, semilla: int) -> dict:
    """Error por comuna y por origen del precio, sobre predicciones out-of-fold."""
    pred = np.full(len(y), np.nan)
    for train, test in validation.particiones(df, y, "espacial",
                                              n_splits=n_splits, semilla=semilla):
        modelo = models.construir(nombre, espec, semilla=semilla)
        modelo.fit(X.iloc[train], y[train])
        pred[test] = modelo.predict(X.iloc[test])

    ok = ~np.isnan(pred)
    diag = {}
    for columna, clave in (("comuna", "por_comuna"), ("precio_origen", "por_precio_origen")):
        if columna in df.columns:
            tabla = metrics.metricas_por_grupo(y[ok], pred[ok],
                                               df.loc[ok, columna].to_numpy())
            diag[clave] = tabla.to_dict("records")
    return diag


def entrenar(args: argparse.Namespace) -> dict:
    print(f"\n{'=' * 78}\nSEGMENTO: {args.operacion} / {args.tipo}\n{'=' * 78}")

    df, informe = data.cargar_segmento(
        args.operacion, args.tipo, db_path=args.db, uf_online=args.uf_online,
        con_recorte_final=not args.sin_recorte_final)
    print(informe.como_tabla())
    print(f"\nUF usada: {informe.reparacion.uf_usada:,.2f} "
          f"({informe.reparacion.procedencia}) | "
          f"reconstruidas CLP->UF {informe.reparacion.clp_a_uf:,} / "
          f"UF->CLP {informe.reparacion.uf_a_clp:,}")

    espec = features.espec_features(args.operacion, args.tipo,
                                    incluir_sitio=args.incluir_sitio)
    X_todo = features.preparar_matriz(df, espec)
    y_todo = df[config.TARGET[args.operacion]].to_numpy(dtype=float)

    # Holdout externo: se aparta ANTES de mirar nada y no se toca hasta el
    # ultimo paso. La validacion cruzada ya da metricas fuera de muestra, pero
    # esas mismas metricas se usan para elegir el ganador (y para el tuning),
    # y elegir sobre una medicion la contamina como estimador de error futuro.
    df_hold = X_hold = y_hold = None
    if args.holdout > 0:
        idx_dev, idx_hold = validation.separar_holdout(
            df, fraccion=args.holdout, semilla=args.semilla)
        df_hold = df.iloc[idx_hold].reset_index(drop=True)
        X_hold, y_hold = X_todo.iloc[idx_hold], y_todo[idx_hold]
        df = df.iloc[idx_dev].reset_index(drop=True)
        X, y = X_todo.iloc[idx_dev].reset_index(drop=True), y_todo[idx_dev]
        print(f"\nHoldout externo apartado por grupos espaciales: "
              f"{len(idx_hold):,} filas ({100 * len(idx_hold) / len(X_todo):.1f}%). "
              f"Desarrollo: {len(idx_dev):,}. No se toca hasta el final.")
    else:
        X, y = X_todo, y_todo

    resumen = validation.resumen_grupos(validation.clave_espacial(df))
    print(f"\nEstructura espacial ({config.GEO_DECIMALES} decimales): "
          f"{resumen.n_grupos:,} grupos | "
          f"{resumen.pct_filas_en_grupo_multiple:.1f}% de las filas comparte grupo | "
          f"grupo mayor {resumen.grupo_maximo} | fuentes {resumen.por_fuente}")

    print(f"\n{'-' * 78}\nBASELINE HEDONICO\n{'-' * 78}")
    try:
        res_baseline = baseline.ajustar(df, args.operacion, con_moran=not args.sin_moran)
        print(res_baseline.como_tabla())
        baseline_dict = res_baseline.a_dict()
    except ValueError as e:
        print(f"no se pudo ajustar el baseline: {e}")
        baseline_dict = {"error": str(e)}

    nombres = models.resolver(args.modelos)
    esquemas = ESQUEMAS_CLI[args.cv]
    print(f"\n{'-' * 78}\nMODELOS: {', '.join(nombres)}\n"
          f"ESQUEMAS: {', '.join(esquemas)}  ({args.folds} folds, semilla {args.semilla})"
          f"\n{'-' * 78}")

    resultados: list[ResultadoModelo] = []
    for esquema in esquemas:
        for nombre in nombres:
            r = evaluar_modelo(nombre, df, X, y, espec, esquema,
                               operacion=args.operacion, n_splits=args.folds,
                               semilla=args.semilla)
            resultados.append(r)
            print(f"  {nombre:<16}{esquema:<20}MdAPE {r.metricas['mdape']:6.2f}  "
                  f"PPE10 {r.metricas['ppe10']:5.1f}  [{r.segundos:.1f}s]")

    print(f"\n{'=' * 78}\nCOMPARATIVA\n{'=' * 78}")
    print(_tabla_comparativa(resultados))

    referencia = "espacial" if "espacial" in esquemas else esquemas[0]
    candidatos = [r for r in resultados if r.esquema == referencia]
    ganador = min(candidatos, key=lambda r: r.metricas["mdape"])
    print(f"\nGanador ({referencia}): {ganador.modelo} con MdAPE "
          f"{ganador.metricas['mdape']:.2f}% y PPE10 {ganador.metricas['ppe10']:.1f}%")

    delta = None
    if {"aleatorio", "espacial"} <= set(esquemas):
        mejor_ale = min((r for r in resultados if r.esquema == "aleatorio"),
                        key=lambda r: r.metricas["mdape"])
        delta = ganador.metricas["mdape"] - mejor_ale.metricas["mdape"]
        print(f"Brecha espacial - aleatorio: {delta:+.2f} puntos de MdAPE "
              f"(el split aleatorio infla el resultado en esa magnitud)")

    print(f"\n{'-' * 78}\nDIAGNOSTICO DEL GANADOR\n{'-' * 78}")
    diag = _diagnostico(df, y, X, espec, ganador.modelo,
                        n_splits=args.folds, semilla=args.semilla)
    for clave, titulo in (("por_comuna", "Error por comuna"),
                          ("por_precio_origen", "Error por origen del precio")):
        if diag.get(clave):
            print(f"\n{titulo}:")
            print(pd.DataFrame(diag[clave]).to_string(index=False))

    # Evaluacion final sobre el holdout. Se toca UNA sola vez, con el ganador
    # reentrenado sobre todo el desarrollo. Es el estimador honesto del error
    # que tendria el modelo con propiedades de edificios que nunca vio.
    holdout_dict = None
    if df_hold is not None:
        modelo_final = models.construir(ganador.modelo, espec, semilla=args.semilla)
        modelo_final.fit(X, y)
        pred_hold = modelo_final.predict(X_hold)
        m_hold = metrics.tabla_metricas(y_hold, pred_hold, operacion=args.operacion)
        brecha = m_hold["mdape"] - ganador.metricas["mdape"]
        holdout_dict = {
            "fraccion": args.holdout, "modelo": ganador.modelo,
            "metricas": m_hold,
            "mdape_cv": ganador.metricas["mdape"],
            "brecha_holdout_cv": brecha,
        }
        print(f"\n{'-' * 78}\nHOLDOUT EXTERNO (nunca visto, evaluado una sola vez)"
              f"\n{'-' * 78}")
        print(f"  {'':<22}{'CV espacial':>14}{'Holdout':>12}")
        for clave, etiqueta in (("mdape", "MdAPE"), ("ppe10", "PPE10"),
                                ("cod", "COD"), ("prd", "PRD")):
            print(f"  {etiqueta:<22}{ganador.metricas[clave]:>14.2f}"
                  f"{m_hold[clave]:>12.2f}")
        print(f"  {'n':<22}{ganador.metricas['n']:>14,}{m_hold['n']:>12,}")
        if abs(brecha) < 1.0:
            print(f"\n  Brecha de {brecha:+.2f} puntos: la CV NO estaba siendo "
                  "optimista de forma\n  apreciable. El error reportado se sostiene "
                  "sobre datos completamente\n  nuevos.")
        else:
            print(f"\n  [!] Brecha de {brecha:+.2f} puntos entre la CV y el holdout. "
                  "La seleccion\n      del ganador sobre la CV la volvio optimista: "
                  "reportar la cifra del holdout.")

    avisos = _chequeos_de_sanidad(resultados, args.operacion)
    print(f"\n{'-' * 78}\nCHEQUEOS DE SANIDAD\n{'-' * 78}")
    if avisos:
        for a in avisos:
            print(f"  [!] {a}")
    else:
        print("  Todos los chequeos pasan.")

    artefacto = {
        "version_artefacto": "1",
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "git_commit": _commit(),
        "operacion": args.operacion, "tipo": args.tipo, "semilla": args.semilla,
        "entorno": _versiones(),
        "datos": informe.a_dict(),
        "features": espec.a_dict() | {
            "excluidas_por_leakage": sorted(config.COLUMNAS_PROHIBIDAS)},
        "validacion": {"esquemas": esquemas, "folds": args.folds,
                       "geo_decimales": config.GEO_DECIMALES,
                       "grupos": resumen.a_dict()},
        "baseline": baseline_dict,
        "resultados": [asdict(r) for r in resultados],
        "ganador": ganador.modelo,
        "holdout": holdout_dict,
        "diagnostico": diag | {"delta_espacial_aleatorio": delta},
        "chequeos_de_sanidad": avisos,
        "sesgos_declarados": config.SESGOS_DECLARADOS,
    }

    if not args.no_guardar:
        config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        sufijo = f"_{args.etiqueta}" if args.etiqueta else ""
        marca = datetime.now().strftime("%Y%m%d-%H%M")
        ruta = config.ARTIFACTS_DIR / f"{args.operacion}_{args.tipo}_{marca}{sufijo}.json"
        ruta.write_text(json.dumps(artefacto, indent=2, ensure_ascii=False,
                                   default=str), encoding="utf-8")
        print(f"\nArtefacto: {ruta}")

        if args.guardar_modelo:
            import joblib
            # Se reentrena con todas las filas, holdout incluido: una vez que
            # el holdout ya cumplio su funcion de medir, retenerlo solo resta datos.
            final = models.construir(ganador.modelo, espec, semilla=args.semilla)
            final.fit(X_todo, y_todo)
            destino = ruta.with_suffix(".joblib")
            joblib.dump({"modelo": final, "espec": espec,
                         "operacion": args.operacion, "tipo": args.tipo}, destino)
            print(f"Modelo:    {destino}")

    return artefacto


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ml.train",
        description="Entrena y compara modelos hedonicos de valoracion inmobiliaria.")
    p.add_argument("--operacion", required=True, choices=list(config.OPERACIONES))
    p.add_argument("--tipo", default="todos", choices=[*config.TIPOS, "todos"])
    p.add_argument("--modelos", default="todos",
                   help="'todos' o lista separada por comas (ej: lightgbm,ridge)")
    p.add_argument("--cv", default="ambos", choices=list(ESQUEMAS_CLI))
    p.add_argument("--folds", type=int, default=config.CV_N_SPLITS)
    p.add_argument("--holdout", type=float, default=0.0, metavar="FRACCION",
                   help="aparta esta fraccion por grupos espaciales y la evalua "
                        "una sola vez al final (ej: 0.2). 0 = desactivado")
    p.add_argument("--semilla", type=int, default=config.RANDOM_STATE)
    p.add_argument("--db", default=config.DB_PATH, type=Path)
    p.add_argument("--etiqueta", default="", help="sufijo del archivo de artefacto")
    p.add_argument("--incluir-sitio", action="store_true",
                   help="corrida diagnostica: mide el sesgo de fuente (no desplegable)")
    p.add_argument("--uf-online", action="store_true",
                   help="consulta mindicador.cl en vez de usar la UF implicita")
    p.add_argument("--sin-recorte-final", action="store_true",
                   help="desactiva el recorte p1-p99 de precio/m2 (control de riesgo)")
    p.add_argument("--sin-moran", action="store_true",
                   help="omite la I de Moran del baseline (es lo mas lento)")
    p.add_argument("--guardar-modelo", action="store_true",
                   help="serializa el ganador reentrenado con todas las filas")
    p.add_argument("--no-guardar", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    entrenar(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
