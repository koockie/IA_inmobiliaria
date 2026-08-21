"""Features derivadas, encoding y las tres barreras antifuga del pipeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import TargetEncoder

from ml import config, features as f


def _base(n=1, **kw):
    d = {
        "m2_util": [60.0] * n, "m2_total": [75.0] * n, "dormitorios": [2.0] * n,
        "banos": [2.0] * n, "estacionamientos": [1.0] * n, "bodegas": [1.0] * n,
        "gastos_comunes_clp": [80_000.0] * n, "lat": [-33.45] * n, "lon": [-70.60] * n,
        "ano_construccion": [2015.0] * n, "comuna": ["nunoa"] * n,
        "tipo": ["departamento"] * n, "barrio": ["plaza nunoa"] * n,
    }
    d.update(kw)
    return pd.DataFrame(d)


class TestDerivadas:
    def test_ratio_terraza_con_valores_conocidos(self):
        d = f.derivar(_base(m2_util=[60.0], m2_total=[75.0]))
        assert d["ratio_terraza"].iloc[0] == pytest.approx(0.2)

    def test_antiguedad_usa_ano_fijo_no_el_actual(self):
        """ANIO_REFERENCIA esta congelado para que el feature sea reproducible."""
        d = f.derivar(_base(ano_construccion=[2015.0]))
        assert d["antiguedad"].iloc[0] == config.ANIO_REFERENCIA - 2015

    def test_log_m2_util(self):
        d = f.derivar(_base(m2_util=[np.e]))
        assert d["log_m2_util"].iloc[0] == pytest.approx(1.0)

    def test_densidad_banos_con_monoambiente_es_finita(self):
        """dormitorios = 0 es valido: no puede producir una division por cero."""
        d = f.derivar(_base(dormitorios=[0.0], banos=[1.0]))
        assert np.isfinite(d["densidad_banos"].iloc[0])
        assert d["densidad_banos"].iloc[0] == pytest.approx(1.0)

    def test_m2_por_dormitorio_con_cero_dormitorios(self):
        d = f.derivar(_base(m2_util=[40.0], dormitorios=[0.0]))
        assert d["m2_por_dormitorio"].iloc[0] == pytest.approx(40.0)

    def test_flag_de_m2_total_copiado(self):
        """En 3.175 filas m2_total es copia de m2_util y no aporta nada."""
        d = f.derivar(_base(n=2, m2_util=[60.0, 60.0], m2_total=[60.0, 75.0]))
        assert list(d["m2_total_igual_util"]) == [1, 0]

    def test_flags_de_ausencia_informativa(self):
        d = f.derivar(_base(n=2, estacionamientos=[np.nan, 2.0]))
        assert list(d["estacionamientos_informado"]) == [0, 1]
        assert list(d["tiene_estacionamiento"]) == [0, 1]

    def test_ratio_terraza_es_na_sin_m2_total(self):
        d = f.derivar(_base(m2_total=[np.nan]))
        assert pd.isna(d["ratio_terraza"].iloc[0])

    def test_es_funcion_pura(self):
        original = _base()
        columnas_antes = list(original.columns)
        f.derivar(original)
        assert list(original.columns) == columnas_antes


class TestClaveBarrio:
    def test_distingue_barrios_homonimos_de_comunas_distintas(self):
        """Once nombres de barrio se repiten entre comunas: no deben mezclarse."""
        df = _base(n=2, comuna=["nunoa", "macul"], barrio=["villa frei", "villa frei"])
        assert f.clave_barrio(df).nunique() == 2

    def test_mismo_barrio_y_comuna_es_una_sola_clave(self):
        df = _base(n=2, comuna=["nunoa"] * 2, barrio=["plaza nunoa"] * 2)
        assert f.clave_barrio(df).nunique() == 1

    def test_barrio_faltante_no_rompe(self):
        df = _base(barrio=[None])
        assert f.clave_barrio(df).iloc[0] == "nunoa|sin_barrio"


class TestAgrupadorCola:
    def test_colapsa_las_categorias_raras(self):
        X = pd.DataFrame({"b": ["comun"] * 30 + ["raro"] * 3})
        salida = f.AgrupadorCola(min_freq=20).fit_transform(X)
        assert set(salida["b"]) == {"comun", "OTROS"}

    def test_categoria_inedita_en_transform_va_a_otros(self):
        ag = f.AgrupadorCola(min_freq=5).fit(pd.DataFrame({"b": ["a"] * 10}))
        salida = ag.transform(pd.DataFrame({"b": ["a", "jamas_vista"]}))
        assert list(salida["b"]) == ["a", "OTROS"]

    def test_aprende_las_frecuencias_solo_del_train(self):
        """Si contara sobre todo el dataset, la presencia de una categoria en el
        test decidiria si sobrevive en el train: fuga sutil."""
        train = pd.DataFrame({"b": ["a"] * 30 + ["b"] * 3})
        ag = f.AgrupadorCola(min_freq=20).fit(train)
        assert ag.categorias_["b"] == {"a"}
        # Aunque "b" abunde en el test, sigue siendo OTROS.
        salida = ag.transform(pd.DataFrame({"b": ["b"] * 100}))
        assert set(salida["b"]) == {"OTROS"}


class TestEspecFeatures:
    def test_ninguna_feature_esta_en_la_lista_de_prohibidas(self):
        """La barrera declarativa contra el leakage."""
        for op in config.OPERACIONES:
            for tipo in ("todos", "casa", "departamento"):
                espec = f.espec_features(op, tipo)
                assert not set(espec.todas) & config.COLUMNAS_PROHIBIDAS

    @pytest.mark.parametrize("prohibida", [
        "precio_clp", "precio_uf", "precio_valor",
        "antiguedad_aviso_dias", "fecha_publicacion", "uf_por_m2",
    ])
    def test_las_columnas_de_riesgo_estan_declaradas_prohibidas(self, prohibida):
        assert prohibida in config.COLUMNAS_PROHIBIDAS

    def test_fecha_publicacion_esta_prohibida(self):
        """Es biyeccion exacta con antiguedad_aviso_dias dado fecha_scrape (3
        valores). Excluir una y dejar la otra seria la misma fuga."""
        assert "fecha_publicacion" in config.COLUMNAS_PROHIBIDAS
        assert "antiguedad_aviso_dias" in config.COLUMNAS_PROHIBIDAS

    def test_tipo_sale_del_onehot_en_un_segmento_de_un_solo_tipo(self):
        assert "tipo" not in f.espec_features("venta", "casa").onehot
        assert "tipo" in f.espec_features("venta", "todos").onehot

    def test_sitio_solo_entra_en_la_corrida_diagnostica(self):
        """La API no puede suministrar `sitio` en inferencia."""
        assert "sitio" not in f.espec_features("venta", "todos").onehot
        assert "sitio" in f.espec_features("venta", "todos", incluir_sitio=True).onehot

    def test_preprocesador_rechaza_una_espec_contaminada(self):
        malo = f.EspecFeatures(numericas=["m2_util", "precio_clp"])
        with pytest.raises(ValueError, match="columnas prohibidas"):
            f.construir_preprocesador(malo, "arbol_nan")


class TestPipelineAntifuga:
    """Los tres tests que sostienen la validez de todas las metricas."""

    @pytest.fixture
    def datos(self):
        rng = np.random.default_rng(0)
        n = 400
        barrios = rng.choice(["a", "b", "c", "d"], n)
        df = pd.DataFrame({
            "m2_util": rng.uniform(30, 120, n), "m2_total": rng.uniform(40, 140, n),
            "dormitorios": rng.integers(1, 4, n).astype(float),
            "banos": rng.integers(1, 3, n).astype(float),
            "estacionamientos": rng.choice([np.nan, 1.0], n),
            "bodegas": rng.choice([np.nan, 1.0], n),
            "gastos_comunes_clp": rng.uniform(50_000, 150_000, n),
            "lat": rng.uniform(-33.6, -33.4, n), "lon": rng.uniform(-70.7, -70.5, n),
            "ano_construccion": rng.integers(1980, 2025, n).astype(float),
            "comuna": rng.choice(["nunoa", "macul"], n),
            "tipo": ["departamento"] * n, "barrio": barrios,
        })
        y = np.log(rng.uniform(2000, 8000, n))
        return df, y

    def test_el_target_encoding_se_ajusta_solo_con_el_train(self, datos):
        """Compara las codificaciones contra un ajuste solo-train y uno global."""
        df, y = datos
        espec = f.espec_features("venta", "departamento")
        X = f.preparar_matriz(df, espec)
        train = np.arange(300)

        prep = f.construir_preprocesador(espec, "arbol_nan")
        prep.fit(X.iloc[train], y[train])
        dentro = prep.named_transformers_["barrio"].named_steps["te"].encodings_[0]

        def _codificaciones(indices):
            cola = f.AgrupadorCola(min_freq=config.BARRIO_MIN_FREQ)
            crudo = X.iloc[indices][["comuna_barrio"]]
            te = TargetEncoder(target_type="continuous", smooth="auto")
            te.fit(cola.fit_transform(crudo), y[indices])
            return te.encodings_[0]

        assert np.allclose(dentro, _codificaciones(train))
        assert not np.allclose(dentro, _codificaciones(np.arange(len(df))))

    def test_una_columna_prohibida_en_la_matriz_no_altera_nada(self, datos):
        """remainder='drop' protege aunque nadie haya borrado la columna."""
        df, y = datos
        espec = f.espec_features("venta", "departamento")
        X = f.preparar_matriz(df, espec)
        prep = f.construir_preprocesador(espec, "arbol_nan")
        limpio = prep.fit_transform(X, y)

        X_contaminada = X.copy()
        X_contaminada["precio_uf"] = np.exp(y)          # el target, literal
        contaminado = f.construir_preprocesador(espec, "arbol_nan").fit_transform(
            X_contaminada, y)
        assert np.array_equal(limpio, contaminado, equal_nan=True)

    def test_la_imputacion_usa_la_mediana_del_train_no_la_global(self, datos):
        df, y = datos
        espec = f.espec_features("venta", "departamento")
        X = f.preparar_matriz(df, espec)
        train = np.arange(200)

        prep = f.construir_preprocesador(espec, "arbol_imputa")
        prep.fit(X.iloc[train], y[train])
        imputador = prep.named_transformers_["num"].named_steps["imputar"]
        posicion = espec.numericas.index("m2_util")
        assert imputador.statistics_[posicion] == pytest.approx(
            X.iloc[train]["m2_util"].median())
        assert imputador.statistics_[posicion] != pytest.approx(X["m2_util"].median())


class TestPreprocesadorPorFamilia:
    @pytest.fixture
    def xy(self):
        rng = np.random.default_rng(1)
        n = 120
        df = _base(n=n)
        df["m2_util"] = rng.uniform(30, 120, n)
        df["estacionamientos"] = rng.choice([np.nan, 1.0], n)
        return df, np.log(rng.uniform(2000, 8000, n))

    def test_los_arboles_conservan_el_nan(self, xy):
        """En estacionamientos (47% de faltantes) la ausencia es senal."""
        df, y = xy
        espec = f.espec_features("venta", "departamento")
        M = f.construir_preprocesador(espec, "arbol_nan").fit_transform(
            f.preparar_matriz(df, espec), y)
        assert np.isnan(M).any()

    @pytest.mark.parametrize("familia", ["lineal", "arbol_imputa"])
    def test_las_familias_que_imputan_no_dejan_nan(self, xy, familia):
        df, y = xy
        espec = f.espec_features("venta", "departamento")
        M = f.construir_preprocesador(espec, familia).fit_transform(
            f.preparar_matriz(df, espec), y)
        assert not np.isnan(M).any()

    def test_familia_desconocida(self):
        with pytest.raises(ValueError, match="familia desconocida"):
            f.construir_preprocesador(f.espec_features("venta"), "red_neuronal")

    def test_preparar_matriz_avisa_de_columnas_faltantes(self):
        with pytest.raises(KeyError, match="faltan columnas"):
            f.preparar_matriz(pd.DataFrame({"m2_util": [60.0]}),
                              f.espec_features("venta", "departamento"))
