"""Constantes de configuracion. Sin I/O, sin pandas: importable en cualquier contexto."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "ofertas_unificado.sqlite"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"

RANDOM_STATE = 42
MARCADOR = "SIN_DATO"          # centinela de faltante en el dataset (limpiar_dataset.py:50)

# Ano fijo, no date.today().year: el feature `antiguedad` debe ser reproducible
# aunque el modelo se re-entrene el ano que viene.
ANIO_REFERENCIA = 2026

# Mediana empirica de precio_clp/precio_uf sobre las 8.959 filas que tienen ambos
# precios. Es preferible a consultar mindicador.cl, que devolveria la UF de hoy y
# no la del 26-27/07/2026 que es cuando se capturaron los datos.
UF_FALLBACK_CLP = 40_844.79
UF_BANDA_VALIDA = (39_000.0, 43_000.0)   # la UF vario 0,16% en la ventana de scrape

TARGET = {"venta": "precio_uf", "arriendo": "precio_clp"}
OPERACIONES = ("venta", "arriendo")
TIPOS = ("casa", "departamento")
COMUNAS = ("macul", "la-florida", "nunoa", "san-miguel")

# --------------------------------------------------------------------------
# Columnas que NUNCA pueden entrar al modelo.
# --------------------------------------------------------------------------
# `precio_clp` y `precio_uf`: en venta el target es precio_uf y precio_clp es
#   literalmente el target multiplicado por la UF (y viceversa en arriendo).
# `precio_valor`: el mismo precio en la moneda original.
# `antiguedad_aviso_dias`: un aviso lleva 300 dias publicado *porque* esta caro.
#   Es consecuencia del precio, no causa. Se conserva en el DataFrame para
#   diagnostico de zombis, pero jamas llega al estimador.
# `fecha_publicacion`: biyeccion exacta con antiguedad_aviso_dias dado
#   fecha_scrape (que solo tiene 3 valores). Excluir una y dejar la otra seria
#   dejar la misma puerta abierta.
# `uf_por_m2`: es target/m2_util.
# `publica`: 100% vacia en las 15.808 filas.
COLUMNAS_PROHIBIDAS = frozenset({
    "precio_valor", "precio_moneda", "precio_clp", "precio_uf",
    "antiguedad_aviso_dias", "fecha_publicacion",
    "uf_por_m2", "clp_por_m2",
    "publica",
    "id_aviso", "url", "titulo", "descripcion", "detalle_ok", "fecha_scrape",
    "direccion",          # texto libre; se usa solo como clave de agrupacion espacial
    "precio_origen",      # columna de auditoria de la reparacion UF
})

# Caja que contiene a las 4 comunas. El dataset trae lon minimo -71,2193, unos
# 70 km al oeste de Santiago: es una coordenada rota.
BBOX_LAT = (-33.62, -33.40)
BBOX_LON = (-70.72, -70.48)

# 0,0001 grados = ~11 m de latitud y ~9 m de longitud a -33,5: la huella de un
# edificio, que es la unidad de fuga que importa (deptos de la misma torre en
# train y test). A 3 decimales (~110 m) el 89,7% de las filas queda encadenado.
GEO_DECIMALES = 4
CV_N_SPLITS = 5
BARRIO_MIN_FREQ = 20          # bajo este umbral, (comuna,barrio) colapsa a OTROS


@dataclass(frozen=True)
class Umbrales:
    """Rangos de validez por segmento. Fuera de rango se elimina o se anula."""
    m2_util: tuple[float, float]
    precio: tuple[float, float]
    dormitorios: tuple[int, int]
    banos: tuple[int, int]
    estacionamientos: tuple[int, int]
    bodegas: tuple[int, int]


# Estacionamientos y bodegas necesitan tope porque algunos avisos reportan el
# conteo del EDIFICIO entero en vez del de la unidad: hay estudios de 29 m2 con
# 540 estacionamientos y 95 bodegas. Son 115 filas en venta-departamento (1,8%)
# y el modelo las leia como una caracteristica cara de la propiedad.
UMBRALES: dict[tuple[str, str], Umbrales] = {
    ("venta", "departamento"):    Umbrales((20, 400), (500, 60_000), (0, 8), (1, 8), (0, 6), (0, 4)),
    ("venta", "casa"):            Umbrales((30, 800), (500, 60_000), (1, 10), (1, 10), (0, 10), (0, 6)),
    ("arriendo", "departamento"): Umbrales((15, 300), (150_000, 4_000_000), (0, 8), (1, 8), (0, 6), (0, 4)),
    ("arriendo", "casa"):         Umbrales((30, 600), (150_000, 4_000_000), (1, 10), (1, 10), (0, 10), (0, 6)),
}

ANIO_CONSTRUCCION_VALIDO = (1900, 2027)
GASTOS_COMUNES_MAX = 3_000_000
RECORTE_PERCENTILES = (1, 99)      # sobre precio/m2 dentro de (comuna, tipo)
RECORTE_N_MINIMO = 50              # grupos mas chicos usan los percentiles globales

# Umbrales de los criterios de aceptacion (PLAN_MODELO_ML.md seccion 10)
META_MDAPE_VENTA = 20.0
META_MDAPE_ARRIENDO = 25.0
META_PPE10_VENTA = 40.0
MDAPE_SOSPECHOSO = 5.0             # por debajo de esto se asume leakage

# Rangos del estandar IAAO (Standard on Ratio Studies)
IAAO_COD = (5.0, 15.0)
IAAO_PRD = (0.98, 1.03)
IAAO_PRB = (-0.05, 0.05)

# Sesgos estructurales del dataset. Se serializan en cada artefacto: no se
# pueden corregir, pero deben quedar declarados junto a las metricas.
SESGOS_DECLARADOS = [
    "Precios de publicacion, no de cierre. En Chile el sesgo tipico es 5-15% sobre "
    "el precio final de venta, asi que el modelo estima 'precio pedido esperado'.",
    "Sesgo de seleccion invertido: el dataset es una foto del stock publicado. Lo "
    "bien valorado se vende rapido y desaparece; lo sobrevalorado se acumula.",
    "Truncamiento a 2.016 resultados por busqueda (documentacion.md seccion 8). "
    "Afecta a departamentos en venta de Nunoa y San Miguel, el segmento mas grande "
    "del modelo de venta.",
    "El modelo de venta depende de una sola fuente (portalinmobiliario): las 1.346 "
    "filas de chilepropiedades son exclusivamente arriendo-departamento.",
    "Sin dispersion temporal: 3 fechas de scrape en una ventana de 15 dias y la UF "
    "vario 0,16%. NO se aplica ajuste temporal de precios; deflactar por "
    "fecha_publicacion confundiria antiguedad del aviso con epoca del precio.",
]
