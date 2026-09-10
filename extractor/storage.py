"""Persistencia de las consultas del usuario.

En una base **aparte** de la de entrenamiento, a proposito: los avisos que trae
un usuario no deben mezclarse en silencio con el dataset con el que se entrenaron
los modelos. Si algun dia se reentrena con estos datos, esa tiene que ser una
decision explicita y no un efecto colateral del MVP.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config as C
from .validate import COLUMNAS

_EXTRA = ["advertencias", "fuera_de_cobertura"]
_TODAS = COLUMNAS + _EXTRA


def abrir(ruta: Path | None = None) -> sqlite3.Connection:
    destino = Path(ruta) if ruta else C.DB_CONSULTAS
    destino.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(destino)
    conn.execute("PRAGMA journal_mode=WAL")
    _crear(conn)
    return conn


def _crear(conn: sqlite3.Connection) -> None:
    cols = []
    for c in _TODAS:
        if c in ("detalle_ok", "es_proyecto", "fuera_de_cobertura"):
            cols.append(f"{c} INTEGER")
        elif c in ("precio_valor", "precio_clp", "precio_uf", "m2_util", "m2_total",
                   "gastos_comunes_clp", "lat", "lon", "uf_usada"):
            cols.append(f"{c} REAL")
        elif c in ("dormitorios", "banos", "estacionamientos", "bodegas",
                   "antiguedad_anos", "ano_construccion"):
            cols.append(f"{c} INTEGER")
        else:
            cols.append(f"{c} TEXT")
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS consultas ({', '.join(cols)}, "
        "PRIMARY KEY (sitio, id_aviso))")

    # Migracion: si el esquema crecio desde la ultima corrida, se agregan las
    # columnas que falten en vez de fallar al insertar.
    existentes = {r[1] for r in conn.execute("PRAGMA table_info(consultas)")}
    for definicion in cols:
        nombre = definicion.split()[0]
        if nombre not in existentes:
            conn.execute(f"ALTER TABLE consultas ADD COLUMN {definicion}")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_consulta ON consultas (fecha_consulta)")
    conn.commit()


def guardar(conn: sqlite3.Connection, registro: dict) -> None:
    """Upsert sobre (sitio, id_aviso): reconsultar el mismo aviso lo actualiza en
    vez de duplicarlo, igual que hacia `scraper/storage.py:39-48`."""
    fila = dict(registro)
    fila["advertencias"] = json.dumps(fila.get("advertencias") or [], ensure_ascii=False)
    fila["fuera_de_cobertura"] = int(bool(fila.get("fuera_de_cobertura")))

    valores = [fila.get(c) for c in _TODAS]
    marcas = ", ".join("?" * len(_TODAS))
    actualiza = ", ".join(f"{c}=excluded.{c}" for c in _TODAS
                          if c not in ("sitio", "id_aviso"))
    conn.execute(
        f"INSERT INTO consultas ({', '.join(_TODAS)}) VALUES ({marcas}) "
        f"ON CONFLICT(sitio, id_aviso) DO UPDATE SET {actualiza}", valores)
    conn.commit()


def leer(conn: sqlite3.Connection, sitio: str, id_aviso: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    fila = conn.execute(
        "SELECT * FROM consultas WHERE sitio=? AND id_aviso=?",
        (sitio, id_aviso)).fetchone()
    if fila is None:
        return None
    d = dict(fila)
    d["advertencias"] = json.loads(d.get("advertencias") or "[]")
    d["fuera_de_cobertura"] = bool(d.get("fuera_de_cobertura"))
    return d
