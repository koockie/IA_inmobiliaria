r"""UNIFICAR DATASETS — agrega avisos de otra fuente al dataset principal.

Toma el dataset principal (`data/ofertas_limpio.sqlite`) y le suma las filas de un CSV
externo, traduciendo sus columnas al esquema estándar de 30 columnas del proyecto.

Fuente soportada: chilepropiedades.cl (`parsedChilePropiedades.csv`).
Para sumar otra fuente, basta agregar su mapeo en MAPEOS.

USO
---
    # ver qué se agregaría, sin modificar nada
    .\.venv\Scripts\python.exe unificar_dataset.py

    # aplicar la unión
    .\.venv\Scripts\python.exe unificar_dataset.py --aplicar

    Opcionales:
      --csv <ruta>       CSV externo (default: data/parsedChilePropiedades.csv)
      --fuente cp        clave del mapeo a usar (default: cp)
      --base <ruta>      base principal (default: data/ofertas_limpio.sqlite)
      --marcador TEXTO   relleno de celdas sin dato (default: SIN_DATO)

SALIDAS
-------
    data/ofertas_unificado.sqlite
    data/ofertas_unificado.csv

La base principal NO se modifica: se copia y se trabaja sobre la copia.
"""
from __future__ import annotations

import csv
import shutil
import sqlite3
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

DATA = Path(__file__).parent / "data"
BASE_IN = DATA / "ofertas_limpio.sqlite"
CSV_EXTERNO = DATA / "parsedChilePropiedades.csv"
DB_OUT = DATA / "ofertas_unificado.sqlite"
CSV_OUT = DATA / "ofertas_unificado.csv"
MARCADOR = "SIN_DATO"

# Comunas del proyecto: "Ñuñoa" -> "nunoa"
COMUNAS = {"nunoa": "nunoa", "la florida": "la-florida",
           "san miguel": "san-miguel", "macul": "macul"}


def slug_comuna(v: str) -> str | None:
    s = unicodedata.normalize("NFKD", (v or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return COMUNAS.get(s)


def num(v, entero=False):
    """'2.0' -> 2 (o 2.0). Devuelve None si no es número."""
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(f) if entero else f


def fecha_iso(v: str) -> str | None:
    """'26/07/2026' -> '2026-07-26'"""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime((v or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def mapear_chilepropiedades(r: dict) -> dict | None:
    """Traduce una fila de chilepropiedades.cl al esquema estándar."""
    comuna = slug_comuna(r.get("comuna"))
    if not comuna:                       # comuna fuera del alcance del proyecto
        return None

    # "arriendo-mensual" -> arriendo | "venta" -> venta
    tp = (r.get("tipo_publicacion") or "").lower()
    operacion = "arriendo" if "arriendo" in tp else ("venta" if "venta" in tp else None)
    tipo = (r.get("tipo_propiedad") or "").lower().strip()
    if tipo not in ("casa", "departamento") or not operacion:
        return None

    precio_clp = num(r.get("precio_clp"))
    precio_uf = num(r.get("precio_uf"))
    fpub = fecha_iso(r.get("fecha_publicacion"))
    dias = (date.today() - date.fromisoformat(fpub)).days if fpub else None

    return {
        "sitio": "cp",                                   # chilepropiedades.cl
        "id_aviso": (r.get("codigo_aviso") or "").strip(),
        "url": r.get("url"),
        "operacion": operacion,
        "tipo": tipo,
        "comuna": comuna,
        "titulo": r.get("titulo"),
        # los arriendos vienen publicados en pesos
        "precio_valor": precio_clp,
        "precio_moneda": "CLP" if precio_clp else None,
        "precio_clp": precio_clp,
        "precio_uf": precio_uf,
        "m2_util": num(r.get("superficie_m2"), entero=True),
        "dormitorios": num(r.get("habitaciones"), entero=True),
        "banos": num(r.get("banos"), entero=True),
        "estacionamientos": num(r.get("estacionamientos"), entero=True),
        "antiguedad_aviso_dias": dias,
        "fecha_publicacion": fpub,
        "detalle_ok": 0,
        "fecha_scrape": date.today().isoformat(),
    }


MAPEOS = {"cp": ("chilepropiedades.cl", mapear_chilepropiedades)}


def main() -> None:
    def arg(flag, default):
        return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default

    base = Path(arg("--base", BASE_IN))
    externo = Path(arg("--csv", CSV_EXTERNO))
    clave = arg("--fuente", "cp")
    marcador = arg("--marcador", MARCADOR)
    aplicar = "--aplicar" in sys.argv

    if clave not in MAPEOS:
        raise SystemExit(f"Fuente desconocida: {clave}. Disponibles: {list(MAPEOS)}")
    nombre_fuente, mapear = MAPEOS[clave]
    for p in (base, externo):
        if not p.exists():
            raise SystemExit(f"No existe: {p}")

    # ── Esquema de la base principal ──
    conn = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
    columnas = [r[1] for r in conn.execute("PRAGMA table_info(ofertas)")]
    n_base = conn.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0]
    ids_base = {(s, i) for s, i in conn.execute("SELECT sitio, id_aviso FROM ofertas")}
    conn.close()

    print(f"Base principal : {base.name}  ({n_base} filas, {len(columnas)} columnas)")
    print(f"Fuente externa : {externo.name}  [{nombre_fuente}]")

    # ── Leer y mapear el CSV externo ──
    with externo.open(encoding="utf-8-sig", newline="") as fh:
        filas_ext = list(csv.DictReader(fh))

    nuevas, descartadas, repetidas = [], 0, 0
    for r in filas_ext:
        m = mapear(r)
        if m is None:
            descartadas += 1
            continue
        if (m["sitio"], m["id_aviso"]) in ids_base:
            repetidas += 1
            continue
        # completar el resto de columnas del esquema
        fila = {c: m.get(c, marcador) for c in columnas}
        for c, v in fila.items():
            if v is None or v == "":
                fila[c] = marcador
        fila["detalle_ok"] = 0
        nuevas.append(fila)

    print(f"\nFilas en el CSV externo : {len(filas_ext)}")
    print(f"  se agregarán          : {len(nuevas)}")
    print(f"  descartadas           : {descartadas}  (comuna/tipo/operación fuera de alcance)")
    print(f"  ya existían           : {repetidas}")

    # Cobertura de columnas de la nueva fuente
    if nuevas:
        print("\nCobertura de columnas en las filas nuevas:")
        con_dato = [c for c in columnas
                    if sum(1 for f in nuevas if f[c] != marcador) > len(nuevas) * 0.5]
        sin_dato = [c for c in columnas if c not in con_dato]
        print(f"  con dato ({len(con_dato)}): {', '.join(con_dato)}")
        print(f"  SIN_DATO ({len(sin_dato)}): {', '.join(sin_dato)}")

    if not aplicar:
        print("\n  (modo revisión: no se modificó nada)")
        print("  Para aplicar:  python unificar_dataset.py --aplicar\n")
        return

    # ── Aplicar: copiar la base y agregar ──
    print(f"\nUnificando -> {DB_OUT.name}")
    shutil.copy2(base, DB_OUT)
    out = sqlite3.connect(DB_OUT)
    placeholders = ", ".join("?" for _ in columnas)
    out.executemany(
        f"INSERT OR IGNORE INTO ofertas ({', '.join(columnas)}) VALUES ({placeholders})",
        [[f[c] for c in columnas] for f in nuevas])
    out.commit()

    total = out.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0]
    rows = out.execute(f"SELECT {', '.join(columnas)} FROM ofertas").fetchall()
    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(columnas)
        w.writerows(rows)

    print(f"   filas: {n_base} + {len(nuevas)} = {total}")
    print("\n   Composición del dataset unificado:")
    print(f"     {'sitio':<8}{'operacion':<11}{'tipo':<14}{'filas':>7}")
    for s, o, t, n in out.execute(
            "SELECT sitio, operacion, tipo, COUNT(*) FROM ofertas "
            "GROUP BY 1,2,3 ORDER BY 1,2,3"):
        print(f"     {s:<8}{o:<11}{t:<14}{n:>7}")
    out.close()

    print(f"\n   -> {DB_OUT}")
    print(f"   -> {CSV_OUT}")
    print(f"   La base {base.name} quedó intacta.\n")


if __name__ == "__main__":
    main()
