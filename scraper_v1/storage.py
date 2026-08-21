"""Persistencia del scraper v1: SQLite propio + export CSV + registro de excluidos."""
from __future__ import annotations

import csv
import sqlite3

from scraper.config import DATA_DIR
from scraper.schema import COLUMNS as COLUMNS_BASE
from scraper_v1.config import CSV_PATH, DB_PATH, EXCLUIDOS_CSV

# Esquema del v1: el de siempre + trazabilidad de la exclusión de proyectos
COLUMNS = COLUMNS_BASE + ["es_proyecto", "senales_proyecto"]

_LISTADO_FIELDS = [
    "url", "operacion", "tipo", "comuna", "barrio", "direccion", "titulo",
    "precio_valor", "precio_moneda", "precio_clp", "precio_uf",
    "m2_util", "dormitorios", "banos", "fecha_scrape",
]


def empty_record() -> dict:
    return {c: None for c in COLUMNS}


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cols_sql = ", ".join(
        f"{c} {'INTEGER' if c in ('detalle_ok', 'es_proyecto') else 'TEXT'}" for c in COLUMNS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS ofertas ({cols_sql}, "
                 "PRIMARY KEY (sitio, id_aviso))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_detalle ON ofertas (sitio, detalle_ok)")
    existentes = {r[1] for r in conn.execute("PRAGMA table_info(ofertas)")}
    for col in COLUMNS:
        if col not in existentes:
            tipo = "INTEGER" if col in ("detalle_ok", "es_proyecto") else "TEXT"
            conn.execute(f"ALTER TABLE ofertas ADD COLUMN {col} {tipo}")
    return conn


def upsert_listado(conn: sqlite3.Connection, rec: dict) -> None:
    rec = {**rec, "detalle_ok": rec.get("detalle_ok") or 0,
           "es_proyecto": rec.get("es_proyecto") or 0}
    placeholders = ", ".join("?" for _ in COLUMNS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in _LISTADO_FIELDS)
    conn.execute(
        f"INSERT INTO ofertas ({', '.join(COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(sitio, id_aviso) DO UPDATE SET {updates}",
        [rec.get(c) for c in COLUMNS])


def update_detalle(conn: sqlite3.Connection, sitio: str, id_aviso: str, campos: dict) -> None:
    campos = {**campos, "detalle_ok": 1}
    sets = ", ".join(f"{k}=?" for k in campos)
    conn.execute(f"UPDATE ofertas SET {sets} WHERE sitio=? AND id_aviso=?",
                 [*campos.values(), sitio, id_aviso])


def marcar_proyecto(conn: sqlite3.Connection, sitio: str, id_aviso: str,
                    senales: list[str]) -> None:
    """Marca un aviso como proyecto (queda en la BD pero fuera del CSV final)."""
    conn.execute("UPDATE ofertas SET es_proyecto=1, senales_proyecto=?, detalle_ok=1 "
                 "WHERE sitio=? AND id_aviso=?",
                 (" | ".join(senales), sitio, id_aviso))


def eliminar(conn: sqlite3.Connection, sitio: str, id_aviso: str) -> None:
    conn.execute("DELETE FROM ofertas WHERE sitio=? AND id_aviso=?", (sitio, id_aviso))


def pendientes_detalle(conn: sqlite3.Connection, sitio: str,
                       limit: int | None = None) -> list[tuple[str, str]]:
    """Fichas por visitar: excluye las ya marcadas como proyecto."""
    q = ("SELECT id_aviso, url FROM ofertas "
         "WHERE sitio=? AND detalle_ok=0 AND es_proyecto=0")
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q, (sitio,)).fetchall()


def resumen(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT sitio, comuna, operacion, tipo, COUNT(*), SUM(detalle_ok), SUM(es_proyecto) "
        "FROM ofertas GROUP BY sitio, comuna, operacion, tipo ORDER BY 1,2,3,4").fetchall()


def export_csv(conn: sqlite3.Connection) -> int:
    """Exporta SOLO las viviendas individuales (es_proyecto = 0)."""
    rows = conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM ofertas WHERE es_proyecto=0").fetchall()
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerows(rows)
    return len(rows)


def export_excluidos(conn: sqlite3.Connection) -> int:
    """Deja constancia de qué proyectos se excluyeron y por qué señal."""
    rows = conn.execute(
        "SELECT id_aviso, titulo, comuna, operacion, tipo, precio_valor, precio_moneda, "
        "m2_util, dormitorios, senales_proyecto, url FROM ofertas WHERE es_proyecto=1"
    ).fetchall()
    with EXCLUIDOS_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id_aviso", "titulo", "comuna", "operacion", "tipo", "precio_valor",
                    "precio_moneda", "m2_util", "dormitorios", "senales_proyecto", "url"])
        w.writerows(rows)
    return len(rows)
