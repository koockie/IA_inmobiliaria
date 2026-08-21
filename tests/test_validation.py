"""Split espacial: agrupacion por edificio y garantia de disyuncion."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import config, data, validation as v


def _df(lats, lons, direcciones=None, n=None):
    n = n or len(lats)
    return pd.DataFrame({
        "lat": lats, "lon": lons,
        "direccion": direcciones if direcciones is not None else [f"Calle {i}" for i in range(n)],
    })


class TestClaveEspacial:
    def test_coordenadas_identicas_dan_un_solo_grupo(self):
        claves = v.clave_espacial(_df([-33.4567] * 3, [-70.5432] * 3))
        assert claves.nunique() == 1

    def test_diferencia_en_el_quinto_decimal_no_separa(self):
        """~1 m de diferencia sigue siendo el mismo edificio."""
        claves = v.clave_espacial(_df([-33.45670, -33.45671], [-70.5432, -70.5432]))
        assert claves.nunique() == 1

    def test_diferencia_en_el_cuarto_decimal_si_separa(self):
        """~11 m ya es otro edificio."""
        claves = v.clave_espacial(_df([-33.4567, -33.4568], [-70.5432, -70.5432]))
        assert claves.nunique() == 2

    def test_tres_decimales_agrupa_mas_que_cuatro(self):
        lats = [-33.4560, -33.4565, -33.4569]
        lons = [-70.5432] * 3
        assert v.clave_espacial(_df(lats, lons), decimales=4).nunique() == 3
        assert v.clave_espacial(_df(lats, lons), decimales=3).nunique() < 3

    def test_redondeo_es_deterministico_en_el_borde(self):
        """Fija el comportamiento por test, no por suerte del formateo."""
        claves = v.clave_espacial(_df([-33.45675, -33.45675], [-70.5, -70.5]))
        assert claves.iloc[0] == claves.iloc[1]

    def test_sin_geo_cae_en_la_direccion(self):
        df = _df([np.nan, np.nan], [np.nan, np.nan], ["Av Grecia 100", "Av Grecia 100"])
        claves = v.clave_espacial(df)
        assert claves.iloc[0].startswith("d:")
        assert claves.iloc[0] == claves.iloc[1]

    def test_la_direccion_se_normaliza_antes_de_agrupar(self):
        df = _df([np.nan] * 2, [np.nan] * 2, ["  Av. ÑUÑOA 12 ", "av. nunoa 12"])
        assert v.clave_espacial(df).nunique() == 1

    def test_sin_geo_ni_direccion_queda_singleton(self):
        df = _df([np.nan] * 3, [np.nan] * 3, [None, "", np.nan])
        claves = v.clave_espacial(df)
        assert all(c.startswith("u:") for c in claves)
        assert claves.nunique() == 3

    def test_la_cascada_no_deja_ninguna_clave_nula(self):
        df = _df([-33.45, np.nan, np.nan], [-70.6, np.nan, np.nan],
                 ["Calle A", "Calle B", None])
        claves = v.clave_espacial(df)
        assert claves.notna().all()
        assert [c[0] for c in claves] == ["g", "d", "u"]

    def test_faltan_columnas_de_geo(self):
        with pytest.raises(KeyError, match="lat/lon"):
            v.clave_espacial(pd.DataFrame({"comuna": ["nunoa"]}))


class TestParticiones:
    @pytest.fixture
    def df_grupos(self):
        """60 filas en 12 edificios de 5 avisos cada uno."""
        filas = []
        for edificio in range(12):
            for _ in range(5):
                filas.append({"lat": -33.45 + edificio * 0.001,
                              "lon": -70.60, "direccion": f"Torre {edificio}"})
        return pd.DataFrame(filas)

    def test_ningun_grupo_cruza_train_y_test(self, df_grupos):
        """El test que hace honesto al esquema espacial."""
        y = np.linspace(2000, 8000, len(df_grupos))
        claves = v.clave_espacial(df_grupos).to_numpy()
        for train, test in v.particiones(df_grupos, y, "espacial", n_splits=4):
            assert not (set(claves[train]) & set(claves[test]))

    def test_el_split_aleatorio_si_parte_los_grupos(self, df_grupos):
        """Contraste explicito: es exactamente la fuga que se quiere evitar."""
        y = np.linspace(2000, 8000, len(df_grupos))
        claves = v.clave_espacial(df_grupos).to_numpy()
        cruces = sum(
            len(set(claves[tr]) & set(claves[te])) > 0
            for tr, te in v.particiones(df_grupos, y, "aleatorio", n_splits=4)
        )
        assert cruces > 0

    def test_verificar_disyuncion_detecta_la_fuga(self, df_grupos):
        indices = np.arange(len(df_grupos))
        with pytest.raises(AssertionError, match="aparecen en train y test"):
            v.verificar_disyuncion(df_grupos, indices[:30], indices[25:])

    def test_verificar_disyuncion_acepta_un_split_limpio(self, df_grupos):
        y = np.linspace(2000, 8000, len(df_grupos))
        for train, test in v.particiones(df_grupos, y, "espacial", n_splits=4):
            v.verificar_disyuncion(df_grupos, train, test)

    def test_cubre_todas_las_filas(self, df_grupos):
        y = np.linspace(2000, 8000, len(df_grupos))
        vistos = set()
        for _, test in v.particiones(df_grupos, y, "espacial", n_splits=4):
            vistos |= set(test)
        assert vistos == set(range(len(df_grupos)))

    def test_estricto_excluye_del_test_las_filas_sin_geo(self):
        filas = []
        for edificio in range(10):
            for _ in range(4):
                filas.append({"lat": -33.45 + edificio * 0.001, "lon": -70.60,
                              "direccion": f"Torre {edificio}"})
        for i in range(12):
            filas.append({"lat": np.nan, "lon": np.nan, "direccion": f"Sin geo {i}"})
        df = pd.DataFrame(filas)
        y = np.linspace(2000, 8000, len(df))
        con_geo = df["lat"].notna().to_numpy()

        for train, test in v.particiones(df, y, "espacial_estricto", n_splits=4):
            assert con_geo[test].all()

        # ...pero el train si las conserva: aportan senal aunque no se pueda
        # verificar que no filtran.
        trains = [tr for tr, _ in v.particiones(df, y, "espacial_estricto", n_splits=4)]
        assert any((~con_geo[tr]).any() for tr in trains)

    def test_esquema_invalido(self, df_grupos):
        with pytest.raises(ValueError, match="esquema invalido"):
            list(v.particiones(df_grupos, np.arange(len(df_grupos)), "por_barrio"))

    def test_menos_grupos_que_folds_da_error_claro(self):
        df = _df([-33.45, -33.45, -33.46], [-70.6] * 3)
        with pytest.raises(ValueError, match="grupos espaciales para"):
            list(v.particiones(df, np.arange(3), "espacial", n_splits=5))

    def test_es_reproducible_con_la_misma_semilla(self, df_grupos):
        y = np.linspace(2000, 8000, len(df_grupos))
        a = [t.tolist() for _, t in v.particiones(df_grupos, y, "espacial", semilla=42)]
        b = [t.tolist() for _, t in v.particiones(df_grupos, y, "espacial", semilla=42)]
        assert a == b


class TestResumenGrupos:
    def test_cuenta_grupos_y_singletons(self):
        claves = pd.Series(["g:a", "g:a", "g:a", "g:b", "g:c"], dtype="string")
        r = v.resumen_grupos(claves)
        assert r.n_grupos == 3 and r.n_grupos_multiples == 1
        assert r.grupo_maximo == 3 and r.n_singletons == 2
        assert r.filas_en_grupo_multiple == 3
        assert r.pct_filas_en_grupo_multiple == pytest.approx(60.0)

    def test_desglosa_por_fuente_de_la_clave(self):
        claves = pd.Series(["g:1", "g:2", "d:x", "u:9"], dtype="string")
        assert v.resumen_grupos(claves).por_fuente == {
            "geo": 2, "direccion": 1, "singleton": 1}


@pytest.mark.necesita_db
class TestEstructuraEspacialReal:
    """Reproduce la medicion que justifica usar 4 decimales y no 3."""

    @pytest.fixture(autouse=True)
    def _salta_si_no_hay_base(self):
        if not config.DB_PATH.exists():
            pytest.skip("no esta data/ofertas_unificado.sqlite")

    @pytest.fixture(scope="class")
    def geo(self):
        df = data.castear_tipos(data.a_faltantes(data.cargar_crudo()))
        return df[df["lat"].notna() & df["lon"].notna()]

    def test_cuatro_decimales_reproduce_la_medicion(self, geo):
        r = v.resumen_grupos(v.clave_espacial(geo, decimales=4))
        assert r.n_grupos == 7_514
        assert r.grupo_maximo == 53
        assert r.n_singletons == 5_487
        assert r.pct_filas_en_grupo_multiple == pytest.approx(61.8, abs=0.1)

    def test_tres_decimales_colapsa_demasiado(self, geo):
        """Justifica la desviacion respecto del documento de traspaso."""
        cuatro = v.resumen_grupos(v.clave_espacial(geo, decimales=4))
        tres = v.resumen_grupos(v.clave_espacial(geo, decimales=3))
        assert tres.pct_filas_en_grupo_multiple > 85.0
        assert tres.n_grupos < cuatro.n_grupos / 2
        assert tres.grupo_maximo > 100

    def test_la_mayoria_de_las_filas_comparte_edificio(self, geo):
        """Motivo por el que un split aleatorio esta descartado."""
        r = v.resumen_grupos(v.clave_espacial(geo))
        assert r.pct_filas_en_grupo_multiple > 50.0


class TestHoldoutExterno:
    """El holdout responde una pregunta distinta que la validacion cruzada.

    La CV ya da metricas fuera de muestra, pero esas mismas metricas se usan
    para elegir el ganador. El holdout no participa de esa eleccion, asi que
    sigue siendo un estimador limpio del error futuro.
    """

    @pytest.fixture
    def df_grande(self):
        rng = np.random.default_rng(7)
        filas = []
        for edificio in range(120):
            for _ in range(rng.integers(1, 6)):
                filas.append({"lat": -33.45 + edificio * 0.0007, "lon": -70.60,
                              "direccion": f"Torre {edificio}"})
        return pd.DataFrame(filas)

    def test_aparta_aproximadamente_la_fraccion_pedida(self, df_grande):
        dev, hold = v.separar_holdout(df_grande, fraccion=0.2)
        assert 0.12 < len(hold) / len(df_grande) < 0.30
        assert len(dev) + len(hold) == len(df_grande)

    def test_desarrollo_y_holdout_no_comparten_ningun_edificio(self, df_grande):
        """Si una torre quedara en ambos, el holdout no mediria nada."""
        dev, hold = v.separar_holdout(df_grande, fraccion=0.2)
        claves = v.clave_espacial(df_grande).to_numpy()
        assert not (set(claves[dev]) & set(claves[hold]))

    def test_no_se_pierde_ni_se_duplica_ninguna_fila(self, df_grande):
        dev, hold = v.separar_holdout(df_grande, fraccion=0.2)
        assert sorted([*dev, *hold]) == list(range(len(df_grande)))

    def test_es_reproducible_con_la_misma_semilla(self, df_grande):
        a = v.separar_holdout(df_grande, fraccion=0.2, semilla=42)
        b = v.separar_holdout(df_grande, fraccion=0.2, semilla=42)
        assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])

    def test_semillas_distintas_dan_particiones_distintas(self, df_grande):
        a = v.separar_holdout(df_grande, fraccion=0.2, semilla=42)
        b = v.separar_holdout(df_grande, fraccion=0.2, semilla=7)
        assert not np.array_equal(a[1], b[1])

    @pytest.mark.parametrize("fraccion", [0.0, 1.0, -0.1, 1.5])
    def test_fraccion_invalida(self, df_grande, fraccion):
        with pytest.raises(ValueError, match="fraccion debe estar"):
            v.separar_holdout(df_grande, fraccion=fraccion)

    def test_muy_pocos_grupos_da_error_claro(self):
        df = _df([-33.45, -33.46, -33.47], [-70.6] * 3)
        with pytest.raises(ValueError, match="muy pocos"):
            v.separar_holdout(df, fraccion=0.2)
