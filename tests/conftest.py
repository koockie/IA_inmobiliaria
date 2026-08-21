"""Fixtures compartidas: un dataset sintetico que cubre cada caso borde real.

Los casos borde no son inventados: salen de la verificacion empirica del
dataset (m2_util = 1,0, lon = -71,2193, arriendos de 194 millones, banos = 0,
nombres de barrio repetidos entre comunas, deptos de la misma torre).
"""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from ml import config

COLUMNAS = [
    "sitio", "id_aviso", "url", "operacion", "tipo", "comuna", "barrio", "direccion",
    "titulo", "precio_valor", "precio_moneda", "precio_clp", "precio_uf", "m2_util",
    "m2_total", "dormitorios", "banos", "estacionamientos", "bodegas",
    "antiguedad_anos", "ano_construccion", "gastos_comunes_clp",
    "antiguedad_aviso_dias", "fecha_publicacion", "lat", "lon", "descripcion",
    "publica", "detalle_ok", "fecha_scrape",
]

S = config.MARCADOR


def _fila(**kw) -> dict:
    """Fila valida de venta-departamento; los kwargs sobrescriben lo que haga falta."""
    base = {
        "sitio": "pi", "id_aviso": "1", "url": "http://x/1", "operacion": "venta",
        "tipo": "departamento", "comuna": "nunoa", "barrio": "plaza nunoa",
        "direccion": "Av Irarrazaval 100", "titulo": "Depto", "precio_valor": "3500",
        "precio_moneda": "UF", "precio_clp": "142956765", "precio_uf": "3500",
        "m2_util": "60", "m2_total": "70", "dormitorios": "2", "banos": "2",
        "estacionamientos": "1", "bodegas": "1", "antiguedad_anos": "11",
        "ano_construccion": "2015", "gastos_comunes_clp": "80000",
        "antiguedad_aviso_dias": "30", "fecha_publicacion": "2026-06-26",
        "lat": "-33.4550", "lon": "-70.6000", "descripcion": "d", "publica": S,
        "detalle_ok": 1, "fecha_scrape": "2026-07-26",
    }
    base.update({k: str(v) if not isinstance(v, int) else v for k, v in kw.items()})
    if "direccion" not in kw:
        base["direccion"] = f"Av Irarrazaval {base['id_aviso']}"
    return base


@pytest.fixture
def filas_crudas() -> list[dict]:
    """~30 filas con todos los casos borde que los filtros deben atrapar."""
    f = []
    # 8 ventas-depto sanas, 3 en la misma coordenada (misma torre).
    for i in range(8):
        lat = "-33.4550" if i < 3 else f"-33.45{60 + i}"
        f.append(_fila(id_aviso=f"ok{i}", precio_uf=3000 + i * 100,
                       precio_clp=(3000 + i * 100) * 40844.79,
                       m2_util=55 + i, lat=lat, direccion=f"Calle Sana {i}"))
    # Reparacion UF: en CLP sin precio_uf (el fallo del 27/07).
    f.append(_fila(id_aviso="sin_uf", precio_moneda="CLP", precio_valor="163379160",
                   precio_clp="163379160", precio_uf=S, fecha_scrape="2026-07-27"))
    # Reparacion inversa: en UF sin precio_clp (la mitad que el documento omite).
    f.append(_fila(id_aviso="sin_clp", precio_uf="4000", precio_clp=S,
                   fecha_scrape="2026-07-27"))
    # Outliers de superficie.
    f.append(_fila(id_aviso="m2_min", m2_util="1"))
    f.append(_fila(id_aviso="m2_max", m2_util="138000"))
    # m2_util > m2_total: se anula m2_total, la fila sobrevive.
    f.append(_fila(id_aviso="m2_incoherente", m2_util="80", m2_total="60"))
    # Coordenada a 70 km al oeste: se anula la geo, la fila sobrevive.
    f.append(_fila(id_aviso="geo_mala", lon="-71.2193"))
    # banos = 0 no existe fisicamente; dormitorios = 0 SI es valido en depto.
    f.append(_fila(id_aviso="banos_cero", banos="0"))
    f.append(_fila(id_aviso="monoambiente", dormitorios="0"))
    # gastos_comunes = 0: ambiguo en depto, cero real en casa.
    f.append(_fila(id_aviso="gc_cero_depto", gastos_comunes_clp="0"))
    f.append(_fila(id_aviso="gc_cero_casa", tipo="casa", gastos_comunes_clp="0",
                   m2_util="120", m2_total="200", precio_uf="8000",
                   precio_clp=8000 * 40844.79))
    # Duplicado de ok0 (misma direccion, m2 y precio) capturado el 27/07, el dia
    # en que fallo la UF: llega en CLP y su precio_uf hay que reconstruirlo.
    # Al desempatar debe perder frente al precio original de ok0.
    f.append(_fila(id_aviso="dup", direccion="Calle Sana 0", m2_util="55",
                   precio_moneda="CLP", precio_valor=3000 * 40844.79,
                   precio_clp=3000 * 40844.79, precio_uf=S,
                   fecha_scrape="2026-07-27"))
    # Mismo nombre de barrio en dos comunas distintas: no deben mezclarse.
    f.append(_fila(id_aviso="homonimo_a", comuna="nunoa", barrio="villa frei"))
    f.append(_fila(id_aviso="homonimo_b", comuna="macul", barrio="villa frei"))
    # Conteo del edificio en vez del de la unidad: un estudio no tiene 540
    # estacionamientos ni 95 bodegas.
    f.append(_fila(id_aviso="estac_edificio", m2_util="29", estacionamientos="540",
                   bodegas="95"))
    # Fila sin geo y sin direccion (como las de chilepropiedades).
    f.append(_fila(id_aviso="sin_geo", sitio="cp", lat=S, lon=S, direccion=S))
    # Arriendos: uno sano y uno contaminado (una venta etiquetada como arriendo).
    f.append(_fila(id_aviso="arr_ok", operacion="arriendo", precio_moneda="CLP",
                   precio_clp="470000", precio_uf="11.5", m2_util="46"))
    f.append(_fila(id_aviso="arr_contaminado", operacion="arriendo",
                   precio_moneda="CLP", precio_clp="194012752", precio_uf="4750",
                   m2_util="46"))
    return f


@pytest.fixture
def df_crudo(filas_crudas) -> pd.DataFrame:
    """DataFrame tal como sale de SQLite: todo texto, SIN_DATO como centinela."""
    df = pd.DataFrame(filas_crudas)
    for c in COLUMNAS:
        if c not in df.columns:
            df[c] = S
    return df[COLUMNAS]


@pytest.fixture
def db_muestra(tmp_path, df_crudo) -> str:
    """Materializa el fixture en un SQLite con el mismo tipado que el real."""
    ruta = tmp_path / "muestra.sqlite"
    con = sqlite3.connect(ruta)
    cols = ", ".join(
        f"{c} INTEGER" if c == "detalle_ok" else f"{c} TEXT" for c in COLUMNAS
    )
    con.execute(f"CREATE TABLE ofertas ({cols}, PRIMARY KEY (sitio, id_aviso))")
    con.executemany(
        f"INSERT INTO ofertas VALUES ({', '.join('?' * len(COLUMNAS))})",
        [tuple(r[c] for c in COLUMNAS) for r in df_crudo.to_dict("records")],
    )
    con.commit()
    con.close()
    return str(ruta)
