"""
Convierte el Excel descargado de CEAD al CSV que usa crime.py.

CÓMO OBTENER EL EXCEL OFICIAL:
──────────────────────────────
1. Ve a: https://cead.minsegpublica.gob.cl/estadisticas-delictuales/
2. Selecciona:
   - Territorio: TODAS LAS COMUNAS (o las que necesites)
   - Tipo de dato: Casos policiales
   - Delito: Delitos de Mayor Connotación Social (DMCS) — total
   - Período: el año más reciente disponible
3. Haz clic en "Descargar" → guarda el .xlsx en:
       app/data/cead_raw.xlsx

4. Ejecuta este script:
       python app/tools/parse_cead_excel.py

Genera: app/data/crime_by_comuna.csv  (reemplaza el placeholder)

Dependencia extra: openpyxl  →  pip install openpyxl
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

RAW_EXCEL = Path(__file__).resolve().parent.parent / "data" / "cead_raw.xlsx"
OUT_CSV   = Path(__file__).resolve().parent.parent / "data" / "crime_by_comuna.csv"

# Nombre de columna en el Excel de CEAD para la población (para calcular tasa).
# Si el Excel ya trae la tasa directamente, ajusta la lógica abajo.
COL_COMUNA    = "COMUNA"          # ajustar si el encabezado difiere
COL_REGION    = "REGIÓN"
COL_CASOS     = "CASOS POLICIALES"  # o "TOTAL" según la versión del Excel
COL_POBLACION = "POBLACIÓN"        # si existe; si no, la tasa viene precalculada
COL_TASA      = "TASA"             # tasa cada 100.000 hab. (si ya viene calculada)
COL_ANIO      = "AÑO"


def _try_import_openpyxl():
    try:
        import openpyxl
        return openpyxl
    except ImportError:
        print("Falta openpyxl. Instálalo con:  pip install openpyxl")
        sys.exit(1)


def parse(excel_path: Path = RAW_EXCEL, out_path: Path = OUT_CSV) -> None:
    openpyxl = _try_import_openpyxl()

    if not excel_path.exists():
        print(f"No encontré el archivo: {excel_path}")
        print("Descárgalo de https://cead.minsegpublica.gob.cl/estadisticas-delictuales/")
        print("y guárdalo como app/data/cead_raw.xlsx")
        sys.exit(1)

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        print("El Excel está vacío.")
        sys.exit(1)

    # Detectar la fila de encabezados (la primera fila no vacía)
    header_row = None
    data_start = 0
    for i, row in enumerate(rows):
        cleaned = [str(c).strip().upper() if c else "" for c in row]
        if any(k in " ".join(cleaned) for k in ("COMUNA", "REGION", "CASOS", "TASA")):
            header_row = cleaned
            data_start = i + 1
            break

    if header_row is None:
        print("No se encontró la fila de encabezados. Revisa el Excel y ajusta las constantes COL_* en este script.")
        print("Primeras 3 filas del Excel:")
        for row in rows[:3]:
            print(" ", row)
        sys.exit(1)

    print(f"Encabezados detectados: {header_row}")

    # Mapear nombres de columna a índice (búsqueda flexible)
    def col_idx(candidates: list[str]) -> int | None:
        for candidate in candidates:
            for i, h in enumerate(header_row):
                if candidate in h:
                    return i
        return None

    idx_comuna = col_idx(["COMUNA"])
    idx_region = col_idx(["REGION", "REGIÓN"])
    idx_anio   = col_idx(["AÑO", "ANO", "YEAR"])
    idx_tasa   = col_idx(["TASA"])
    idx_casos  = col_idx(["CASOS", "TOTAL"])
    idx_pob    = col_idx(["POBLACION", "POBLACIÓN", "POB"])

    if idx_comuna is None:
        print("No se encontró la columna COMUNA. Revisa los encabezados e imprime el Excel.")
        sys.exit(1)

    out_rows: list[dict] = []
    for row in rows[data_start:]:
        if not any(row):
            continue
        comuna = str(row[idx_comuna]).strip() if idx_comuna is not None and row[idx_comuna] else None
        if not comuna or comuna.upper() in ("NONE", "TOTAL", ""):
            continue

        region = str(row[idx_region]).strip() if idx_region is not None and row[idx_region] else ""
        anio   = str(row[idx_anio]).strip()   if idx_anio   is not None and row[idx_anio]   else ""

        # Tasa: usar directamente si existe, sino calcular con casos/población
        tasa = None
        if idx_tasa is not None and row[idx_tasa]:
            try:
                tasa = float(str(row[idx_tasa]).replace(",", "."))
            except ValueError:
                pass

        if tasa is None and idx_casos is not None and idx_pob is not None:
            try:
                casos = float(str(row[idx_casos]).replace(",", "."))
                pob   = float(str(row[idx_pob]).replace(",", "."))
                if pob > 0:
                    tasa = round(casos / pob * 100_000, 1)
            except (ValueError, TypeError):
                pass

        if tasa is None:
            continue  # sin tasa, no podemos usar la fila

        out_rows.append({
            "comuna": comuna,
            "region": region,
            "tasa_delitos_100k_hab": tasa,
            "anio": anio,
        })

    wb.close()

    if not out_rows:
        print("No se pudo extraer ninguna fila con datos válidos. Revisa las constantes COL_* y el Excel.")
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["comuna", "region", "tasa_delitos_100k_hab", "anio"])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"\n✓ Generado: {out_path}")
    print(f"  {len(out_rows)} comunas escritas.")
    print("  Recarga la aplicación para que crime.py use los datos reales.")


if __name__ == "__main__":
    parse()
