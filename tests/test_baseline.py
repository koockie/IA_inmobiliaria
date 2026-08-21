"""Baseline hedonico: recuperacion de coeficientes, VIF, I de Moran y signos."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import baseline, config, data


class TestVIF:
    def test_variables_independientes_dan_vif_cercano_a_uno(self):
        rng = np.random.default_rng(0)
        X = pd.DataFrame(rng.normal(size=(500, 3)), columns=["a", "b", "c"])
        assert (baseline.calcular_vif(X) < 1.5).all()

    def test_colinealidad_dispara_el_vif(self):
        rng = np.random.default_rng(0)
        a = rng.normal(size=500)
        X = pd.DataFrame({"a": a, "b": a + rng.normal(scale=1e-3, size=500),
                          "c": rng.normal(size=500)})
        vif = baseline.calcular_vif(X)
        assert vif["a"] > 100 and vif["b"] > 100
        assert vif["c"] < 1.5


class TestMoranI:
    def test_detecta_agrupamiento_espacial(self):
        """Residuos que siguen un gradiente suave: I positivo y significativo."""
        rng = np.random.default_rng(1)
        lat = rng.uniform(-33.6, -33.4, 400)
        lon = rng.uniform(-70.7, -70.5, 400)
        residuos = (lat + lon) * 50 + rng.normal(scale=0.01, size=400)
        i, p = baseline.moran_i(residuos, lat, lon)
        assert i > 0.5 and p < 0.05

    def test_residuos_aleatorios_no_dan_senal(self):
        rng = np.random.default_rng(2)
        lat = rng.uniform(-33.6, -33.4, 400)
        lon = rng.uniform(-70.7, -70.5, 400)
        i, p = baseline.moran_i(rng.normal(size=400), lat, lon)
        assert abs(i) < 0.15 and p > 0.05

    def test_es_reproducible(self):
        rng = np.random.default_rng(3)
        lat, lon = rng.uniform(-33.6, -33.4, 200), rng.uniform(-70.7, -70.5, 200)
        r = rng.normal(size=200)
        assert baseline.moran_i(r, lat, lon) == baseline.moran_i(r, lat, lon)

    def test_muestra_insuficiente_da_nan(self):
        i, p = baseline.moran_i(np.arange(3.0), np.arange(3.0), np.arange(3.0))
        assert np.isnan(i) and np.isnan(p)

    def test_ignora_las_filas_sin_geo(self):
        rng = np.random.default_rng(4)
        n = 300
        lat = np.concatenate([rng.uniform(-33.6, -33.4, n), np.full(50, np.nan)])
        lon = np.concatenate([rng.uniform(-70.7, -70.5, n), np.full(50, np.nan)])
        residuos = np.concatenate([rng.normal(size=n), rng.normal(size=50)])
        i, _ = baseline.moran_i(residuos, lat, lon)
        assert np.isfinite(i)


class TestValidarSignos:
    def _coefs(self, **kw):
        filas = {v: {"coef": c, "p": 0.001} for v, c in kw.items()}
        return pd.DataFrame(filas).T

    def test_signos_correctos_no_reportan_nada(self):
        assert baseline.validar_signos(
            self._coefs(log_m2_util=0.8, antiguedad=-0.006, banos=0.17)) == []

    def test_superficie_con_signo_invertido_se_reporta(self):
        fallos = baseline.validar_signos(self._coefs(log_m2_util=-0.5))
        assert len(fallos) == 1 and "log_m2_util" in fallos[0]

    def test_antiguedad_positiva_se_reporta(self):
        fallos = baseline.validar_signos(self._coefs(antiguedad=+0.01))
        assert len(fallos) == 1 and "antiguedad" in fallos[0]

    def test_un_coeficiente_no_significativo_no_es_evidencia(self):
        """Signo raro pero p alto es ruido, no un problema de datos."""
        coefs = pd.DataFrame({"log_m2_util": {"coef": -0.5, "p": 0.6}}).T
        assert baseline.validar_signos(coefs) == []

    def test_dormitorios_no_esta_entre_los_signos_esperados(self):
        """Condicionado a la superficie suele salir negativo: no es un bug."""
        assert "dormitorios" not in baseline.SIGNOS_ESPERADOS
        assert "dormitorios" in baseline.SIGNOS_AMBIGUOS


class TestAjuste:
    def test_recupera_coeficientes_conocidos(self):
        """log(precio) = 5 + 0,8*log(m2) - 0,01*antiguedad + ruido."""
        rng = np.random.default_rng(5)
        n = 2000
        m2 = rng.uniform(30, 150, n)
        ano = rng.integers(1950, 2025, n).astype(float)
        antiguedad = config.ANIO_REFERENCIA - ano
        log_precio = 5.0 + 0.8 * np.log(m2) - 0.01 * antiguedad + rng.normal(0, 0.05, n)

        df = pd.DataFrame({
            "m2_util": m2, "m2_total": m2 * 1.2, "ano_construccion": ano,
            "dormitorios": rng.integers(1, 4, n).astype(float),
            "banos": rng.integers(1, 3, n).astype(float),
            "estacionamientos": rng.integers(0, 2, n).astype(float),
            "bodegas": rng.integers(0, 2, n).astype(float),
            "comuna": ["nunoa"] * n, "tipo": ["departamento"] * n,
            "barrio": ["x"] * n, "precio_uf": np.exp(log_precio),
        })
        r = baseline.ajustar(df, "venta", con_moran=False)
        assert r.coeficientes.loc["log_m2_util", "coef"] == pytest.approx(0.8, abs=0.05)
        assert r.coeficientes.loc["antiguedad", "coef"] == pytest.approx(-0.01, abs=0.005)
        assert r.r2 > 0.9
        assert r.incumplimientos == []

    def test_reporta_cuantos_casos_completos_uso(self):
        """El OLS cae por listwise deletion; el R2 no es comparable con el de ML."""
        rng = np.random.default_rng(6)
        n = 500
        df = pd.DataFrame({
            "m2_util": rng.uniform(30, 150, n), "m2_total": rng.uniform(40, 200, n),
            "ano_construccion": rng.integers(1950, 2025, n).astype(float),
            "dormitorios": rng.integers(1, 4, n).astype(float),
            "banos": rng.integers(1, 3, n).astype(float),
            # La mitad sin informar, como estacionamientos en el dataset real.
            "estacionamientos": np.where(rng.random(n) < 0.5, np.nan, 1.0),
            "bodegas": rng.integers(0, 2, n).astype(float),
            "comuna": ["nunoa"] * n, "tipo": ["departamento"] * n,
            "barrio": ["x"] * n, "precio_uf": rng.uniform(2000, 8000, n),
        })
        r = baseline.ajustar(df, "venta", con_moran=False)
        assert r.n_segmento == n
        assert r.n < n
        assert r.a_dict()["pct_casos_completos"] < 100

    def test_muy_pocas_filas(self):
        df = pd.DataFrame({
            "m2_util": [60.0] * 5, "m2_total": [70.0] * 5, "ano_construccion": [2015.0] * 5,
            "dormitorios": [2.0] * 5, "banos": [2.0] * 5, "estacionamientos": [1.0] * 5,
            "bodegas": [1.0] * 5, "comuna": ["nunoa"] * 5, "tipo": ["departamento"] * 5,
            "barrio": ["x"] * 5, "precio_uf": [3000.0] * 5,
        })
        with pytest.raises(ValueError, match="muy pocas filas"):
            baseline.ajustar(df, "venta")


@pytest.mark.necesita_db
class TestBaselineReal:
    @pytest.fixture(autouse=True)
    def _salta_si_no_hay_base(self):
        if not config.DB_PATH.exists():
            pytest.skip("no esta data/ofertas_unificado.sqlite")

    @pytest.mark.parametrize("op,tipo", [
        ("venta", "departamento"), ("venta", "casa"), ("arriendo", "departamento"),
    ])
    def test_los_signos_del_dataset_real_son_correctos(self, op, tipo):
        """Criterio de aceptacion: un signo invertido significa datos malos."""
        df, _ = data.cargar_segmento(op, tipo)
        r = baseline.ajustar(df, op, con_moran=False)
        assert r.incumplimientos == [], f"{op}-{tipo}: {r.incumplimientos}"

    def test_la_superficie_es_el_factor_dominante(self):
        df, _ = data.cargar_segmento("venta", "departamento")
        r = baseline.ajustar(df, "venta", con_moran=False)
        assert r.coeficientes.loc["log_m2_util", "coef"] > 0.5

    def test_nunoa_es_la_comuna_mas_cara(self):
        """Coincide con las medianas de UF/m2 medidas sobre el dataset."""
        df, _ = data.cargar_segmento("venta", "departamento")
        r = baseline.ajustar(df, "venta", con_moran=False)
        dummies = [i for i in r.coeficientes.index if i.startswith("comuna_")]
        mas_cara = r.coeficientes.loc[dummies, "coef"].idxmax()
        assert mas_cara == "comuna_nunoa"

    def test_queda_autocorrelacion_espacial_en_los_residuos(self):
        """Justifica empiricamente meter lat/lon en los modelos de arboles."""
        df, _ = data.cargar_segmento("venta", "departamento")
        r = baseline.ajustar(df, "venta")
        assert r.moran_i is not None and r.moran_i > 0.1
        assert r.moran_p < 0.05

    def test_sin_multicolinealidad_grave(self):
        df, _ = data.cargar_segmento("venta", "departamento")
        r = baseline.ajustar(df, "venta", con_moran=False)
        assert (r.vif.dropna() < 10).all()
