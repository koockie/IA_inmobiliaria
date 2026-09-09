"""Verificacion del extractor, sin red.

Los fixtures son HTML real guardado (comprimido), no maquetas: los tests corren
offline y no le piden nada al portal, pero prueban contra lo que el portal
entrega de verdad.

    ./.venv/Scripts/python.exe -m pytest tests/test_extractor.py -v
"""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from extractor import storage                                       # noqa: E402
from extractor.fetch import es_challenge                            # noqa: E402
from extractor.normalize import es_rango, numero, precios           # noqa: E402
from extractor.parse import extraer                                 # noqa: E402
from extractor.urls import UrlInvalida, analizar                    # noqa: E402
from extractor.validate import construir, normalizar_comuna         # noqa: E402

FIXTURES = RAIZ / "tests" / "fixtures"


def ficha(nombre: str) -> str:
    with gzip.open(FIXTURES / f"{nombre}.html.gz", "rt", encoding="utf-8",
                   errors="replace") as f:
        return f.read()


def registro(nombre: str, url: str) -> dict:
    return construir(analizar(url), extraer(ficha(nombre)))


CASA = "https://casa.mercadolibre.cl/MLC-2130634117-increible-casa-_JM"
PROYECTO = "https://portalinmobiliario.com/MLC-3585368896-castillo-velasco-_JM"
DEPTO = "https://portalinmobiliario.com/MLC-4228882382-arriendo-2d2b-macul-_JM"


# --- URLs -------------------------------------------------------------------
def test_acepta_los_dos_dominios():
    """Portal Inmobiliario y MercadoLibre son la misma plataforma y el id es el
    mismo; el extractor debe aceptar las dos formas."""
    assert analizar(CASA).sitio == "ml"
    assert analizar(PROYECTO).sitio == "pi"


def test_descarta_query_y_fragmento():
    sucia = CASA + "#polycard_client=search&position=1&tracking_id=abc"
    assert analizar(sucia).url == CASA


@pytest.mark.parametrize("url", [
    "https://portalinmobiliario.com/venta/departamento/nunoa-metropolitana",
    "https://www.mercadolibre.cl/perfil/ALGUIEN",
    "https://www.zonaprop.cl/propiedades/algo-123.html",
    "",
])
def test_rechaza_lo_que_no_es_ficha(url):
    with pytest.raises(UrlInvalida):
        analizar(url)


# --- parseo -----------------------------------------------------------------
def test_casa_en_venta_completa():
    r = registro("ml_casa_venta", CASA)
    assert (r["operacion"], r["tipo"], r["comuna"]) == ("venta", "casa", "nunoa")
    assert (r["m2_util"], r["m2_total"]) == (173.0, 458.0)
    assert (r["dormitorios"], r["banos"], r["estacionamientos"]) == (6, 3, 4)
    assert r["es_proyecto"] == 0
    assert not r["advertencias"]


def test_clf_es_uf_no_pesos():
    """El portal publica la moneda como `CLF`, el codigo ISO de la UF. Leerlo como
    pesos dejaria el analisis 40.000 veces mal."""
    r = registro("ml_casa_venta", CASA)
    assert r["precio_moneda"] == "UF"
    assert r["precio_valor"] == 11900.0
    assert r["precio_clp"] > 400_000_000


def test_departamento_en_arriendo_trae_gastos_comunes():
    r = registro("pi_depto_arriendo", DEPTO)
    assert (r["operacion"], r["tipo"], r["comuna"]) == ("arriendo", "departamento", "macul")
    assert r["precio_moneda"] == "CLP" and r["precio_valor"] == 450000.0
    assert r["gastos_comunes_clp"] == 90000.0
    assert (r["dormitorios"], r["banos"]) == (2, 2)


def test_coordenada_es_la_del_mapa_no_el_senuelo():
    """El HTML trae un `"latitude": -35.67` que es el centro geografico de Chile.
    Tomarlo en vez del centro del mapa seria un error silencioso de ~250 km."""
    for nombre, url in (("ml_casa_venta", CASA), ("pi_depto_arriendo", DEPTO)):
        r = registro(nombre, url)
        assert -33.70 <= r["lat"] <= -33.40, nombre
        assert -70.70 <= r["lon"] <= -70.45, nombre


# --- proyectos: la regla de no inventar -------------------------------------
def test_proyecto_no_inventa_valores():
    """Este aviso es el que produjo el `m2_util=21` con `m2_total=85` en la base
    historica: el scraper anterior tomaba el minimo del rango."""
    r = registro("pi_proyecto", PROYECTO)
    assert r["es_proyecto"] == 1
    for campo in ("m2_util", "m2_total", "dormitorios", "banos"):
        assert r[campo] is None, f"{campo} deberia quedar vacio en un proyecto"
    assert any("rango" in a for a in r["advertencias"])
    # El precio y la ubicacion si son de la ficha, no de una unidad: se conservan.
    assert r["precio_valor"] == 6471.0 and r["lat"] is not None


@pytest.mark.parametrize("texto,esperado", [
    ("21.5 m² a 239.48 m²", True), ("85.4 - 239.48 m²", True), ("1 a 3", True),
    ("458 m²", False), ("6", False), ("86 años", False),
])
def test_deteccion_de_rangos(texto, esperado):
    assert es_rango(texto) is esperado


# --- numeros y precios ------------------------------------------------------
@pytest.mark.parametrize("texto,esperado", [
    ("458 m²", 458.0), ("1.234.567", 1234567.0), ("1.234,56", 1234.56),
    ("21.5 m²", 21.5), ("$ 486.476.332", 486476332.0), ("Inmediata", None),
])
def test_formato_chileno(texto, esperado):
    assert numero(texto) == esperado


def test_conversion_bidireccional():
    assert precios(100.0, "UF", 40000.0) == (4_000_000, 100.0)
    assert precios(400_000.0, "CLP", 40000.0) == (400_000, 10.0)


def test_sin_uf_el_registro_sobrevive():
    """Cuando mindicador.cl fallo, el scraper anterior cacheo el `None` y perdio
    3.804 filas. Sin UF debe perderse solo la columna derivada."""
    clp, uf = precios(11900.0, "UF", None)
    assert clp is None and uf == 11900.0


# --- comunas y cobertura ----------------------------------------------------
@pytest.mark.parametrize("nombre,slug", [
    ("Ñuñoa", "nunoa"), ("nunoa", "nunoa"), ("La Florida", "la-florida"),
    ("San Miguel", "san-miguel"), ("Macul", "macul"), ("Providencia", None),
])
def test_normalizacion_de_comuna(nombre, slug):
    assert normalizar_comuna(nombre) == slug


def test_fuera_de_cobertura_avisa_en_vez_de_tasar_a_ciegas():
    crudo = extraer(ficha("ml_casa_venta"))
    crudo["comuna"] = "Providencia"
    r = construir(analizar(CASA), crudo)
    assert r["fuera_de_cobertura"] is True
    assert any("cobertura" in a for a in r["advertencias"])


# --- sanidad ----------------------------------------------------------------
def test_superficie_util_mayor_que_total_se_descarta():
    crudo = extraer(ficha("ml_casa_venta"))
    crudo["specs"] = {"Superficie útil": "173 m²", "Superficie total": "85 m²"}
    r = construir(analizar(CASA), crudo)
    assert r["m2_util"] == 173.0 and r["m2_total"] is None
    assert any("supera la total" in a for a in r["advertencias"])


def test_coordenadas_fuera_de_santiago_se_descartan():
    crudo = extraer(ficha("ml_casa_venta"))
    crudo["lat"], crudo["lon"] = "-35.675148", "-71.54297"
    r = construir(analizar(CASA), crudo)
    assert r["lat"] is None and r["lon"] is None
    assert any("fuera de Santiago" in a for a in r["advertencias"])


# --- deteccion de bloqueo ---------------------------------------------------
def test_challenge_no_se_confunde_con_ficha_vacia():
    """El punto ciego del scraper anterior: una pagina de verificacion responde
    200 igual que una ficha, y se parseaba como 'no habia datos'."""
    assert es_challenge("<html>Antes de continuar, verifica que eres humano</html>")
    assert es_challenge("x" * 300_000)          # grande pero sin bloque de datos
    assert not es_challenge(ficha("ml_casa_venta"))


# --- persistencia -----------------------------------------------------------
def test_guardar_es_idempotente(tmp_path):
    ruta = tmp_path / "consultas.sqlite"
    r = registro("ml_casa_venta", CASA)
    conn = storage.abrir(ruta)
    try:
        storage.guardar(conn, r)
        storage.guardar(conn, r)
        assert conn.execute("SELECT COUNT(*) FROM consultas").fetchone()[0] == 1
        vuelta = storage.leer(conn, r["sitio"], r["id_aviso"])
        assert vuelta["m2_util"] == 173.0
        assert isinstance(vuelta["advertencias"], list)
    finally:
        conn.close()
