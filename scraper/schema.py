"""Esquema del registro normalizado del dataset de ofertas."""
from __future__ import annotations

# Orden de columnas del dataset final (SQLite y CSV)
COLUMNS = [
    "sitio",              # pi | toctoc
    "id_aviso",           # id único dentro del sitio (ej: 3585368896 de MLC-3585368896)
    "url",
    "operacion",          # venta | arriendo
    "tipo",               # casa | departamento
    "comuna",             # slug interno (nunoa, macul, la-florida, san-miguel)
    "barrio",
    "direccion",
    "titulo",
    "precio_valor",       # número tal como lo publica el aviso
    "precio_moneda",      # UF | CLP
    "precio_clp",         # normalizado a pesos (con UF del día)
    "precio_uf",          # normalizado a UF
    "m2_util",
    "m2_total",
    "dormitorios",
    "banos",
    "estacionamientos",
    "bodegas",
    "antiguedad_anos",
    "ano_construccion",
    "gastos_comunes_clp",
    "antiguedad_aviso_dias",  # "Publicado hace N días" (NULL en proyectos)
    "fecha_publicacion",      # fecha estimada = fecha visita - N días
    "lat",
    "lon",
    "descripcion",
    "publica",            # particular | profesional (sin datos personales)
    "detalle_ok",         # 0 = solo tarjeta, 1 = ficha de detalle visitada
    "fecha_scrape",
]


def empty_record() -> dict:
    return {col: None for col in COLUMNS}
