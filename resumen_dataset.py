r"""RESUMEN COMPLETO del dataset de ofertas inmobiliarias (para presentar a la empresa).

Ejecutar en VS Code: abrir este archivo y presionar Ctrl+F5
(o en terminal:  .\.venv\Scripts\python.exe resumen_dataset.py)

Se puede correr aunque el scraper esté extrayendo en paralelo (lectura solo-lectura).
"""
import sqlite3
import sys
from pathlib import Path
from statistics import median

# Base vigente: la deduplicada. Se puede apuntar a otra con  --db <ruta>
DATA = Path(__file__).parent / "data"
DB = DATA / "ofertas_sinduplicados.sqlite"
CSV = DATA / "ofertas_sinduplicados.csv"
if "--db" in sys.argv:
    DB = Path(sys.argv[sys.argv.index("--db") + 1])
    CSV = DB.with_suffix(".csv")

if not DB.exists():
    raise SystemExit(f"No existe la base todavía: {DB}\nCorre primero el scraper.")

# Conexión de solo lectura con timeout: no interfiere con el scraper si está corriendo
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)

DESCRIPCION_COLUMNAS = {
    "sitio": "Portal de origen (pi = PortalInmobiliario)",
    "id_aviso": "ID único del aviso en el portal",
    "url": "Link directo al aviso",
    "operacion": "venta | arriendo",
    "tipo": "casa | departamento",
    "comuna": "Comuna (macul, la-florida, nunoa, san-miguel)",
    "barrio": "Barrio/sector según el portal",
    "direccion": "Dirección aproximada publicada",
    "titulo": "Título del aviso",
    "precio_valor": "Precio tal como se publicó",
    "precio_moneda": "UF o CLP",
    "precio_clp": "Precio normalizado a pesos (UF del día)",
    "precio_uf": "Precio normalizado a UF",
    "m2_util": "Superficie útil (m²)",
    "m2_total": "Superficie total (m²)",
    "dormitorios": "N° de dormitorios",
    "banos": "N° de baños",
    "estacionamientos": "N° de estacionamientos",
    "bodegas": "N° de bodegas",
    "antiguedad_anos": "Antigüedad declarada de la propiedad (años)",
    "ano_construccion": "Año de construcción estimado",
    "gastos_comunes_clp": "Gastos comunes (pesos)",
    "antiguedad_aviso_dias": "Días desde que se publicó el aviso",
    "fecha_publicacion": "Fecha estimada de publicación del aviso",
    "lat": "Latitud (para features de entorno/POIs)",
    "lon": "Longitud",
    "descripcion": "Descripción larga del aviso (texto)",
    "publica": "Tipo de publicador (particular/profesional)",
    "detalle_ok": "1 = ficha de detalle ya visitada",
    "fecha_scrape": "Fecha de captura del dato",
}

SEP = "=" * 66


def fmt(n, dec=0):
    if n is None:
        return "-"
    return f"{n:,.{dec}f}".replace(",", ".")


print(SEP)
print("RESUMEN DEL DATASET DE OFERTAS INMOBILIARIAS")
print("Fuente: PortalInmobiliario | Comunas: Macul, La Florida, Ñuñoa, San Miguel")
print(SEP)

# ------------------------------------------------------------------ 1. Volumen
total, con_detalle = conn.execute(
    "SELECT COUNT(*), SUM(detalle_ok) FROM ofertas").fetchone()
print(f"\n1) VOLUMEN")
print(f"   Total de anuncios extraídos : {fmt(total)}")
print(f"   Con ficha de detalle        : {fmt(con_detalle or 0)} "
      f"({(con_detalle or 0)/total*100:.1f}%)")
if CSV.exists():
    print(f"   Export CSV                  : {CSV.name} "
          f"({CSV.stat().st_size/1024/1024:.1f} MB)")

print("\n   Anuncios por comuna:")
for comuna, n in conn.execute(
        "SELECT comuna, COUNT(*) FROM ofertas GROUP BY comuna ORDER BY 2 DESC"):
    print(f"     {comuna:<14}{fmt(n):>8}")

print("\n   Anuncios por comuna / operación / tipo:")
print(f"     {'comuna':<12}{'operacion':<10}{'tipo':<14}{'avisos':>7}")
for comuna, op, tipo, n in conn.execute(
        "SELECT comuna, operacion, tipo, COUNT(*) FROM ofertas "
        "GROUP BY 1,2,3 ORDER BY 1,2,3"):
    print(f"     {comuna:<12}{op:<10}{tipo:<14}{fmt(n):>7}")

# ------------------------------------------- 2. Por año de publicación y comuna
print(f"\n2) ANUNCIOS POR AÑO DE PUBLICACIÓN Y COMUNA")
print("   (según 'Publicado hace N días' del aviso; los proyectos no lo informan)")
anios = [a for (a,) in conn.execute(
    "SELECT DISTINCT substr(fecha_publicacion,1,4) FROM ofertas "
    "WHERE fecha_publicacion IS NOT NULL ORDER BY 1 DESC")]
comunas = [c for (c,) in conn.execute(
    "SELECT DISTINCT comuna FROM ofertas ORDER BY 1")]
if anios:
    print(f"     {'año':<7}" + "".join(f"{c:>12}" for c in comunas) + f"{'total':>9}")
    for anio in anios:
        fila = [conn.execute(
            "SELECT COUNT(*) FROM ofertas WHERE comuna=? "
            "AND substr(fecha_publicacion,1,4)=?", (c, anio)).fetchone()[0]
            for c in comunas]
        print(f"     {anio:<7}" + "".join(f"{fmt(v):>12}" for v in fila)
              + f"{fmt(sum(fila)):>9}")
    sin_fecha = conn.execute(
        "SELECT COUNT(*) FROM ofertas WHERE fecha_publicacion IS NULL").fetchone()[0]
    print(f"     {'s/fecha':<7}" + " " * (12 * len(comunas)) + f"{fmt(sin_fecha):>9}")
else:
    print("     (aún sin fechas: falta la pasada de detalle)")

# ------------------------------------------------------ 3. Columnas del dataset
print(f"\n3) COLUMNAS DEL DATASET ({len(DESCRIPCION_COLUMNAS)})")
for col, desc in DESCRIPCION_COLUMNAS.items():
    print(f"     {col:<24}{desc}")

# ------------------------------------------------- 4. Estadísticas de mercado
print(f"\n4) ESTADÍSTICAS DE MERCADO (medianas)")
print("   Venta (UF) y arriendo (CLP/mes) por comuna y tipo:")
print(f"     {'comuna':<13}{'tipo':<14}{'venta UF':>10}{'UF/m²':>8}{'arriendo CLP':>14}")
for comuna in comunas:
    for tipo in ("casa", "departamento"):
        ventas = [v for (v,) in conn.execute(
            "SELECT CAST(precio_uf AS REAL) FROM ofertas WHERE comuna=? AND tipo=? "
            "AND operacion='venta' AND precio_uf IS NOT NULL", (comuna, tipo))]
        uf_m2 = [v / m for (v, m) in conn.execute(
            "SELECT CAST(precio_uf AS REAL), CAST(m2_util AS REAL) FROM ofertas "
            "WHERE comuna=? AND tipo=? AND operacion='venta' "
            "AND precio_uf IS NOT NULL AND m2_util IS NOT NULL AND m2_util > 10",
            (comuna, tipo))]
        arr = [v for (v,) in conn.execute(
            "SELECT CAST(precio_clp AS REAL) FROM ofertas WHERE comuna=? AND tipo=? "
            "AND operacion='arriendo' AND precio_clp IS NOT NULL", (comuna, tipo))]
        print(f"     {comuna:<13}{tipo:<14}"
              f"{fmt(median(ventas)) if ventas else '-':>10}"
              f"{fmt(median(uf_m2), 1) if uf_m2 else '-':>8}"
              f"{fmt(median(arr)) if arr else '-':>14}")

# --------------------------------------------------- 5. Completitud de columnas
print(f"\n5) COMPLETITUD DE COLUMNAS CLAVE (% de avisos con dato)")
for col in ["precio_uf", "m2_util", "dormitorios", "banos", "direccion",
            "m2_total", "ano_construccion", "gastos_comunes_clp",
            "lat", "fecha_publicacion", "descripcion"]:
    con_dato = conn.execute(f"SELECT COUNT({col}) FROM ofertas").fetchone()[0]
    pct = con_dato / total * 100
    print(f"     {col:<22}{pct:>6.1f}%  {'#' * int(pct / 100 * 28)}")

# ------------------------------------------------- 6. Ejemplo real por comuna
print(f"\n6) EJEMPLO DE ANUNCIO POR COMUNA (extraído de la base)")
for comuna in comunas:
    row = conn.execute(
        "SELECT titulo, operacion, tipo, precio_uf, precio_clp, m2_util, m2_total, "
        "dormitorios, banos, ano_construccion, barrio, direccion, fecha_publicacion, "
        "lat, lon, substr(descripcion,1,150), url "
        "FROM ofertas WHERE comuna=? AND detalle_ok=1 AND lat IS NOT NULL "
        "AND m2_util IS NOT NULL AND ano_construccion IS NOT NULL "
        "AND fecha_publicacion IS NOT NULL AND dormitorios IS NOT NULL "
        "ORDER BY id_aviso DESC LIMIT 1", (comuna,)).fetchone()
    if not row:
        row = conn.execute(
            "SELECT titulo, operacion, tipo, precio_uf, precio_clp, m2_util, m2_total, "
            "dormitorios, banos, ano_construccion, barrio, direccion, fecha_publicacion, "
            "lat, lon, substr(descripcion,1,150), url "
            "FROM ofertas WHERE comuna=? LIMIT 1", (comuna,)).fetchone()
    (tit, op, tipo, uf, clp, m2u, m2t, dorm, ban, ano, barrio, dire, fpub,
     lat, lon, desc, url) = row
    print(f"\n   --- {comuna.upper()} ---")
    print(f"   {tit}")
    print(f"   {op} · {tipo} · {barrio or 's/barrio'}")
    print(f"   Precio: UF {fmt(float(uf)) if uf else '-'} "
          f"(~${fmt(float(clp)) if clp else '-'} CLP)")
    print(f"   {fmt(float(m2u)) if m2u else '-'} m² útiles / "
          f"{fmt(float(m2t)) if m2t else '-'} m² totales · "
          f"{dorm or '-'} dorm · {ban or '-'} baños · año {ano or '-'}")
    print(f"   Publicado: {fpub or '-'} · lat/lon: {lat or '-'}, {lon or '-'}")
    print(f"   Dirección: {dire or '-'}")
    if desc:
        print(f"   Descripción: {desc}...")
    print(f"   {url}")

conn.close()
print("\n" + SEP)
