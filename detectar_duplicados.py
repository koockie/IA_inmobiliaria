r"""DETECTOR DE ANUNCIOS DUPLICADOS — solo lectura, genera listado para revisión manual.

NO modifica la base de datos ni el CSV. Solo lee `data/ofertas.sqlite` y escribe
dos archivos nuevos con los grupos de posibles duplicados para que los revises a mano.

USO
---
    .\.venv\Scripts\python.exe detectar_duplicados.py                  (usa data/ofertas.sqlite)
    .\.venv\Scripts\python.exe detectar_duplicados.py --csv otro.csv   (usa un CSV cualquiera)

    Opcionales:
      --min-confianza media    solo reporta grupos ALTA y MEDIA (default: reporta todo)
      --limite 100             corta el reporte a N grupos
      --salida nombre          prefijo de los archivos de salida (default: duplicados)
      --limpiar                además de detectar, genera una base SIN duplicados

LIMPIEZA (--limpiar)
--------------------
    .\.venv\Scripts\python.exe detectar_duplicados.py --limpiar

    Elimina SOLO las copias de los grupos de confianza ALTA (deja el ORIGINAL de
    cada grupo). Los grupos MEDIA y BAJA quedan intactos: suelen ser unidades
    distintas del mismo edificio y borrarlos perdería datos válidos.

    NUNCA modifica data/ofertas.sqlite. Trabaja sobre una copia y escribe:
        data/ofertas_sinduplicados.sqlite
        data/ofertas_sinduplicados.csv
        data/eliminados_por_duplicado.csv   (bitácora de qué se eliminó y por qué)

COLUMNAS QUE NECESITA EL CSV
----------------------------
    Imprescindibles : id_aviso, titulo, direccion
    Muy recomendadas: lat, lon, precio_clp, m2_util   (sin lat/lon usa la dirección escrita)
    Opcionales      : precio_uf, precio_moneda, m2_total, dormitorios, banos,
                      estacionamientos, bodegas, ano_construccion, gastos_comunes_clp,
                      comuna, tipo, operacion, antiguedad_aviso_dias, descripcion, url
    Las que falten se rellenan vacías y el detector sigue funcionando (con menos señales).

SALIDAS (en data/)
------------------
    duplicados.csv   una fila por anuncio, con grupo, rol (ORIGINAL/DUPLICADO) y señales
    duplicados.txt   el mismo listado en formato legible para revisar con los links

EL PROBLEMA QUE RESUELVE
------------------------
En PortalInmobiliario la dirección corresponde al EDIFICIO, no al departamento. Por eso
"misma dirección + mismo m² + mismos dormitorios" puede ser:
    (a) el mismo inmueble publicado por dos corredoras  -> DUPLICADO real
    (b) dos departamentos distintos del mismo edificio  -> NO es duplicado
Para separarlos se combinan varias señales y se entrega un nivel de confianza.
"""
from __future__ import annotations

import csv
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
# Base vigente: la deduplicada. Se puede apuntar a otra con  --db <ruta>
DB = DATA_DIR / "ofertas_sinduplicados.sqlite"
if "--db" in sys.argv:
    DB = Path(sys.argv[sys.argv.index("--db") + 1])

# Columnas que usa el detector. Las que falten en el origen se rellenan con None.
CAMPOS = [
    "id_aviso", "url", "titulo", "comuna", "barrio", "direccion", "operacion", "tipo",
    "precio_uf", "precio_clp", "precio_moneda", "m2_util", "m2_total", "dormitorios",
    "banos", "estacionamientos", "bodegas", "ano_construccion", "gastos_comunes_clp",
    "lat", "lon", "fecha_publicacion", "antiguedad_aviso_dias", "descripcion",
]

# ── Umbrales (ajustables) ────────────────────────────────────────────────────
SIM_DESC_ALTA = 0.85     # descripciones casi idénticas -> mismo aviso
SIM_DESC_MEDIA = 0.60
SIM_TITULO_ALTA = 0.80
DIST_COORD_M = 30        # metros: mismas coordenadas prácticamente
PESO = {                 # puntaje de cada señal coincidente
    "descripcion_muy_similar": 45,
    "titulo_muy_similar": 15,
    "precio_identico": 20,
    "m2_util_identico": 8,
    "m2_total_identico": 6,
    "dormitorios_banos_iguales": 6,
    "coordenadas_iguales": 10,
    "gastos_comunes_identicos": 8,
    "ano_construccion_identico": 5,
    "estacionamientos_bodegas_iguales": 4,
}


def normalizar(txt: str | None) -> str:
    """minúsculas, sin acentos ni puntuación, para comparar texto."""
    if not txt:
        return ""
    t = unicodedata.normalize("NFKD", str(txt).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def similitud(a: str, b: str) -> float:
    """Similitud 0-1 entre dos textos (rápida: Jaccard + refinamiento)."""
    if not a or not b:
        return 0.0
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    jaccard = len(sa & sb) / len(sa | sb)
    if jaccard < 0.35:            # descarte rápido, evita comparar todo
        return jaccard
    return SequenceMatcher(None, a[:900], b[:900]).ratio()


def fnum(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def dist_m(lat1, lon1, lat2, lon2) -> float | None:
    """Distancia aproximada en metros (suficiente para distinguir <30 m)."""
    a, b, c, d = fnum(lat1), fnum(lon1), fnum(lat2), fnum(lon2)
    if None in (a, b, c, d):
        return None
    return ((a - c) ** 2 + ((b - d) * 0.83) ** 2) ** 0.5 * 111_000


def señas_de_unidad(titulo_norm: str) -> set[str]:
    """Extrae marcas de unidad concreta del título: piso, depto y orientación.

    Los edificios de renta publican decenas de unidades casi idénticas y las
    distinguen justamente ahí ("vista norte piso 5" vs "vista sur piso 11").
    """
    marcas = set()
    for m in re.finditer(r"\bpiso\s*(\d{1,2})", titulo_norm):
        marcas.add(f"piso{m.group(1)}")
    for m in re.finditer(r"\b(?:depto|departamento|unidad|casa)\s*n?\s*(\d{2,4})\b", titulo_norm):
        marcas.add(f"unidad{m.group(1)}")
    for o in ("norte", "sur", "oriente", "poniente", "nororiente", "surponiente"):
        if re.search(rf"vista\s+{o}\b", titulo_norm):
            marcas.add(f"vista{o}")
    return marcas


def unidades_distintas(x: dict, y: dict) -> bool:
    """True si los títulos identifican explícitamente unidades diferentes."""
    a, b = señas_de_unidad(x["titulo_norm"]), señas_de_unidad(y["titulo_norm"])
    return bool(a and b and a != b)


def mismo_lugar(x: dict, y: dict) -> tuple[bool, str]:
    """FILTRO OBLIGATORIO: dos avisos solo pueden ser el mismo inmueble si están
    físicamente en el mismo punto.

    Es el filtro más importante del detector: sin él, las descripciones-plantilla
    que reutilizan las corredoras agrupan propiedades de direcciones distintas.
    """
    d = dist_m(x["lat"], x["lon"], y["lat"], y["lon"])
    if d is not None:                       # ambos tienen coordenadas: manda la distancia
        return (d <= DIST_COORD_M, "coordenadas_iguales" if d <= DIST_COORD_M else "")
    # sin coordenadas: comparar la dirección escrita
    sim_dir = similitud(normalizar(x["direccion"]), normalizar(y["direccion"]))
    return (sim_dir >= 0.75, "direccion_muy_similar" if sim_dir >= 0.75 else "")


def comparar(x: dict, y: dict) -> tuple[int, list[str], float]:
    """Devuelve (puntaje, señales coincidentes, similitud de descripción)."""
    senales: list[str] = []

    sim_desc = similitud(x["desc_norm"], y["desc_norm"])
    if sim_desc >= SIM_DESC_ALTA:
        senales.append("descripcion_muy_similar")

    if similitud(x["titulo_norm"], y["titulo_norm"]) >= SIM_TITULO_ALTA:
        senales.append("titulo_muy_similar")

    # precio: comparar en la misma unidad
    px, py = fnum(x["precio_clp"]), fnum(y["precio_clp"])
    if px and py and abs(px - py) < 1:
        senales.append("precio_identico")

    for campo, senal in [("m2_util", "m2_util_identico"),
                         ("m2_total", "m2_total_identico"),
                         ("gastos_comunes_clp", "gastos_comunes_identicos"),
                         ("ano_construccion", "ano_construccion_identico")]:
        vx, vy = fnum(x[campo]), fnum(y[campo])
        if vx is not None and vy is not None and vx == vy and vx > 0:
            senales.append(senal)

    if (x["dormitorios"] and x["dormitorios"] == y["dormitorios"]
            and x["banos"] and x["banos"] == y["banos"]):
        senales.append("dormitorios_banos_iguales")

    if (x["estacionamientos"] and x["estacionamientos"] == y["estacionamientos"]
            and x["bodegas"] and x["bodegas"] == y["bodegas"]):
        senales.append("estacionamientos_bodegas_iguales")

    d = dist_m(x["lat"], x["lon"], y["lat"], y["lon"])
    if d is not None and d <= DIST_COORD_M:
        senales.append("coordenadas_iguales")

    return sum(PESO[s] for s in senales), senales, sim_desc


def confianza(puntaje: int, senales: list[str]) -> str | None:
    """Traduce el puntaje a un nivel de confianza interpretable.

    Se asume que el par YA pasó el filtro de ubicación (mismo_lugar), es decir
    ambos avisos están en el mismo punto. Lo que discrimina aquí es si se trata
    del mismo inmueble o de dos unidades distintas del mismo edificio.
    """
    mismo_precio = "precio_identico" in senales
    misma_desc = "descripcion_muy_similar" in senales
    mismo_m2 = "m2_util_identico" in senales

    # Mismo lugar + mismo precio exacto -> casi con certeza el mismo inmueble
    # (dos departamentos distintos rara vez comparten el precio al peso exacto).
    if mismo_precio and (misma_desc or mismo_m2):
        return "ALTA"
    if mismo_precio:
        return "MEDIA"
    # Sin mismo precio: puede ser otra unidad del edificio, o el mismo aviso
    # republicado con ajuste de precio.
    if misma_desc and mismo_m2:
        return "MEDIA"
    if puntaje >= 30:
        return "BAJA"
    return None


def cargar_desde_sqlite() -> list[dict]:
    if not DB.exists():
        raise SystemExit(f"No existe la base: {DB}")
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    filas = [dict(r) for r in conn.execute(f"SELECT {', '.join(CAMPOS)} FROM ofertas")]
    conn.close()
    return filas


def cargar_desde_csv(ruta: Path) -> list[dict]:
    """Lee un CSV cualquiera y lo adapta al esquema del detector.

    Acepta que falten columnas: las rellena con None y avisa cuáles no encontró.
    """
    if not ruta.exists():
        raise SystemExit(f"No existe el archivo: {ruta}")
    # Se detecta SOLO el delimitador y se conserva el dialecto excel estándar.
    # (Usar el dialecto completo del Sniffer rompe los campos multilínea: las
    #  descripciones con saltos de línea generaban filas fantasma.)
    with ruta.open(encoding="utf-8-sig", newline="") as fh:
        muestra = fh.read(8192)
        fh.seek(0)
        try:
            delimitador = csv.Sniffer().sniff(muestra, delimiters=",;\t").delimiter
        except csv.Error:
            delimitador = ","
        filas_csv = list(csv.DictReader(fh, delimiter=delimitador))

    if not filas_csv:
        raise SystemExit("El CSV está vacío.")

    presentes = set(filas_csv[0].keys())
    faltan = [c for c in CAMPOS if c not in presentes]
    imprescindibles = [c for c in ("id_aviso", "titulo", "direccion") if c not in presentes]
    if imprescindibles:
        print(f"\n  Columnas del CSV: {sorted(presentes)}\n")
        raise SystemExit(
            f"Faltan columnas imprescindibles: {', '.join(imprescindibles)}.\n"
            "Renómbralas en el CSV o ajusta la lista CAMPOS de este script.")
    if faltan:
        print(f"  Aviso: el CSV no trae {len(faltan)} columnas opcionales "
              f"({', '.join(faltan[:6])}{'...' if len(faltan) > 6 else ''}).")
        print("         El detector funciona igual, con menos señales disponibles.")

    return [{c: (f.get(c) or None) for c in CAMPOS} for f in filas_csv]


def limpiar_duplicados(grupos_final: list, por_id: dict) -> None:
    """Genera una base SIN los duplicados de confianza ALTA.

    Regla conservadora: solo se eliminan las copias de los grupos ALTA (el
    ORIGINAL de cada grupo se conserva siempre). Los grupos MEDIA y BAJA no se
    tocan porque suelen ser unidades distintas del mismo edificio.

    La base original NUNCA se modifica: se copia y se limpia la copia.
    """
    if not DB.exists():
        print("\n  [limpieza] omitida: requiere data/ofertas.sqlite (no aplica en modo --csv)")
        return

    a_eliminar: list[tuple[str, str, str]] = []   # (id_duplicado, id_original, confianza)
    for original, miembros, conf, _senales, _sim in grupos_final:
        if conf != "ALTA":
            continue
        for idv in miembros:
            if idv != original:
                a_eliminar.append((idv, original, conf))

    if not a_eliminar:
        print("\n  [limpieza] no hay duplicados ALTA que eliminar.")
        return

    # Si la entrada ya es la base deduplicada, el resultado va a _v2 para no pisarla.
    sufijo = "_v2" if "sinduplicados" in DB.stem else ""
    destino_db = DATA_DIR / f"ofertas_sinduplicados{sufijo}.sqlite"
    destino_csv = DATA_DIR / f"ofertas_sinduplicados{sufijo}.csv"
    bitacora = DATA_DIR / f"eliminados_por_duplicado{sufijo}.csv"

    print(f"\n  [limpieza] copiando {DB.name} -> {destino_db.name} ...")
    shutil.copy2(DB, destino_db)

    conn = sqlite3.connect(destino_db)
    antes = conn.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0]

    # Bitácora ANTES de borrar, para conservar los datos del eliminado
    with bitacora.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id_eliminado", "id_conservado", "confianza", "titulo_eliminado",
                    "precio_uf_eliminado", "precio_clp_eliminado", "m2_util", "direccion", "url"])
        for idv, original, conf in a_eliminar:
            f = por_id[idv]
            w.writerow([idv, original, conf, f["titulo"], f["precio_uf"], f["precio_clp"],
                        f["m2_util"], f["direccion"], f["url"]])

    conn.executemany("DELETE FROM ofertas WHERE id_aviso = ?",
                     [(idv,) for idv, _, _ in a_eliminar])
    conn.commit()
    despues = conn.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0]
    conn.execute("VACUUM")          # compacta el archivo tras los DELETE
    conn.commit()

    # Export a CSV con el mismo orden de columnas de la tabla
    columnas = [r[1] for r in conn.execute("PRAGMA table_info(ofertas)")]
    filas = conn.execute(f"SELECT {', '.join(columnas)} FROM ofertas").fetchall()
    with destino_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(columnas)
        w.writerows(filas)
    conn.close()

    print(f"  [limpieza] filas: {antes} -> {despues}  (eliminadas {antes - despues})")
    print(f"    -> {destino_db}")
    print(f"    -> {destino_csv}")
    print(f"    -> {bitacora}  (bitácora de lo eliminado)")
    print(f"  La base original {DB.name} quedó intacta.")


def main() -> None:
    min_conf = "baja"
    limite = None
    if "--min-confianza" in sys.argv:
        min_conf = sys.argv[sys.argv.index("--min-confianza") + 1].lower()
    if "--limite" in sys.argv:
        limite = int(sys.argv[sys.argv.index("--limite") + 1])
    orden = {"alta": 3, "media": 2, "baja": 1}
    umbral = orden.get(min_conf, 1)

    # Origen de los datos: SQLite (default) o un CSV cualquiera
    if "--csv" in sys.argv:
        ruta = Path(sys.argv[sys.argv.index("--csv") + 1])
        print(f"Origen: CSV {ruta}")
        filas = cargar_desde_csv(ruta)
        prefijo = f"duplicados_{ruta.stem}"
    else:
        print(f"Origen: SQLite {DB.name}")
        filas = cargar_desde_sqlite()
        prefijo = "duplicados"

    if "--salida" in sys.argv:
        prefijo = sys.argv[sys.argv.index("--salida") + 1]
    DATA_DIR.mkdir(exist_ok=True)
    out_csv = DATA_DIR / f"{prefijo}.csv"
    out_txt = DATA_DIR / f"{prefijo}.txt"

    print(f"Analizando {len(filas)} anuncios...")
    for f in filas:
        f["titulo_norm"] = normalizar(f["titulo"])
        f["desc_norm"] = normalizar(f["descripcion"])

    # ── BLOQUEO: solo se comparan anuncios que podrían ser el mismo inmueble.
    # Clave: comuna + tipo + operación + m² útil redondeado a 5. Evita comparar
    # los 15k contra los 15k (116 millones de pares) y baja a unos miles.
    bloques: dict[tuple, list[dict]] = defaultdict(list)
    for f in filas:
        m2 = fnum(f["m2_util"])
        clave = (f["comuna"], f["tipo"], f["operacion"], round(m2 / 5) if m2 else None)
        bloques[clave].append(f)

    pares = []
    for clave, grupo in bloques.items():
        if len(grupo) < 2 or clave[3] is None:
            continue
        for i in range(len(grupo)):
            for j in range(i + 1, len(grupo)):
                # FILTRO 1 (obligatorio): ¿están en el mismo punto?
                ok, senal_lugar = mismo_lugar(grupo[i], grupo[j])
                if not ok:
                    continue
                # FILTRO 1b: si los títulos declaran unidades distintas
                # (piso/depto/orientación), son inmuebles diferentes.
                if unidades_distintas(grupo[i], grupo[j]):
                    continue
                # FILTRO 2: ¿comparten suficientes atributos?
                puntaje, senales, sim = comparar(grupo[i], grupo[j])
                if senal_lugar and senal_lugar not in senales:
                    senales.append(senal_lugar)
                conf = confianza(puntaje, senales)
                if conf and orden[conf.lower()] >= umbral:
                    pares.append((grupo[i], grupo[j], puntaje, senales, sim, conf))

    print(f"Pares sospechosos encontrados: {len(pares)}")

    # ── AGRUPAR en clusters (si A~B y B~C, van al mismo grupo) ──
    padre: dict[str, str] = {}

    def raiz(x):
        padre.setdefault(x, x)
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    def unir(a, b):
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            padre[ra] = rb

    # Solo se encadenan (A~B, B~C -> mismo grupo) los pares de confianza ALTA o
    # MEDIA. Los BAJA quedan como pares sueltos: encadenarlos juntaría medio
    # edificio en un solo grupo.
    info_par: dict[tuple, tuple] = {}
    for x, y, puntaje, senales, sim, conf in pares:
        if conf in ("ALTA", "MEDIA"):
            unir(x["id_aviso"], y["id_aviso"])
        else:
            padre.setdefault(x["id_aviso"], x["id_aviso"])
            padre.setdefault(y["id_aviso"], y["id_aviso"])
            if raiz(x["id_aviso"]) == x["id_aviso"] and raiz(y["id_aviso"]) == y["id_aviso"]:
                unir(x["id_aviso"], y["id_aviso"])
        info_par[(x["id_aviso"], y["id_aviso"])] = (puntaje, senales, sim, conf)

    clusters: dict[str, list[str]] = defaultdict(list)
    for idv in padre:
        clusters[raiz(idv)].append(idv)

    por_id = {f["id_aviso"]: f for f in filas}

    # ── ELEGIR EL ORIGINAL: el aviso publicado hace más tiempo. Si no hay dato
    # de antigüedad, el de id menor (se publicó antes en el portal).
    def clave_orden(idv: str):
        f = por_id[idv]
        dias = fnum(f["antiguedad_aviso_dias"])
        return (-(dias if dias is not None else -1), int(idv))

    grupos_final = []
    for miembros in clusters.values():
        if len(miembros) < 2:
            continue
        miembros = sorted(miembros, key=clave_orden)
        original = miembros[0]
        conf_grupo = "BAJA"
        senales_grupo, sim_grupo = [], 0.0
        for (a, b), (p, s, sim, c) in info_par.items():
            if a in miembros and b in miembros:
                if orden[c.lower()] > orden[conf_grupo.lower()]:
                    conf_grupo = c
                if len(s) > len(senales_grupo):
                    senales_grupo = s
                sim_grupo = max(sim_grupo, sim)
        # Un grupo con muchos miembros suele ser un edificio de renta publicando
        # varias unidades parecidas, no un aviso repetido. Se degrada la confianza
        # para que se revise con otro criterio.
        if len(miembros) >= 5 and conf_grupo == "ALTA":
            conf_grupo = "MEDIA"
            senales_grupo = senales_grupo + ["OJO_grupo_grande_posible_edificio_renta"]
        grupos_final.append((original, miembros, conf_grupo, senales_grupo, sim_grupo))

    grupos_final.sort(key=lambda g: (-orden[g[2].lower()], -len(g[1])))
    if limite:
        grupos_final = grupos_final[:limite]

    # ── ESCRIBIR CSV ──
    out_csv.parent.mkdir(exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["grupo", "rol", "id_aviso", "id_original", "confianza",
                    "similitud_descripcion", "senales", "titulo", "comuna", "tipo",
                    "operacion", "precio_uf", "precio_clp", "m2_util", "dormitorios",
                    "banos", "direccion", "antiguedad_aviso_dias", "url"])
        for n, (original, miembros, conf, senales, sim) in enumerate(grupos_final, 1):
            for idv in miembros:
                f = por_id[idv]
                w.writerow([n, "ORIGINAL" if idv == original else "DUPLICADO", idv,
                            "" if idv == original else original, conf, f"{sim:.2f}",
                            " | ".join(senales), f["titulo"], f["comuna"], f["tipo"],
                            f["operacion"], f["precio_uf"], f["precio_clp"], f["m2_util"],
                            f["dormitorios"], f["banos"], f["direccion"],
                            f["antiguedad_aviso_dias"], f["url"]])

    # ── ESCRIBIR TXT LEGIBLE ──
    with out_txt.open("w", encoding="utf-8") as fh:
        fh.write("POSIBLES ANUNCIOS DUPLICADOS — revisión manual\n")
        fh.write("=" * 78 + "\n")
        fh.write(f"Grupos detectados: {len(grupos_final)}   "
                 f"Anuncios involucrados: {sum(len(g[1]) for g in grupos_final)}\n")
        fh.write("Nota: la dirección en el portal es del EDIFICIO. Confianza BAJA suele\n"
                 "ser 'mismo edificio, distinto departamento' (NO duplicado).\n")
        fh.write("=" * 78 + "\n\n")
        for n, (original, miembros, conf, senales, sim) in enumerate(grupos_final, 1):
            fh.write(f"GRUPO {n}  [confianza {conf}]  similitud_descripcion={sim:.2f}\n")
            fh.write(f"  señales: {', '.join(senales) or '-'}\n")
            for idv in miembros:
                f = por_id[idv]
                rol = "ORIGINAL " if idv == original else "DUPLICADO"
                precio = (f"UF {f['precio_uf']}" if f["precio_moneda"] == "UF"
                          else f"$ {f['precio_clp']}")
                fh.write(f"    {rol} id={idv}\n")
                fh.write(f"        {str(f['titulo'])[:66]}\n")
                fh.write(f"        {precio} | {f['m2_util']} m2 | {f['dormitorios']}D "
                         f"{f['banos']}B | publicado hace {f['antiguedad_aviso_dias']} dias\n")
                fh.write(f"        {f['direccion']}\n")
                fh.write(f"        {f['url']}\n")
            fh.write("\n")

    # ── RESUMEN EN PANTALLA ──
    print("\n" + "=" * 70)
    resumen = defaultdict(int)
    for _, miembros, conf, _, _ in grupos_final:
        resumen[conf] += 1
    print(f"  Grupos detectados     : {len(grupos_final)}")
    for c in ("ALTA", "MEDIA", "BAJA"):
        print(f"    confianza {c:<6}    : {resumen[c]}")
    print(f"  Anuncios involucrados : {sum(len(g[1]) for g in grupos_final)}")
    print(f"  Filas sobrantes si se elimina el duplicado: "
          f"{sum(len(g[1]) - 1 for g in grupos_final)}")
    print("=" * 70)
    print(f"\n  -> {out_csv}")
    print(f"  -> {out_txt}")
    print("\n  Revisa primero los de confianza ALTA; los BAJA suelen ser\n"
          "  departamentos distintos del mismo edificio.")

    if "--limpiar" in sys.argv:
        if limite:
            print("\n  [limpieza] CANCELADA: no se puede limpiar con --limite "
                  "(solo se detectó una parte de los grupos).")
        else:
            limpiar_duplicados(grupos_final, por_id)
    print()


if __name__ == "__main__":
    main()
