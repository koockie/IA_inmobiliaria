"""Persistencia: SQLite incremental (dedupe/resume) + export a CSV."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from scraper.config import CSV_PATH, DATA_DIR, DB_PATH
from scraper.schema import COLUMNS

# Campos que llegan del listado (pasada A). El resto viene de la ficha (pasada B).
_LISTADO_FIELDS = [
    "url", "operacion", "tipo", "comuna", "barrio", "direccion", "titulo",
    "precio_valor", "precio_moneda", "precio_clp", "precio_uf",
    "m2_util", "dormitorios", "banos", "fecha_scrape",
]


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cols_sql = ", ".join(
        f"{c} {'INTEGER' if c == 'detalle_ok' else 'TEXT'}" for c in COLUMNS
    )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS ofertas ({cols_sql}, "
        "PRIMARY KEY (sitio, id_aviso))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_detalle ON ofertas (sitio, detalle_ok)")
    # Migración: agregar columnas nuevas a bases creadas con un esquema anterior
    existentes = {row[1] for row in conn.execute("PRAGMA table_info(ofertas)")}
    for col in COLUMNS:
        if col not in existentes:
            tipo = "INTEGER" if col == "detalle_ok" else "TEXT"
            conn.execute(f"ALTER TABLE ofertas ADD COLUMN {col} {tipo}")
    return conn


def upsert_listado(conn: sqlite3.Connection, rec: dict) -> None:
    """Inserta el aviso o refresca sus campos de listado (sin pisar el detalle)."""
    rec = {**rec, "detalle_ok": rec.get("detalle_ok") or 0}
    placeholders = ", ".join("?" for _ in COLUMNS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in _LISTADO_FIELDS)
    conn.execute(
        f"INSERT INTO ofertas ({', '.join(COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(sitio, id_aviso) DO UPDATE SET {updates}",
        [rec.get(c) for c in COLUMNS],
    )


def update_detalle(conn: sqlite3.Connection, sitio: str, id_aviso: str, campos: dict) -> None:
    campos = {**campos, "detalle_ok": 1}
    sets = ", ".join(f"{k}=?" for k in campos)
    conn.execute(
        f"UPDATE ofertas SET {sets} WHERE sitio=? AND id_aviso=?",
        [*campos.values(), sitio, id_aviso],
    )


def pendientes_detalle(conn: sqlite3.Connection, sitio: str, limit: int | None = None) -> list[tuple[str, str]]:
    q = "SELECT id_aviso, url FROM ofertas WHERE sitio=? AND detalle_ok=0"
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q, (sitio,)).fetchall()


def resumen(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT sitio, comuna, operacion, tipo, COUNT(*), SUM(detalle_ok) "
        "FROM ofertas GROUP BY sitio, comuna, operacion, tipo ORDER BY 1,2,3,4"
    ).fetchall()


def export_csv(conn: sqlite3.Connection, path: Path = CSV_PATH) -> int:
    rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM ofertas").fetchall()
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return len(rows)
