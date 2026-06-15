"""
DESCUBRIMIENTO API #6 — CEAD (Estadísticas Delictuales por Comuna)
==================================================================
¿Qué es?   El CEAD (Centro de Estudios y Análisis del Delito) es la fuente oficial
           del Ministerio de Seguridad Pública para estadísticas de delincuencia
           por región, provincia y comuna en Chile.

¿Tiene API pública?  NO. El sitio usa una interfaz web interactiva con filtros
           (territorio, tipo de delito, año) y un botón de descarga que genera
           un Excel dinámicamente. No hay una URL fija que se pueda automatizar
           de forma simple y oficial.

Fuente:    https://cead.minsegpublica.gob.cl/estadisticas-delictuales/

CÓMO OBTENER LOS DATOS REALES:
───────────────────────────────
1. Ir a: https://cead.minsegpublica.gob.cl/estadisticas-delictuales/
2. Seleccionar:
   - Territorio    → todas las comunas
   - Tipo de dato  → Casos policiales
   - Delito        → DMCS (Delitos de Mayor Connotación Social)
   - Período       → el año más reciente disponible
3. Clic en "Descargar" → guardar como:  app/data/cead_raw.xlsx
4. Correr el parser:
       python app/tools/parse_cead_excel.py
   Esto genera app/data/crime_by_comuna.csv con datos reales.

Este script valida que el archivo exista y muestra una previsualización.

Ejecutar:  python apis/06_cead_delincuencia.py
"""
import json
from pathlib import Path

RAW_EXCEL = Path(__file__).resolve().parent.parent / "app" / "data" / "cead_raw.xlsx"
PARSED_CSV = Path(__file__).resolve().parent.parent / "app" / "data" / "crime_by_comuna.csv"

print("=" * 60)
print("CEAD — Estado de los datos de delincuencia")
print("=" * 60)

# Verificar si ya existe el Excel descargado
if RAW_EXCEL.exists():
    size_kb = RAW_EXCEL.stat().st_size / 1024
    print(f"\n✓ Excel descargado encontrado: {RAW_EXCEL.name}  ({size_kb:.0f} KB)")
    print("  Puedes parsearlo con: python app/tools/parse_cead_excel.py")
else:
    print(f"\n✗ Excel NO encontrado en: {RAW_EXCEL}")
    print("""
  PASOS PARA OBTENERLO:
  1. Ir a: https://cead.minsegpublica.gob.cl/estadisticas-delictuales/
  2. Filtrar: todas las comunas + DMCS + año más reciente
  3. Clic en Descargar
  4. Guardar como: app/data/cead_raw.xlsx
  5. Correr: python app/tools/parse_cead_excel.py
""")

# Verificar el CSV actual (placeholder o real)
print("-" * 60)
if PARSED_CSV.exists():
    import csv
    with PARSED_CSV.open(encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#")]
    reader = list(csv.DictReader(lines))
    is_placeholder = PARSED_CSV.read_text(encoding="utf-8").startswith("#")

    print(f"CSV actual: {PARSED_CSV.name}")
    print(f"  Comunas en el dataset: {len(reader)}")
    print(f"  ¿Es placeholder?: {'SÍ ⚠️  — reemplazar con datos reales' if is_placeholder else 'NO ✓ — datos reales'}")

    if reader:
        print("\n  Primeras 5 filas:")
        for row in reader[:5]:
            print(f"    {row}")

    # Guardar estado en outputs/
    out_dir = Path(__file__).parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    status = {
        "excel_descargado": RAW_EXCEL.exists(),
        "csv_existe": True,
        "comunas_en_dataset": len(reader),
        "es_placeholder": is_placeholder,
        "muestra": reader[:3],
        "fuente_oficial": "https://cead.minsegpublica.gob.cl/estadisticas-delictuales/",
        "parser": "python app/tools/parse_cead_excel.py",
    }
    (out_dir / "cead_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n  Estado guardado en apis/outputs/cead_status.json")
else:
    print("✗ No existe el CSV todavía.")
