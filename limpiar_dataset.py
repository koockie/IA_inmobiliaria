r"""LIMPIEZA DEL DATASET — elimina proyectos y rellena vacíos.

Dos tareas, ambas sobre `data/ofertas_sinduplicados.sqlite` (nunca lo modifica: trabaja
sobre una copia).

1) PROYECTOS  Un aviso de proyecto agrupa varias viviendas: sus superficies, dormitorios,
   baños y precio vienen como RANGOS y el scraper guardó el mínimo de cada uno. La fila
   resultante describe una vivienda que no existe (ej. "Castillo Velasco": 21 m² útiles
   con precio de UF 5.500, que en realidad es el "desde" de otra unidad).

2) VACÍOS     Las celdas sin dato quedan como NULL, que en Excel se ve igual que un cero
   o un texto vacío. Se reemplazan por un marcador explícito.

USO
---
    # 1. Ver qué se detectaría (no modifica nada)
    .\.venv\Scripts\python.exe limpiar_dataset.py

    # 2. Aplicar la limpieza (crea archivos nuevos)
    .\.venv\Scripts\python.exe limpiar_dataset.py --aplicar

    Opcionales:
      --db <ruta>            base de entrada (default: data/ofertas_sinduplicados.sqlite)
      --sin-relleno          elimina proyectos pero deja los vacíos como NULL
      --solo-relleno         solo rellena vacíos, no elimina proyectos
      --marcador SIN_DATO    texto para las celdas vacías (default: SIN_DATO)

SALIDAS
-------
    data/proyectos_detectados.csv     candidatos con sus señales (para revisar a mano)
    data/ofertas_limpio.sqlite        base limpia          (solo con --aplicar)
    data/ofertas_limpio.csv           dataset final        (solo con --aplicar)
"""
from __future__ import annotations

import csv
import re
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

DATA = Path(__file__).parent / "data"
DB_IN = DATA / "ofertas_sinduplicados.sqlite"
DB_OUT = DATA / "ofertas_limpio.sqlite"
CSV_OUT = DATA / "ofertas_limpio.csv"
REPORTE = DATA / "proyectos_detectados.csv"

MARCADOR = "SIN_DATO"

# Inmobiliarias y constructoras chilenas: su nombre en el título delata un proyecto.
INMOBILIARIAS = [
    "socovesa", "ingevec", "fundamenta", "almagro", "isacorp", "aconcagua", "euro",
    "paz corp", "pazcorp", "simonetti", "manquehue", "armas", "brotec", "icafal",
    "echeverria izquierdo", "guzman larrain", "siena", "valmar", "enaco", "actual",
    "numancia", "ssilva", "norte verde", "altas cumbres", "cypco", "bricsa", "dlp",
    "inmobiliaria", "constructora", "desarrollos", "urbanika", "exxacon", "avellaneda",
]

# Palabras con que suelen bautizarse los proyectos.
PALABRAS_PROYECTO = [
    "edificio", "condominio", "townhouse", "concepto", "parque", "altos de", "alto ",
    "terrazas de", "mirador de", "vista ", "eco ", "urbano", "smart", "home", "life",
    "plaza ", "portal ", "jardines de", "residencial", "barrio ", "distrito",
]

# Marcas de aviso individual: si aparecen, casi seguro NO es un proyecto.
MARCAS_INDIVIDUAL = [
    "en venta", "se vende", "vendo", "en arriendo", "se arrienda", "arriendo",
    "oportunidad", "id:", "rebajad", "impecable", "hermosa casa", "amplia casa",
]


def normalizar(t: str | None) -> str:
    if not t:
        return ""
    s = unicodedata.normalize("NFKD", str(t).lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def señales_proyecto(f: dict) -> list[str]:
    """Señales de que la fila corresponde a un proyecto (no a una vivienda concreta)."""
    s: list[str] = []
    titulo = normalizar(f["titulo"])

    # 1. Firma estructural: los proyectos no informan estos campos porque varían
    #    según la unidad (o no aplican todavía por ser obra nueva).
    if (f["fecha_publicacion"] is None and f["ano_construccion"] is None
            and f["gastos_comunes_clp"] is None and f["estacionamientos"] is None
            and f["bodegas"] is None):
        s.append("firma_5_campos_vacios")

    # 2. Nombre de inmobiliaria/constructora en el título
    if any(x in titulo for x in INMOBILIARIAS):
        s.append("inmobiliaria_en_titulo")

    # 3. Título con forma de nombre de proyecto y sin marcas de aviso individual
    tiene_marca_individual = any(x in titulo for x in MARCAS_INDIVIDUAL)
    if not tiene_marca_individual:
        if any(titulo.startswith(p) or f" {p}" in titulo for p in PALABRAS_PROYECTO):
            s.append("nombre_de_proyecto")
        # títulos cortos sin dormitorios ni operación: "Castillo Velasco", "Macul 3803"
        elif len(titulo.split()) <= 4 and not re.search(r"\d\s*[dh]\b", titulo):
            s.append("titulo_corto_tipo_nombre")

    # 4. Superficies incoherentes: el parser tomó el mínimo de dos rangos distintos
    m2u, m2t = fnum(f["m2_util"]), fnum(f["m2_total"])
    if m2u and m2t and f["tipo"] == "departamento" and m2t > 1.8 * m2u:
        s.append("superficies_incoherentes")
    if m2u and m2u < 22:
        s.append("m2_util_minimo_de_rango")

    return s


def clasificar(s: list[str], f: dict) -> str | None:
    """ALTA solo si hay evidencia sólida; el resto queda para revisión manual."""
    firma = "firma_5_campos_vacios" in s
    nombre = ("inmobiliaria_en_titulo" in s or "nombre_de_proyecto" in s
              or "titulo_corto_tipo_nombre" in s)
    # Un proyecto de obra nueva se VENDE. Si es arriendo, casi seguro es un aviso
    # individual con título parecido: no se elimina, se deja para revisión.
    es_venta = f["operacion"] == "venta"

    if firma and nombre and es_venta:
        return "ALTA"
    if firma and (nombre or es_venta):
        return "MEDIA"
    if len(s) >= 3:
        return "MEDIA"
    if s:
        return "BAJA"
    return None


def main() -> None:
    db_in = Path(sys.argv[sys.argv.index("--db") + 1]) if "--db" in sys.argv else DB_IN
    marcador = (sys.argv[sys.argv.index("--marcador") + 1]
                if "--marcador" in sys.argv else MARCADOR)
    aplicar = "--aplicar" in sys.argv
    solo_relleno = "--solo-relleno" in sys.argv
    sin_relleno = "--sin-relleno" in sys.argv

    if not db_in.exists():
        raise SystemExit(f"No existe la base: {db_in}")

    conn = sqlite3.connect(f"file:{db_in}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    columnas = [r[1] for r in conn.execute("PRAGMA table_info(ofertas)")]
    filas = [dict(r) for r in conn.execute("SELECT * FROM ofertas")]
    conn.close()
    print(f"Base de entrada : {db_in.name}  ({len(filas)} filas)")

    # ── 1. DETECCIÓN DE PROYECTOS ──
    detectados = []
    if not solo_relleno:
        for f in filas:
            s = señales_proyecto(f)
            conf = clasificar(s, f)
            if conf:
                detectados.append((conf, f, s))
        detectados.sort(key=lambda x: {"ALTA": 0, "MEDIA": 1, "BAJA": 2}[x[0]])

        with REPORTE.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["confianza", "id_aviso", "titulo", "comuna", "tipo", "operacion",
                        "precio_uf", "precio_clp", "m2_util", "m2_total", "dormitorios",
                        "banos", "senales", "url"])
            for conf, f, s in detectados:
                w.writerow([conf, f["id_aviso"], f["titulo"], f["comuna"], f["tipo"],
                            f["operacion"], f["precio_uf"], f["precio_clp"], f["m2_util"],
                            f["m2_total"], f["dormitorios"], f["banos"],
                            " | ".join(s), f["url"]])

        n = {c: sum(1 for x in detectados if x[0] == c) for c in ("ALTA", "MEDIA", "BAJA")}
        print(f"\nPROYECTOS DETECTADOS: {len(detectados)}")
        print(f"   ALTA  (se eliminan) : {n['ALTA']}")
        print(f"   MEDIA (se conservan): {n['MEDIA']}")
        print(f"   BAJA  (se conservan): {n['BAJA']}")
        print(f"   -> {REPORTE}")
        print("\n   Ejemplos de confianza ALTA:")
        for conf, f, s in [d for d in detectados if d[0] == "ALTA"][:8]:
            print(f"     {str(f['titulo'])[:40]:<42} {f['tipo'][:5]:<6} "
                  f"m2u={str(f['m2_util']):<5} {str(f['dormitorios'])}D  "
                  f"UF {f['precio_uf']}")

    if not aplicar:
        print("\n  (modo revisión: no se modificó nada)")
        print("  Para aplicar la limpieza:  python limpiar_dataset.py --aplicar\n")
        return

    # ── 2. APLICAR: copiar y limpiar ──
    print(f"\nAplicando limpieza -> {DB_OUT.name}")
    shutil.copy2(db_in, DB_OUT)
    out = sqlite3.connect(DB_OUT)

    if not solo_relleno:
        ids = [(f["id_aviso"],) for conf, f, _ in detectados if conf == "ALTA"]
        out.executemany("DELETE FROM ofertas WHERE id_aviso = ?", ids)
        out.commit()
        print(f"   proyectos eliminados: {len(ids)}")

    if not sin_relleno:
        total_celdas = 0
        for col in columnas:
            if col in ("detalle_ok",):          # numérico de control, se deja como está
                continue
            cur = out.execute(
                f"UPDATE ofertas SET {col} = ? WHERE {col} IS NULL OR TRIM({col}) = ''",
                (marcador,))
            total_celdas += cur.rowcount
        out.commit()
        print(f"   celdas vacías rellenadas con '{marcador}': {total_celdas}")

    out.execute("VACUUM")
    out.commit()
    quedan = out.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0]

    rows = out.execute(f"SELECT {', '.join(columnas)} FROM ofertas").fetchall()
    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(columnas)
        w.writerows(rows)
    out.close()

    print(f"\n   filas finales: {quedan}")
    print(f"   -> {DB_OUT}")
    print(f"   -> {CSV_OUT}")
    print(f"\n   La base de entrada {db_in.name} quedó intacta.\n")


if __name__ == "__main__":
    main()
