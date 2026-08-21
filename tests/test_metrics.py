"""Metricas contra valores calculados a mano.

El vector canonico esta construido para que cada estadistico tenga un valor
cerrado y verificable sin ejecutar el codigo:

    y = [100, 200, 300, 400]
    p = [110, 180, 330, 360]

    APE      = [10%, 10%, 10%, 10%]        -> MdAPE = 10, PPE10 = 100
    ratios   = [1.1, 0.9, 1.1, 0.9]        -> mediana = 1.0
    COD      = 100 * media(|r - 1|) / 1    = 100 * 0.1 = 10
    PRD      = media(r) / (sum p / sum y)  = 1.0 / (980/1000) = 1/0.98
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from ml import metrics as m

Y = [100.0, 200.0, 300.0, 400.0]
P = [110.0, 180.0, 330.0, 360.0]


class TestErrorPorcentual:
    def test_mdape_es_diez(self):
        assert m.mdape(Y, P) == pytest.approx(10.0)

    def test_ppe10_borde_inclusivo(self):
        # Los cuatro errores son exactamente 10,0%: deben contar como acierto.
        assert m.ppe(Y, P, 10.0) == pytest.approx(100.0)

    def test_ppe_por_debajo_del_borde_no_cuenta(self):
        assert m.ppe(Y, P, 9.9) == pytest.approx(0.0)

    def test_mdape_usa_mediana_no_media(self):
        # Un solo outlier brutal dispara el MAPE pero deja la mediana intacta.
        y = [100.0] * 10
        p = [105.0] * 9 + [10_000.0]
        assert m.mdape(y, p) == pytest.approx(5.0)
        assert m.mape(y, p) > 900.0

    def test_prediccion_perfecta(self):
        assert m.mdape(Y, Y) == 0.0
        assert m.ppe(Y, Y) == 100.0
        assert m.cod(Y, Y) == 0.0
        assert m.prd(Y, Y) == pytest.approx(1.0)
        assert m.prb(Y, Y).coef == pytest.approx(0.0, abs=1e-12)


class TestIAAO:
    def test_ratios_y_mediana(self):
        assert list(m.ratios(Y, P)) == pytest.approx([1.1, 0.9, 1.1, 0.9])
        assert m.mediana_ratio(Y, P) == pytest.approx(1.0)

    def test_cod_es_diez(self):
        assert m.cod(Y, P) == pytest.approx(10.0)

    def test_prd_es_uno_sobre_cero_coma_98(self):
        assert m.prd(Y, P) == pytest.approx(1.0 / 0.98)

    def test_prb_contra_ols_independiente(self):
        """Reimplementa PRB con numpy.polyfit para verificar la formula IAAO."""
        y, p = np.array(Y), np.array(P)
        r = p / y
        med = np.median(r)
        dep = (r - med) / med
        ind = np.log(0.5 * y + 0.5 * p / med) / np.log(2.0)
        pendiente_esperada = np.polyfit(ind, dep, 1)[0]
        assert m.prb(Y, P).coef == pytest.approx(pendiente_esperada)

    def test_prb_trae_intervalo_de_confianza(self):
        res = m.prb(Y, P)
        assert res.ic95[0] < res.coef < res.ic95[1]
        assert res.error_estandar > 0

    def test_regresividad_detectada_por_prd_y_prb(self):
        """Modelo que sobrevalora las baratas y subvalora las caras.

        Es el sesgo que PRD y PRB existen para detectar, y ambos deben
        coincidir en el diagnostico: PRD > 1,03 y PRB < -0,05.
        """
        y = np.array([50.0, 100.0, 200.0, 400.0, 800.0, 1600.0])
        p = y * np.array([1.30, 1.20, 1.10, 0.95, 0.85, 0.75])
        assert m.prd(y, p) > 1.03
        assert m.prb(y, p).coef < -0.05
        assert not m.cumple_iaao(m.tabla_metricas(y, p))["prd"]

    def test_cumple_iaao_con_modelo_uniforme(self):
        rng = np.random.default_rng(42)
        y = rng.uniform(1000, 8000, 4000)
        p = y * rng.normal(1.0, 0.06, 4000)   # ruido simetrico, sin sesgo vertical
        veredicto = m.cumple_iaao(m.tabla_metricas(y, p))
        assert veredicto["prd"] and veredicto["prb"]


class TestValidacionDeEscala:
    def test_aborta_si_le_pasan_logaritmos_de_venta(self):
        # log(3450 UF) = 8,15: la trampa que este proyecto quiere evitar.
        with pytest.raises(ValueError, match="logaritmica"):
            m.validar_escala(np.log([3000.0, 3450.0, 4000.0]), "venta")

    def test_aborta_si_le_pasan_logaritmos_de_arriendo(self):
        with pytest.raises(ValueError, match="logaritmica"):
            m.validar_escala(np.log([400_000.0, 470_000.0, 520_000.0]), "arriendo")

    def test_acepta_escala_original(self):
        m.validar_escala([3000.0, 3450.0, 4000.0], "venta")
        m.validar_escala([400_000.0, 470_000.0], "arriendo")

    def test_tabla_metricas_valida_escala(self):
        logs = np.log(np.array(Y) * 30)
        with pytest.raises(ValueError, match="logaritmica"):
            m.tabla_metricas(logs, logs, operacion="venta")


class TestEntradasDegeneradas:
    def test_formas_distintas(self):
        with pytest.raises(ValueError, match="formas distintas"):
            m.mdape([1.0, 2.0], [1.0, 2.0, 3.0])

    def test_descarta_no_finitos_y_reales_no_positivos(self):
        y = [100.0, 0.0, 300.0, math.nan]
        p = [110.0, 50.0, 330.0, 400.0]
        # Solo sobreviven los pares 1 y 3, ambos con 10% de error.
        assert m.mdape(y, p) == pytest.approx(10.0)

    def test_sin_pares_validos(self):
        with pytest.raises(ValueError, match="ningun par valido"):
            m.mdape([0.0, -5.0], [1.0, 2.0])

    def test_prb_con_menos_de_tres_puntos_es_nan(self):
        assert math.isnan(m.prb([100.0, 200.0], [110.0, 180.0]).coef)


class TestTablaYGrupos:
    def test_tabla_trae_todas_las_claves(self):
        t = m.tabla_metricas(Y, P, operacion="venta")
        esperadas = {"n", "mdape", "mape", "ppe10", "ppe20", "cod", "prd", "prb",
                     "prb_ic95", "mediana_ratio", "mae", "rmse", "r2", "sesgo_pct"}
        assert esperadas <= set(t)
        assert t["n"] == 4

    def test_sesgo_con_signo(self):
        y = [100.0, 100.0]
        assert m.sesgo_pct(y, [110.0, 110.0]) == pytest.approx(10.0)
        assert m.sesgo_pct(y, [90.0, 90.0]) == pytest.approx(-10.0)

    def test_metricas_por_grupo_respeta_el_minimo(self):
        y = [100.0] * 50 + [200.0] * 10
        p = [110.0] * 50 + [220.0] * 10
        grupos = ["grande"] * 50 + ["chico"] * 10
        tabla = m.metricas_por_grupo(y, p, grupos, minimo=30)
        assert list(tabla["grupo"]) == ["grande"]
        assert tabla.loc[0, "mdape"] == pytest.approx(10.0)

    def test_metricas_por_grupo_sin_grupos_suficientes(self):
        tabla = m.metricas_por_grupo(Y, P, ["a", "a", "b", "b"], minimo=30)
        assert tabla.empty
