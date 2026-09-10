"""Auditoria QA de los dos modelos entrenados.

Reproduce la preparacion de datos de cada notebook, recarga el paquete .joblib
guardado y comprueba que lo desplegable coincide con lo reportado. Pensado para
correrse antes de publicar la API:

    ./.venv/Scripts/python.exe qa/qa_modelos.py

No modifica nada: solo lee la base en modo `ro` y los artefactos de `modelos/`.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

FALLOS: list[str] = []
AVISOS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "", critico: bool = True) -> bool:
    marca = "OK " if ok else ("FALLA" if critico else "AVISO")
    print(f"  [{marca:^5}] {nombre}{('  ->  ' + detalle) if detalle else ''}")
    if not ok:
        (FALLOS if critico else AVISOS).append(f"{nombre}: {detalle}")
    return ok


def titulo(t: str) -> None:
    print(f"\n{'='*78}\n{t}\n{'='*78}")


# --------------------------------------------------------------------------
# 1. Consistencia de la base
# --------------------------------------------------------------------------
def auditar_base() -> pd.DataFrame:
    titulo("1. BASE DE DATOS")
    db = RAIZ / "data" / "ofertas_unificado.sqlite"
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=15) as con:
        crudo = pd.read_sql_query("SELECT * FROM ofertas", con)
        tablas = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'", con)["name"].tolist()

    print(f"  tablas: {tablas} - {len(crudo):,} filas x {crudo.shape[1]} columnas")
    check("sin id_aviso duplicado dentro de cada sitio",
          crudo.duplicated(["sitio", "id_aviso"]).sum() == 0,
          f"{crudo.duplicated(['sitio','id_aviso']).sum()} duplicados")

    csv = pd.read_csv(RAIZ / "data" / "ofertas_unificado.csv", dtype=str,
                      keep_default_na=False)
    check("el CSV espejo tiene la misma forma que el SQLite",
          csv.shape == crudo.shape, f"csv {csv.shape} vs sqlite {crudo.shape}")
    check("el CSV espejo tiene los mismos id_aviso",
          sorted(csv["id_aviso"].astype(str)) == sorted(crudo["id_aviso"].astype(str)))

    # El centinela textual tiene que seguir siendo el unico: si aparecieran NULL
    # reales, el `replace("SIN_DATO", NA)` de los notebooks los pasaria por alto.
    nulos_reales = int(crudo.isna().sum().sum())
    check("no hay NULL reales mezclados con el centinela SIN_DATO",
          nulos_reales == 0, f"{nulos_reales} NULL reales", critico=False)

    d = crudo.replace("SIN_DATO", pd.NA)
    for c in ("precio_clp", "precio_uf", "m2_util"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    ambos = d["precio_clp"].notna() & d["precio_uf"].notna() & (d["precio_uf"] > 0)
    uf = (d.loc[ambos, "precio_clp"] / d.loc[ambos, "precio_uf"])
    disp = float(uf.quantile(0.75) - uf.quantile(0.25))
    print(f"  UF empirica: mediana {uf.median():,.2f} - rango intercuartil {disp:,.2f}")
    check("la UF empirica es estable (IQR < 1% de la mediana)",
          disp < 0.01 * uf.median(), f"IQR {disp:,.2f}")
    check("la UF empirica coincide con la usada en los modelos (40.844,79)",
          abs(uf.median() - 40_844.79) < 1.0, f"{uf.median():,.2f}")

    fechas = sorted(crudo["fecha_scrape"].unique())
    print(f"  fechas de scrape: {fechas}")
    check("el dataset sigue siendo una foto corta (<= 5 fechas de scrape)",
          len(fechas) <= 5, f"{len(fechas)} fechas", critico=False)
    return crudo


# --------------------------------------------------------------------------
# 2. Reproduccion de cada notebook
# --------------------------------------------------------------------------
def preparar(notebook: str, n_celdas: int) -> dict:
    """Ejecuta las primeras celdas de codigo de un notebook y devuelve su espacio
    de nombres. Solo carga, limpia, construye features y divide: no reentrena."""
    nb = json.loads((RAIZ / notebook).read_text(encoding="utf-8"))
    celdas = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    G: dict = {"__name__": "__qa__"}
    import matplotlib
    matplotlib.use("Agg")
    import os
    cwd = os.getcwd()
    os.chdir(RAIZ)
    try:
        for i in range(n_celdas):
            exec(celdas[i], G)
    finally:
        os.chdir(cwd)
    return G


def auditar_modelo(nombre: str, notebook: str, n_celdas: int, objetivo: str,
                   unidad: str) -> dict:
    titulo(f"2. MODELO DE {nombre.upper()}")
    paquete = joblib.load(RAIZ / "modelos" / f"{nombre}.joblib")
    ficha = json.loads((RAIZ / "modelos" / f"{nombre}.json").read_text(encoding="utf-8"))

    G = preparar(notebook, n_celdas)
    X, y = G["X"], G["y"]
    i_test = G["i_test"]
    evaluar = G["evaluar"]
    X_test, y_test = X.iloc[i_test], y[i_test]

    print(f"  reproduccion: {len(X):,} filas, {len(i_test):,} en prueba")
    check("el n reproducido coincide con la ficha",
          len(X) == ficha["n_total"] and len(i_test) == ficha["n_test"],
          f"reproducido {len(X)}/{len(i_test)} vs ficha "
          f"{ficha['n_total']}/{ficha['n_test']}")

    # --- el modelo guardado reproduce las metricas publicadas -----------------
    pred = paquete["modelo"].predict(X_test)
    m = evaluar(y_test, pred)
    dif = abs(m["MdAPE"] - ficha["metricas_test"]["MdAPE"])
    print(f"  MdAPE recalculado {m['MdAPE']:.3f}% vs ficha "
          f"{ficha['metricas_test']['MdAPE']:.3f}%")
    check("el .joblib reproduce el MdAPE de la ficha", dif < 0.01, f"difiere {dif:.3f}")
    check("el .joblib reproduce el PRD de la ficha",
          abs(m["PRD"] - ficha["metricas_test"]["PRD"]) < 0.002)

    # --- antileakage ---------------------------------------------------------
    PROHIBIDAS = {"precio_uf", "precio_clp", "precio_valor", "antiguedad_aviso_dias",
                  "fecha_publicacion", "fecha_scrape", "uf_por_m2", "sitio", "url",
                  "titulo", "descripcion", "id_aviso"}
    cols = list(paquete["columnas"])
    check("ninguna columna prohibida entre las features del paquete",
          not set(cols) & PROHIBIDAS, f"{set(cols) & PROHIBIDAS}")
    check("las columnas del paquete coinciden con las del notebook",
          cols == list(G["TODAS"]))

    # El ColumnTransformer debe descartar lo no declarado: se le cuela una columna
    # con el objetivo dentro y la prediccion no puede cambiar.
    X_sucio = X_test.copy()
    X_sucio["precio_filtrado"] = y_test
    try:
        pred_sucio = paquete["modelo"].predict(X_sucio)
        check("una columna extra con el objetivo no altera la prediccion",
              np.allclose(pred, pred_sucio),
              "el remainder no esta descartando")
    except Exception as e:                                   # pragma: no cover
        check("una columna extra con el objetivo no altera la prediccion", False, str(e))

    # --- intervalo -----------------------------------------------------------
    lo = paquete["cuantil_bajo"].predict(X_test) - paquete["correccion_conforme"]
    hi = paquete["cuantil_alto"].predict(X_test) + paquete["correccion_conforme"]
    cob = 100 * np.mean((y_test >= lo) & (y_test <= hi))
    objetivo_cob = 100 * (1 - paquete["alfa"])
    print(f"  cobertura del intervalo: {cob:.1f}% (objetivo {objetivo_cob:.0f}%)")
    check("la cobertura del intervalo esta dentro de +-5 puntos del objetivo",
          abs(cob - objetivo_cob) <= 5, f"{cob:.1f}%")
    check("el intervalo nunca queda invertido ni negativo",
          bool(np.all(hi > lo) and np.all(lo >= 0)))
    # Los modelos cuantilicos se entrenan aparte del puntual, asi que nada
    # garantiza que el rango contenga a su propia estimacion. Ocurre en una
    # minoria de casos y `api.modelos` lo corrige ensanchando el rango; aqui se
    # mide cuanto pasaba en el artefacto crudo.
    coherente = float(np.mean((pred >= lo) & (pred <= hi)))
    check("el rango del artefacto crudo contiene su propia estimacion puntual",
          coherente > 0.99, f"{100*coherente:.1f}% de los casos - lo corrige la API",
          critico=False)

    # --- comportamiento monotono en superficie -------------------------------
    # No es una garantia del modelo, pero si al aumentar 20 m2 el precio baja en
    # la mayoria de los casos, algo esta mal orientado.
    base = X_test.copy()
    mas = base.copy()
    mas["m2_util"] = mas["m2_util"] + 20
    mas["log_m2_util"] = np.log(mas["m2_util"])
    mas["m2_por_dormitorio"] = mas["m2_util"] / base["dormitorios"].fillna(1).clip(lower=1)
    sube = float(np.mean(paquete["modelo"].predict(mas) > pred))
    print(f"  al sumar 20 m2 utiles el precio sube en el {100*sube:.1f}% de los casos")
    check("el precio sube con la superficie en >85% de los casos", sube > 0.85,
          f"{100*sube:.1f}%")

    # --- robustez de despliegue: entrada minima ------------------------------
    minima = pd.DataFrame([{c: np.nan for c in cols}])
    for c, v in [("m2_util", 60.0), ("log_m2_util", np.log(60)), ("dormitorios", 2.0),
                 ("banos", 1.0), ("comuna", "nunoa"), ("es_casa", 0.0),
                 ("m2_por_dormitorio", 30.0), ("densidad_banos", 0.5)]:
        if c in minima.columns:
            minima[c] = v
    try:
        p_min = float(paquete["modelo"].predict(minima[cols])[0])
        print(f"  con solo 5 campos informados predice {p_min:,.0f} {unidad}")
        check("predice con la entrada minima que tendra la API", np.isfinite(p_min))
        check("la prediccion minima cae en un rango plausible",
              (500 < p_min < 60_000) if unidad == "UF" else (150_000 < p_min < 4_000_000),
              f"{p_min:,.0f} {unidad}")
    except Exception as e:
        check("predice con la entrada minima que tendra la API", False, str(e))

    # --- comuna desconocida no debe reventar ---------------------------------
    rara = minima.copy()
    if "comuna" in rara.columns:
        rara["comuna"] = "comuna-que-no-existe"
    try:
        check("una comuna desconocida no rompe la prediccion",
              np.isfinite(float(paquete["modelo"].predict(rara[cols])[0])))
    except Exception as e:
        check("una comuna desconocida no rompe la prediccion", False, str(e))

    return {"paquete": paquete, "ficha": ficha, "G": G, "pred": pred,
            "X_test": X_test, "y_test": y_test, "metricas": m}


# --------------------------------------------------------------------------
# 3. Coherencia entre los dos modelos
# --------------------------------------------------------------------------
def auditar_cruce(venta: dict, arriendo: dict) -> None:
    titulo("3. COHERENCIA ENTRE LOS DOS MODELOS")
    cv, ca = venta["paquete"], arriendo["paquete"]

    check("ambos usan la misma UF de referencia",
          abs(cv["uf_referencia"] - ca["uf_referencia"]) < 1.0,
          f"venta {cv['uf_referencia']:,.2f} vs arriendo {ca['uf_referencia']:,.2f}")
    check("ambos usan el mismo anio de referencia",
          cv["anio_referencia"] == ca["anio_referencia"])
    check("ambos comparten el catalogo de categorias POI",
          list(cv["categorias_poi"]) == list(ca["categorias_poi"]))

    solo_arriendo = set(ca["columnas"]) - set(cv["columnas"])
    print(f"  el modelo de arriendo anade {sorted(solo_arriendo)}")
    check("las features comunes estan en el mismo orden relativo",
          [c for c in ca["columnas"] if c in set(cv["columnas"])]
          == [c for c in cv["columnas"] if c in set(ca["columnas"])],
          critico=False)

    # El yield bruto solo tiene sentido si se cruzan las MISMAS propiedades. Se
    # usan las de venta que ademas tienen geo, estimando su arriendo con el otro
    # modelo: no es validacion (nadie publica la misma unidad en venta y arriendo)
    # sino un chequeo de que el orden de magnitud del cruce es creible.
    Xv = venta["X_test"]
    cols_a = list(ca["columnas"])
    faltan = [c for c in cols_a if c not in Xv.columns]
    Xv_a = Xv.copy()
    for c in faltan:
        Xv_a[c] = 0.0 if c in ("sin_geo", "sin_servicios") else np.nan
    arr = ca["modelo"].predict(Xv_a[cols_a])
    precio_clp = venta["pred"] * cv["uf_referencia"]
    yield_bruto = 100 * (arr * 12) / precio_clp
    q = np.percentile(yield_bruto, [5, 25, 50, 75, 95])
    print(f"  yield bruto anual implicito: p5 {q[0]:.2f}% - mediana {q[2]:.2f}% - "
          f"p95 {q[4]:.2f}%")
    check("el yield bruto mediano cae en el rango plausible de Santiago (3%-7%)",
          3.0 <= q[2] <= 7.0, f"mediana {q[2]:.2f}%")
    check("menos del 5% de los cruces da un yield absurdo (>12% o <1%)",
          float(np.mean((yield_bruto > 12) | (yield_bruto < 1))) < 0.05,
          f"{100*np.mean((yield_bruto > 12) | (yield_bruto < 1)):.1f}%", critico=False)


# --------------------------------------------------------------------------
# 4. Riesgos de despliegue
# --------------------------------------------------------------------------
def auditar_despliegue(venta: dict, arriendo: dict) -> None:
    titulo("4. DESPLIEGUE")
    import sklearn
    print(f"  entorno actual: python {sys.version.split()[0]} - "
          f"scikit-learn {sklearn.__version__}")
    try:
        import xgboost
        print(f"  xgboost {xgboost.__version__}")
    except ImportError:
        pass

    for nombre, d in (("venta", venta), ("arriendo", arriendo)):
        ruta = RAIZ / "modelos" / f"{nombre}.joblib"
        mb = ruta.stat().st_size / 1e6
        print(f"  {nombre}.joblib: {mb:.1f} MB - algoritmo {d['ficha']['algoritmo']}")
        check(f"{nombre}.joblib cabe holgado en un contenedor pequeno (<200 MB)",
              mb < 200, f"{mb:.1f} MB")

    # El riesgo real: la construccion de features vive en los notebooks, no en el
    # paquete. Si la API la reimplementa a mano, cualquier diferencia silenciosa
    # (un log1p que falta, un orden distinto) degrada la prediccion sin avisar.
    hay_modulo = (RAIZ / "api" / "features.py").exists()
    check("existe un modulo compartido de features para la API", hay_modulo,
          "" if hay_modulo else "sin el, la API reimplementaria construir_features() "
          "a mano y cualquier divergencia degradaria la prediccion en silencio",
          critico=False)


# --------------------------------------------------------------------------
# 5. Paridad entre el modulo compartido y los notebooks
# --------------------------------------------------------------------------
def auditar_paridad(venta: dict, arriendo: dict) -> None:
    titulo("5. PARIDAD api/features.py CONTRA LOS NOTEBOOKS")
    from api.features import construir_features as api_construir

    for nombre, d in (("venta", venta), ("arriendo", arriendo)):
        G = d["G"]
        # `datos` es el DataFrame que el notebook construyo con SU propia
        # funcion; se rehace con la del modulo compartido y se comparan columna
        # a columna. Cualquier divergencia degradaria la API en silencio.
        crudo_nb = G["df"]
        rehecho = api_construir(crudo_nb, anio=d["paquete"]["anio_referencia"])
        cols = list(d["paquete"]["columnas"])
        a = G["datos"].reset_index(drop=True)[cols]
        b = rehecho.reset_index(drop=True)[cols]

        distintas = []
        for c in cols:
            sa, sb = a[c], b[c]
            if sa.dtype.kind in "biufc" and sb.dtype.kind in "biufc":
                if not np.allclose(sa.to_numpy(float), sb.to_numpy(float),
                                   equal_nan=True):
                    distintas.append(c)
            elif not sa.astype(str).equals(sb.astype(str)):
                distintas.append(c)
        check(f"[{nombre}] las {len(cols)} features del modulo coinciden con el notebook",
              not distintas, f"difieren {distintas}")

        # Y lo que de verdad importa: que la prediccion no cambie.
        p1 = d["paquete"]["modelo"].predict(a.iloc[d["G"]["i_test"][:300]])
        p2 = d["paquete"]["modelo"].predict(b.iloc[d["G"]["i_test"][:300]])
        check(f"[{nombre}] la prediccion es identica con las features del modulo",
              bool(np.allclose(p1, p2)))


# --------------------------------------------------------------------------
# 6. La API
# --------------------------------------------------------------------------
def auditar_api(venta: dict, arriendo: dict) -> None:
    titulo("6. API")
    try:
        from fastapi.testclient import TestClient

        from api.main import app
    except ImportError as e:
        check("fastapi disponible para probar la API", False, str(e), critico=False)
        return

    c = TestClient(app)
    check("GET /salud responde 200", c.get("/salud").status_code == 200)
    check("GET /modelos/venta devuelve la ficha",
          c.get("/modelos/venta").json().get("operacion") == "venta")
    check("un modelo inexistente da 404", c.get("/modelos/foo").status_code == 404)

    # Coherencia del rango sobre propiedades reales del conjunto de prueba: es
    # el defecto que la seccion 2 detecta en el artefacto crudo.
    filas = arriendo["G"]["datos"].iloc[arriendo["G"]["i_test"]].head(120)
    campos = ["m2_util", "m2_total", "dormitorios", "banos", "estacionamientos",
              "bodegas", "ano_construccion", "gastos_comunes_clp", "lat", "lon",
              "comuna", "tipo", "servicios_cercanos"]
    incoherentes = 0
    for _, p in filas.iterrows():
        at = {k: (None if pd.isna(p[k]) else p[k]) for k in campos}
        at["m2_util"] = float(p["m2_util"])
        r = c.post("/estimar", json={"propiedad": at})
        if r.status_code != 200:
            check("POST /estimar responde 200", False, r.text[:200])
            return
        for op in ("venta", "arriendo"):
            d = r.json()[op]
            if not (d["rango"][0] <= d["valor"] <= d["rango"][1]):
                incoherentes += 1
    check("la API nunca devuelve un rango que excluya su estimacion",
          incoherentes == 0, f"{incoherentes} casos de {2*len(filas)}")

    # La comuna tiene que dar igual escrita como venga.
    base = {"m2_util": 70.0, "tipo": "departamento", "dormitorios": 2, "banos": 2,
            "lat": -33.4569, "lon": -70.6011}
    v1 = c.post("/estimar", json={"propiedad": {**base, "comuna": "nunoa"}}).json()
    v2 = c.post("/estimar", json={"propiedad": {**base, "comuna": "Ñuñoa"}}).json()
    check("'Nunoa' y 'nunoa' dan la misma estimacion",
          v1["venta"]["valor"] == v2["venta"]["valor"],
          f"{v1['venta']['valor']} vs {v2['venta']['valor']}")

    # Las advertencias viajan siempre con la estimacion.
    check("la estimacion declara los limites del modelo",
          len(v1["advertencias"]) >= 2, str(v1.get("advertencias"))[:120])


def main() -> int:
    crudo = auditar_base()
    venta = auditar_modelo("venta", "modelo_venta.ipynb", 5, "precio_uf", "UF")
    arriendo = auditar_modelo("arriendo", "modelo_arriendo.ipynb", 6, "precio_clp", "CLP")
    auditar_cruce(venta, arriendo)
    auditar_paridad(venta, arriendo)
    auditar_api(venta, arriendo)
    auditar_despliegue(venta, arriendo)

    titulo("RESUMEN")
    print(f"  fallos criticos : {len(FALLOS)}")
    for f in FALLOS:
        print(f"     - {f}")
    print(f"  avisos          : {len(AVISOS)}")
    for a in AVISOS:
        print(f"     - {a}")
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
