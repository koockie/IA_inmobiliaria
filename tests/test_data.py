"""Carga, reparacion de precios y filtros de calidad."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from ml import config, data


class TestCarga:
    def test_lee_todas_las_filas(self, db_muestra, df_crudo):
        assert len(data.cargar_crudo(db_muestra)) == len(df_crudo)

    def test_base_inexistente_da_error_claro(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="no existe la base"):
            data.cargar_crudo(tmp_path / "no_existe.sqlite")

    def test_no_modifica_el_archivo(self, db_muestra):
        """El modulo abre en mode=ro: data/ es de solo lectura para ml/."""
        antes = os.stat(db_muestra).st_mtime_ns
        data.cargar_crudo(db_muestra)
        assert os.stat(db_muestra).st_mtime_ns == antes


class TestSinDato:
    def test_el_centinela_se_vuelve_na(self, db_muestra):
        crudo = data.cargar_crudo(db_muestra)
        assert (crudo["publica"] == config.MARCADOR).all()
        limpio = data.a_faltantes(crudo)
        assert limpio["publica"].isna().all()

    def test_no_queda_ningun_sin_dato(self, db_muestra):
        limpio = data.a_faltantes(data.cargar_crudo(db_muestra))
        for col in limpio.columns:
            assert not (limpio[col].astype("string") == config.MARCADOR).any(), col

    def test_casteo_produce_float64_no_nullable(self, db_muestra):
        """LightGBM y XGBoost necesitan np.nan; los dtypes nullable los rompen."""
        df = data.castear_tipos(data.a_faltantes(data.cargar_crudo(db_muestra)))
        for col in ("precio_uf", "m2_util", "lat", "dormitorios"):
            assert df[col].dtype == np.float64, col

    def test_detalle_ok_es_integer_y_no_rompe_el_casteo(self, db_muestra):
        """Es la unica columna INTEGER de la tabla: la convencion no es uniforme."""
        df = data.castear_tipos(data.a_faltantes(data.cargar_crudo(db_muestra)))
        assert df["detalle_ok"].notna().all()

    def test_sin_dato_en_numerica_queda_nan(self, db_muestra):
        df = data.castear_tipos(data.a_faltantes(data.cargar_crudo(db_muestra)))
        sin_geo = df[df["id_aviso"] == "sin_geo"].iloc[0]
        assert pd.isna(sin_geo["lat"]) and pd.isna(sin_geo["lon"])


class TestUF:
    def test_uf_implicita_sale_de_los_datos(self, db_muestra):
        df = data.castear_tipos(data.a_faltantes(data.cargar_crudo(db_muestra)))
        assert data.uf_implicita(df) is None or data.uf_implicita(df) > 0

    def test_uf_referencia_cae_a_la_constante_sin_datos(self):
        valor, procedencia = data.uf_referencia(None)
        assert valor == config.UF_FALLBACK_CLP
        assert procedencia == "constante_empirica"

    def test_uf_fuera_de_banda_se_rechaza(self):
        df = pd.DataFrame({"precio_clp": [100.0] * 200, "precio_uf": [1.0] * 200})
        assert data.uf_implicita(df) is None   # razon = 100, muy lejos de ~40.845


class TestReparacionDePrecios:
    UF = 40_844.79

    def test_reconstruye_uf_desde_clp(self):
        df = pd.DataFrame({"precio_clp": [40_844_790.0], "precio_uf": [np.nan]})
        rep, _ = data.reparar_precios(df, self.UF)
        assert rep["precio_uf"].iloc[0] == pytest.approx(1000.0)

    def test_reconstruye_clp_desde_uf(self):
        """La direccion que el documento de traspaso no diagnostica."""
        df = pd.DataFrame({"precio_clp": [np.nan], "precio_uf": [1000.0]})
        rep, _ = data.reparar_precios(df, self.UF)
        assert rep["precio_clp"].iloc[0] == pytest.approx(40_844_790.0)

    def test_reparacion_es_bidireccional_en_una_sola_pasada(self, db_muestra):
        df = data.castear_tipos(data.a_faltantes(data.cargar_crudo(db_muestra)))
        _, rep = data.reparar_precios(df, self.UF)
        assert rep.clp_a_uf >= 1 and rep.uf_a_clp >= 1

    def test_no_pisa_precios_existentes(self):
        df = pd.DataFrame({"precio_clp": [1.0], "precio_uf": [999.0]})
        rep, _ = data.reparar_precios(df, self.UF)
        assert rep["precio_uf"].iloc[0] == 999.0
        assert rep["precio_clp"].iloc[0] == 1.0

    def test_marca_el_origen_para_auditoria(self):
        df = pd.DataFrame({"precio_clp": [40_844_790.0, np.nan, 1.0],
                           "precio_uf": [np.nan, 1000.0, 2.0]})
        rep, _ = data.reparar_precios(df, self.UF)
        assert list(rep["precio_origen"]) == [
            "reconstruido_clp_a_uf", "reconstruido_uf_a_clp", "scraper"]

    def test_precio_origen_esta_prohibido_como_feature(self):
        assert "precio_origen" in config.COLUMNAS_PROHIBIDAS


class TestFiltros:
    def _cargar(self, db, op="venta", tipo="departamento", recorte=False):
        # recorte=False por defecto: con ~24 filas el p1-p99 se lleva justo los
        # casos borde que cada test quiere inspeccionar.
        return data.cargar_segmento(op, tipo, db_path=db, con_recorte_final=recorte)

    def _paso(self, informe, nombre):
        return next(p for p in informe.pasos if p.nombre == nombre)

    def test_m2_util_fuera_de_rango_se_elimina(self, db_muestra):
        df, inf = self._cargar(db_muestra)
        assert self._paso(inf, "m2_util_rango").eliminadas == 2   # m2=1 y m2=138000
        assert "m2_min" not in set(df["id_aviso"]) and "m2_max" not in set(df["id_aviso"])

    def test_m2_incoherente_anula_el_campo_pero_conserva_la_fila(self, db_muestra):
        df, inf = self._cargar(db_muestra)
        assert self._paso(inf, "m2_total_inconsistente").eliminadas == 0
        fila = df[df["id_aviso"] == "m2_incoherente"]
        assert len(fila) == 1
        assert pd.isna(fila["m2_total"].iloc[0])
        assert fila["m2_inconsistente"].iloc[0] == 1

    def test_geo_fuera_de_bbox_se_anula_y_la_fila_sobrevive(self, db_muestra):
        df, _ = self._cargar(db_muestra)
        fila = df[df["id_aviso"] == "geo_mala"]
        assert len(fila) == 1
        assert pd.isna(fila["lat"].iloc[0]) and pd.isna(fila["lon"].iloc[0])
        assert fila["geo_valida"].iloc[0] == 0

    def test_banos_cero_se_anula_pero_dormitorios_cero_se_conserva(self, db_muestra):
        """Un monoambiente tiene 0 dormitorios; ninguna vivienda tiene 0 banos."""
        df, _ = self._cargar(db_muestra)
        assert pd.isna(df.loc[df["id_aviso"] == "banos_cero", "banos"].iloc[0])
        assert df.loc[df["id_aviso"] == "monoambiente", "dormitorios"].iloc[0] == 0

    def test_gastos_cero_se_anula_en_depto(self, db_muestra):
        df, _ = self._cargar(db_muestra)
        assert pd.isna(df.loc[df["id_aviso"] == "gc_cero_depto", "gastos_comunes_clp"].iloc[0])

    def test_gastos_cero_se_conserva_en_casa(self, db_muestra):
        """En casa el 0 es cero real (53,6% de las casas), no un faltante."""
        df, _ = self._cargar(db_muestra, tipo="casa")
        assert df.loc[df["id_aviso"] == "gc_cero_casa", "gastos_comunes_clp"].iloc[0] == 0

    def test_estacionamientos_del_edificio_se_anulan(self, db_muestra):
        """Algunos avisos informan el conteo del edificio entero: un estudio de
        29 m2 con 540 estacionamientos y 95 bodegas. El modelo lo leia como una
        caracteristica cara de la propiedad."""
        df, inf = self._cargar(db_muestra)
        fila = df[df["id_aviso"] == "estac_edificio"]
        assert len(fila) == 1, "la fila se conserva, solo se anula el campo"
        assert pd.isna(fila["estacionamientos"].iloc[0])
        assert pd.isna(fila["bodegas"].iloc[0])
        assert self._paso(inf, "estac_bodegas_del_edificio").anuladas == 2

    def test_estacionamientos_plausibles_se_conservan(self, db_muestra):
        df, _ = self._cargar(db_muestra)
        assert df.loc[df["id_aviso"] == "ok1", "estacionamientos"].iloc[0] == 1

    def test_duplicado_duro_se_elimina(self, db_muestra):
        """De dos avisos identicos sobrevive uno solo."""
        df, inf = self._cargar(db_muestra)
        assert self._paso(inf, "duplicados_duros").eliminadas == 1
        supervivientes = set(df["id_aviso"]) & {"ok0", "dup"}
        assert len(supervivientes) == 1

    def test_al_desempatar_duplicados_gana_el_precio_original(self, db_muestra):
        """`dup` se capturo el 27/07, el dia en que fallo la UF: su precio es
        reconstruido, asi que debe ceder ante el precio original de `ok0`."""
        df, _ = self._cargar(db_muestra)
        assert "ok0" in set(df["id_aviso"])
        assert "dup" not in set(df["id_aviso"])

    def test_contaminacion_de_operacion_se_elimina(self, db_muestra):
        """194 millones de CLP no es un arriendo: es una venta mal etiquetada."""
        df, _ = self._cargar(db_muestra, op="arriendo")
        assert "arr_contaminado" not in set(df["id_aviso"])
        assert "arr_ok" in set(df["id_aviso"])

    def test_columna_publica_se_descarta(self, db_muestra):
        df, _ = self._cargar(db_muestra)
        assert "publica" not in df.columns

    def test_informe_cuadra_con_las_filas_devueltas(self, db_muestra):
        df, inf = self._cargar(db_muestra)
        assert inf.filas_finales == len(df)
        assert inf.filas_crudas == 25

    def test_cada_paso_reporta_su_conteo(self, db_muestra):
        _, inf = self._cargar(db_muestra)
        for p in inf.pasos:
            assert p.eliminadas == p.antes - p.despues
            assert p.eliminadas >= 0 and p.anuladas >= 0

    def test_sin_recorte_final_conserva_mas_filas(self, db_muestra):
        con, _ = self._cargar(db_muestra, recorte=True)
        sin, inf = self._cargar(db_muestra, recorte=False)
        assert len(sin) >= len(con)
        assert not any(p.nombre == "recorte_precio_m2" for p in inf.pasos)

    def test_operacion_invalida(self, db_muestra):
        with pytest.raises(ValueError, match="operacion invalida"):
            data.cargar_segmento("permuta", db_path=db_muestra)


class TestNormalizarTexto:
    def test_quita_tildes_y_colapsa_espacios(self):
        assert data.normalizar_texto("  Av.  Ñuñoa   123 ") == "av. nunoa 123"

    def test_faltantes_dan_cadena_vacia(self):
        assert data.normalizar_texto(None) == ""
        assert data.normalizar_texto(np.nan) == ""
        assert data.normalizar_texto(pd.NA) == ""


@pytest.mark.necesita_db
class TestDatasetReal:
    """Reproduce los conteos verificados contra data/ofertas_unificado.sqlite."""

    @pytest.fixture(autouse=True)
    def _salta_si_no_hay_base(self):
        if not config.DB_PATH.exists():
            pytest.skip("no esta data/ofertas_unificado.sqlite")

    def test_volumen_y_esquema(self):
        crudo = data.cargar_crudo()
        assert len(crudo) == 15_808
        assert len(crudo.columns) == 30

    def test_reparto_por_sitio(self):
        crudo = data.cargar_crudo()
        conteo = crudo["sitio"].value_counts()
        assert conteo["pi"] == 14_462 and conteo["cp"] == 1_346

    def test_uf_implicita_reproduce_la_medicion(self):
        df = data.castear_tipos(data.a_faltantes(data.cargar_crudo()))
        assert data.uf_implicita(df) == pytest.approx(40_844.79, abs=0.01)

    def test_el_fallo_de_uf_fue_bidireccional(self):
        df = data.castear_tipos(data.a_faltantes(data.cargar_crudo()))
        _, rep = data.reparar_precios(df, 40_844.79)
        assert rep.clp_a_uf == 3_102
        assert rep.uf_a_clp == 3_747      # la mitad que el documento no diagnostica
        assert rep.sin_ningun_precio == 0

    @pytest.mark.parametrize("op,tipo,esperado", [
        ("venta", "departamento", 6_813),   # era 6.355 antes de reparar la UF
        ("venta", "casa", 3_114),           # era 2.393: +30%
        ("arriendo", "departamento", 5_533),
        ("arriendo", "casa", 224),
    ])
    def test_filas_utilizables_tras_reparar_uf(self, op, tipo, esperado):
        _, inf = data.cargar_segmento(op, tipo)
        paso = next(p for p in inf.pasos if p.nombre == "m2_util_presente")
        assert paso.despues == esperado

    def test_la_columna_publica_esta_vacia_en_el_dataset_real(self):
        crudo = data.cargar_crudo()
        assert (crudo["publica"] == config.MARCADOR).all()
