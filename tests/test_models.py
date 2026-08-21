"""Registro de modelos y CLI de entrenamiento."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import config, features, metrics, models, train, validation


@pytest.fixture
def datos_sinteticos():
    """log(precio) = 6 + 0,9*log(m2) + 0,3*[nunoa] - 0,01*antiguedad + ruido.

    Con una senal tan clara, cualquier modelo razonable debe recuperarla; si no,
    el pipeline esta roto.
    """
    rng = np.random.default_rng(42)
    n = 400
    m2 = rng.uniform(30, 150, n)
    comuna = rng.choice(["nunoa", "macul"], n)
    ano = rng.integers(1970, 2025, n).astype(float)
    log_precio = (6.0 + 0.9 * np.log(m2) + 0.3 * (comuna == "nunoa")
                  - 0.01 * (config.ANIO_REFERENCIA - ano) + rng.normal(0, 0.08, n))
    df = pd.DataFrame({
        "m2_util": m2, "m2_total": m2 * rng.uniform(1.0, 1.3, n),
        "dormitorios": rng.integers(1, 4, n).astype(float),
        "banos": rng.integers(1, 3, n).astype(float),
        "estacionamientos": rng.choice([np.nan, 0.0, 1.0], n),
        "bodegas": rng.choice([np.nan, 0.0, 1.0], n),
        "gastos_comunes_clp": rng.uniform(40_000, 200_000, n),
        "lat": rng.uniform(-33.60, -33.42, n), "lon": rng.uniform(-70.70, -70.50, n),
        "ano_construccion": ano, "comuna": comuna, "tipo": ["departamento"] * n,
        "barrio": rng.choice(["a", "b", "c", "d", "e"], n),
        "direccion": [f"Calle {i}" for i in range(n)],
        "precio_uf": np.exp(log_precio),
    })
    espec = features.espec_features("venta", "departamento")
    return df, features.preparar_matriz(df, espec), df["precio_uf"].to_numpy(), espec


class TestRegistro:
    def test_hay_modelos_disponibles(self):
        assert len(models.modelos_disponibles()) >= 3

    def test_todos_los_del_registro_declaran_familia_valida(self):
        for espec in models.REGISTRO.values():
            assert espec.familia in ("lineal", "arbol_nan", "arbol_imputa")

    def test_resolver_todos(self):
        assert models.resolver("todos") == models.modelos_disponibles()

    def test_resolver_lista_separada_por_comas(self):
        assert models.resolver("ridge,hist_gradient") == ["ridge", "hist_gradient"]

    def test_resolver_modelo_desconocido(self):
        with pytest.raises(ValueError, match="modelos desconocidos"):
            models.resolver("red_neuronal_profunda")

    def test_los_modelos_con_shap_nativo_son_los_de_boosting(self):
        """Sin la libreria shap, TreeSHAP sale del booster de estos dos."""
        nativos = {n for n, e in models.REGISTRO.items() if e.shap_nativo}
        assert nativos == {"lightgbm", "xgboost"}

    def test_cada_espacio_de_busqueda_usa_el_prefijo_del_pipeline(self):
        for nombre, espec in models.REGISTRO.items():
            for clave in espec.espacio:
                assert clave.startswith("regressor__modelo__"), f"{nombre}: {clave}"


class TestConstruccion:
    def test_predice_en_escala_original_no_en_log(self, datos_sinteticos):
        """La garantia del TransformedTargetRegressor."""
        df, X, y, espec = datos_sinteticos
        modelo = models.construir("ridge", espec).fit(X, y)
        pred = modelo.predict(X)
        assert pred.shape == y.shape
        assert np.isfinite(pred).all()
        assert pred.min() > 100          # en UF, no en logaritmos
        assert 0.5 < np.median(pred) / np.median(y) < 2.0

    @pytest.mark.parametrize("nombre", ["ridge", "hist_gradient", "random_forest"])
    def test_recupera_una_senal_conocida(self, datos_sinteticos, nombre):
        df, X, y, espec = datos_sinteticos
        modelo = models.construir(nombre, espec).fit(X, y)
        assert metrics.r2(y, modelo.predict(X)) > 0.8

    def test_es_reproducible_con_la_misma_semilla(self, datos_sinteticos):
        df, X, y, espec = datos_sinteticos
        a = models.construir("hist_gradient", espec, semilla=42).fit(X, y).predict(X)
        b = models.construir("hist_gradient", espec, semilla=42).fit(X, y).predict(X)
        assert np.array_equal(a, b)

    def test_las_predicciones_son_siempre_positivas(self, datos_sinteticos):
        """exp() nunca da negativos: un precio negativo seria imposible."""
        df, X, y, espec = datos_sinteticos
        for nombre in ("ridge", "hist_gradient"):
            assert (models.construir(nombre, espec).fit(X, y).predict(X) > 0).all()

    @pytest.mark.slow
    @pytest.mark.parametrize("nombre", ["lightgbm", "xgboost"])
    def test_los_modelos_de_boosting_entrenan(self, datos_sinteticos, nombre):
        if nombre not in models.modelos_disponibles():
            pytest.skip(f"{nombre} no instalado")
        df, X, y, espec = datos_sinteticos
        pred = models.construir(nombre, espec).fit(X, y).predict(X)
        assert np.isfinite(pred).all() and (pred > 0).all()


class TestEvaluacion:
    def test_evaluar_modelo_devuelve_metricas_en_escala_original(self, datos_sinteticos):
        df, X, y, espec = datos_sinteticos
        r = train.evaluar_modelo("ridge", df, X, y, espec, "espacial",
                                 operacion="venta", n_splits=3, semilla=42)
        assert r.metricas["mdape"] > 0
        assert r.metricas["n"] == len(y)
        assert len(r.por_fold) == 3

    def test_evaluar_verifica_la_disyuncion_de_grupos(self, datos_sinteticos):
        """Si un edificio cruzara train y test, evaluar_modelo aborta."""
        df, X, y, espec = datos_sinteticos
        # Todas las filas en la misma coordenada: un solo grupo, no hay split posible.
        df_colapsado = df.assign(lat=-33.45, lon=-70.60,
                                 direccion="misma", barrio="unico")
        with pytest.raises(ValueError, match="grupos espaciales"):
            train.evaluar_modelo("ridge", df_colapsado, X, y, espec, "espacial",
                                 operacion="venta", n_splits=3, semilla=42)

    def test_el_esquema_espacial_no_es_mejor_que_el_aleatorio(self, datos_sinteticos):
        """En datos sin estructura de edificio la diferencia debe ser pequena."""
        df, X, y, espec = datos_sinteticos
        kw = dict(operacion="venta", n_splits=3, semilla=42)
        ale = train.evaluar_modelo("ridge", df, X, y, espec, "aleatorio", **kw)
        esp = train.evaluar_modelo("ridge", df, X, y, espec, "espacial", **kw)
        assert abs(esp.metricas["mdape"] - ale.metricas["mdape"]) < 5.0


class TestChequeosDeSanidad:
    def _resultado(self, modelo, esquema, **m):
        base = {"n": 100, "mdape": 12.0, "ppe10": 55.0, "ppe20": 80.0, "cod": 12.0,
                "prd": 1.0, "prb": 0.0, "r2": 0.85}
        return train.ResultadoModelo(modelo, esquema, base | m, 1.0)

    def test_detecta_mdape_sospechosamente_bajo(self):
        avisos = train._chequeos_de_sanidad(
            [self._resultado("lightgbm", "espacial", mdape=2.0)], "venta")
        assert any("LEAKAGE" in a for a in avisos)

    def test_detecta_que_el_espacial_supere_al_aleatorio(self):
        """Es la alerta que descubre un bug en la clave de agrupacion."""
        avisos = train._chequeos_de_sanidad([
            self._resultado("m", "aleatorio", mdape=15.0),
            self._resultado("m", "espacial", mdape=11.0),
        ], "venta")
        assert any("MEJOR QUE EL ALEATORIO" in a for a in avisos)

    def test_no_alerta_cuando_el_espacial_es_peor(self):
        avisos = train._chequeos_de_sanidad([
            self._resultado("m", "aleatorio", mdape=11.0),
            self._resultado("m", "espacial", mdape=14.0),
        ], "venta")
        assert not any("MEJOR QUE EL ALEATORIO" in a for a in avisos)

    def test_detecta_prd_fuera_del_rango_iaao(self):
        avisos = train._chequeos_de_sanidad(
            [self._resultado("m", "espacial", prd=1.12)], "venta")
        assert any("PRD" in a for a in avisos)

    def test_avisa_si_no_se_alcanza_la_meta(self):
        avisos = train._chequeos_de_sanidad(
            [self._resultado("m", "espacial", mdape=28.0)], "venta")
        assert any("no" in a and "meta" in a for a in avisos)

    def test_un_resultado_sano_no_genera_avisos(self):
        avisos = train._chequeos_de_sanidad([
            self._resultado("m", "aleatorio", mdape=11.0),
            self._resultado("m", "espacial", mdape=13.0),
        ], "venta")
        assert avisos == []


class TestCLI:
    def test_parsea_los_argumentos_minimos(self):
        args = train.construir_parser().parse_args(["--operacion", "venta"])
        assert args.operacion == "venta" and args.tipo == "todos"
        assert args.cv == "ambos" and args.semilla == config.RANDOM_STATE

    def test_rechaza_una_operacion_invalida(self):
        with pytest.raises(SystemExit):
            train.construir_parser().parse_args(["--operacion", "permuta"])

    def test_operacion_es_obligatoria(self):
        with pytest.raises(SystemExit):
            train.construir_parser().parse_args([])

    @pytest.mark.parametrize("cv", list(train.ESQUEMAS_CLI))
    def test_todos_los_esquemas_del_cli_son_validos(self, cv):
        for esquema in train.ESQUEMAS_CLI[cv]:
            assert esquema in validation.ESQUEMAS

    def test_las_banderas_de_control_existen(self):
        """--sin-recorte-final controla el riesgo del filtro que usa el target."""
        args = train.construir_parser().parse_args(
            ["--operacion", "venta", "--sin-recorte-final", "--incluir-sitio"])
        assert args.sin_recorte_final and args.incluir_sitio


@pytest.mark.necesita_db
@pytest.mark.slow
class TestEntrenamientoReal:
    def test_corrida_completa_sobre_el_dataset(self, tmp_path):
        if not config.DB_PATH.exists():
            pytest.skip("no esta data/ofertas_unificado.sqlite")
        args = train.construir_parser().parse_args([
            "--operacion", "venta", "--tipo", "departamento",
            "--modelos", "ridge", "--cv", "ambos", "--folds", "3",
            "--sin-moran", "--no-guardar"])
        artefacto = train.entrenar(args)

        assert artefacto["ganador"] == "ridge"
        assert artefacto["datos"]["filas_finales"] > 5_000
        assert artefacto["baseline"]["signos_incumplidos"] == []
        assert len(artefacto["sesgos_declarados"]) == 5
        # El artefacto debe bastar para reproducir la corrida.
        assert artefacto["semilla"] == 42
        assert artefacto["entorno"]["shap"] is None
        assert artefacto["datos"]["reparacion"]["clp_a_uf"] > 0


class TestCLIHoldout:
    def test_holdout_desactivado_por_defecto(self):
        args = train.construir_parser().parse_args(["--operacion", "venta"])
        assert args.holdout == 0.0

    def test_acepta_la_fraccion(self):
        args = train.construir_parser().parse_args(
            ["--operacion", "venta", "--holdout", "0.2"])
        assert args.holdout == pytest.approx(0.2)

    @pytest.mark.necesita_db
    @pytest.mark.slow
    def test_el_holdout_se_evalua_y_se_guarda_en_el_artefacto(self):
        if not config.DB_PATH.exists():
            pytest.skip("no esta data/ofertas_unificado.sqlite")
        args = train.construir_parser().parse_args([
            "--operacion", "venta", "--tipo", "departamento", "--modelos", "ridge",
            "--cv", "espacial", "--folds", "3", "--holdout", "0.2",
            "--sin-moran", "--no-guardar"])
        art = train.entrenar(args)

        h = art["holdout"]
        assert h is not None
        assert h["fraccion"] == pytest.approx(0.2)
        # El holdout se evalua sobre filas que NO entraron en la CV.
        assert h["metricas"]["n"] < art["resultados"][0]["metricas"]["n"]
        assert h["metricas"]["mdape"] > 0
        assert "brecha_holdout_cv" in h

    @pytest.mark.necesita_db
    def test_sin_holdout_el_artefacto_lo_deja_nulo(self):
        if not config.DB_PATH.exists():
            pytest.skip("no esta data/ofertas_unificado.sqlite")
        args = train.construir_parser().parse_args([
            "--operacion", "venta", "--tipo", "casa", "--modelos", "ridge",
            "--cv", "espacial", "--folds", "3", "--sin-moran", "--no-guardar"])
        assert train.entrenar(args)["holdout"] is None
