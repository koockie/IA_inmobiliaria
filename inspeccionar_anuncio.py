from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup


URL = "https://portalinmobiliario.com/MLC-3585368896-castillo-velasco-_JM"
# Ejemplos:
#   sproyecto malo precio por unidad : MLC-3585368896-castillo-velasco-_JM
#   proyecto con precio por unidad : MLC-3625552360-los-lilenes-ingevec-_JM
#   casa individual         : MLC-3571915704-maria-auxiliadora-3d-1b-e-y-b-_JM
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "es-CL,es;q=0.9",
}
SEP = "═" * 78


def titulo(txt: str) -> None:
    print(f"\n{SEP}\n  {txt}\n{SEP}")


def extraer_objeto_json(html: str, clave: str):
    """Extrae el objeto JSON que sigue a '"clave":{' balanceando llaves.
    """
    marca = f'"{clave}":{{'
    i = html.find(marca)
    if i == -1:
        return None
    start = i + len(marca) - 1
    depth, in_str, esc = 0, False, False
    for j in range(start, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start:j + 1])
                    except json.JSONDecodeError:
                        return None
    return None


def get(url: str) -> str:
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    guardar = "--guardar" in sys.argv
    url = args[0] if args else URL

    print(f"\nDescargando: {url}")
    html = get(url)
    soup = BeautifulSoup(html, "lxml")
    mlc = (re.search(r"MLC-?(\d+)", url) or [None, "?"])[1]


    titulo("1. GENERALES")
    es_proyecto = "quotable_models" in html or "Proyecto desde" in html
    print(f"  ID del aviso     : MLC{mlc}")
    print(f"  Título de página : {soup.title.get_text(strip=True) if soup.title else '?'}")
    print(f"  Tamaño del HTML  : {len(html):,} caracteres".replace(",", "."))
    print(f"  TIPO DE AVISO    : {'PROYECTO (varias unidades)' if es_proyecto else 'PROPIEDAD INDIVIDUAL'}")

    #LO QUE EXTRAE EL SCRAPER
    titulo("2. TABLA DE ESPECIFICACIONES (lo que lee el scraper actual)")
    filas = 0
    for row in soup.select("tr.andes-table__row, .andes-table tr"):
        th, td = row.find("th"), row.find("td")
        if th and td:
            etiqueta = th.get_text(" ", strip=True)
            valor = td.get_text(" ", strip=True)
            alerta = "  <-- RANGOO!!!!" if (" a " in valor or " - " in valor) else ""
            print(f"  {etiqueta:<26} = {valor}{alerta}")
            filas += 1
    if not filas:
        print("  (sin tabla de especificaciones)")

    #precios
    titulo("3. PRECIOS EN EL JSON")
    precios = re.findall(
        r'"price":\{"type":"price","value":(\d+),"currency_symbol":"([^"]+)"', html)
    if precios:
        for val, mon in dict.fromkeys(precios):
            print(f"  {mon} {int(val):,}".replace(",", "."))
    upper = re.search(r'"upper_label":\{"text":"([^"]+)"', html)
    if upper:
        print(f"  Etiqueta del precio: \"{upper.group(1)}\"")
    for etiqueta, patron in [("Precio original", r'"value":(\d+),"currency_id":"CLF"\}\}\}\},"title":\{"label":\{"text":"Precio original'),
                             ("Descuento", r'"color":"GREEN"\}\}\}\},"title":\{"label":\{"text":"([^"]*OFF[^"]*)"')]:
        m = re.search(patron, html)
        if m:
            print(f"  {etiqueta}: {m.group(1)}")

    # ubicacion
    titulo("4. UBICACIÓN")
    m = re.search(r"center=(-?\d+\.\d+)(?:%2C|,)(-?\d+\.\d+)", html)
    print(f"  Coordenadas : {m.group(1)}, {m.group(2)}" if m else "  Coordenadas : (no encontradas)")
    # la dirección  esta emn 'location' del JSON embebido
    loc = extraer_objeto_json(html, "location")
    direccion = None
    if loc:
        for clave in ("subtitle", "title", "address"):
            val = loc.get(clave)
            if isinstance(val, dict) and val.get("text"):
                direccion = val["text"]
                break
    if not direccion:
        crumbs = [a.get_text(strip=True) for a in soup.select("a.andes-breadcrumb__link")]
        direccion = " > ".join(crumbs) if crumbs else None
    print(f"  Dirección   : {direccion or '(no encontrada)'}")

    #fecha
    titulo("5. ANTIGÜEDAD DEL AVISO")
    m = re.search(r"[Pp]ublicado hace\s+(\d+)\s+(día|días|mes|meses|año|años)", html)
    print(f"  {m.group(0)}" if m else "  (no informa fecha de publicación , comun en proyectos)")

    # modelos internos si son proyectos
    modelos_info = []
    if es_proyecto:
        titulo("6. MODELOS DEL PROYECTO (quotable_models)")
        qm = extraer_objeto_json(html, "quotable_models")
        modelos = (qm or {}).get("models", [])
        print(f"  Se encontraron {len(modelos)} modelos:\n")
        for mod in modelos:
            attrs = [a["label"]["text"] for a in mod.get("attributes", []) if "label" in a]
            print(f"    · modelo_id = {mod.get('id')}")
            for a in attrs:
                print(f"        {a}")
            modelos_info.append(mod.get("id"))
            print()

        #UNIDADES DE CADA MODELO 
        titulo("7. UNIDADES INDIVIDUALES DE CADA MODELO")
        print("  (se consulta el endpoint interno /noindex/unregistered_quotations)\n")
        for mid in modelos_info:
            url_q = (f"https://portalinmobiliario.com/noindex/unregistered_quotations/"
                     f"MLC{mlc}?new_version=true&model_id={mid}")
            try:
                t = get(url_q)
            except Exception as e:  # noqa: BLE001
                print(f"    modelo {mid}: error -> {e}")
                continue
            mu = extraer_objeto_json(t, "model_units") or {}
            unidades = mu.get(str(mid), [])
            print(f"    ── modelo {mid}: {len(unidades)} unidades ──")
            for u in unidades:
                nombre = u.get("name", {}).get("text", "?")
                desc = u.get("description", {}).get("text", "")
                print(f"       Unidad {nombre}: {desc}")
                for a in u.get("attributes", []):
                    tit = a.get("title", {}).get("text", "?")
                    lab = a.get("label", {}).get("text", "?")
                    print(f"           {tit:<20} = {lab}")
                hay_precio = any(k in json.dumps(u) for k in ("price", "amount", "UF"))
                print(f"           {'PRECIO':<20} = {'(ver JSON)' if hay_precio else 'NO PUBLICADO en esta unidad'}")
                print()
    else:
        titulo("6-7. MODELOS / UNIDADES")
  

    # DESCRIPCIÓN 
    titulo("8. DESCRIPCIÓN")
    desc = soup.select_one(".ui-pdp-description__content")
    print(f"  {desc.get_text(' ', strip=True)[:600]}..." if desc else "  (sin descripción)")


if __name__ == "__main__":
    main()
