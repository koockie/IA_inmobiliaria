"""Lectura de la ficha. Tres fuentes independientes, en orden de preferencia.

1. `__NORDIC_RENDERING_CTX__` -- el modelo JSON que el servidor ya renderizo.
   Es la fuente buena: son datos, no maquetacion, y no depende de nombres de
   clase CSS que cambian sin aviso.
2. JSON-LD (`schema.org`) -- precio, moneda, id y la ruta de categorias.
3. Regex sobre el HTML -- ultimo recurso para coordenadas y descripcion.

Ningun campo se adivina: si las tres fuentes callan, queda en None.
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any

_DEC = json.JSONDecoder()
_CTX = re.compile(r'<script id="__NORDIC_RENDERING_CTX__"[^>]*>_n\.ctx\.r=')
_LD = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_THTD = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S)
# La coordenada real solo esta en el centro del mapa estatico. El HTML trae
# ademas un "latitude": -35.67 que es el centro geografico de Chile, no la
# propiedad: tomarlo seria un error silencioso de ~250 km.
_CENTRO = re.compile(r"center=(-?\d+\.\d+)(?:%2C|,)(-?\d+\.\d+)")
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_DESC_HTML = re.compile(r"ui-pdp-description__content[^>]*>(.*?)</p>", re.S)
# La linea de ubicacion siempre termina en la region. Sirve de respaldo cuando el
# portal sirve la variante "isBot", que no trae `appProps` y por tanto no trae el
# componente de ubicacion.
_DIR_HTML = re.compile(r">\s*([^<>{}]{5,160}?(?:RM \(Metropolitana\)|Metropolitana))\s*<")


def _texto(bruto: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", " ", bruto)).strip()


# --- fuente 1: contexto de render ------------------------------------------
def contexto(html: str) -> dict[str, Any] | None:
    m = _CTX.search(html)
    if not m:
        return None
    try:
        datos, _ = _DEC.raw_decode(html, m.end())
        return datos["appProps"]["pageProps"]["initialState"]
    except (ValueError, KeyError, TypeError):
        return None


def componentes(nodo: Any, tipo: str) -> list[dict]:
    """Todos los nodos del arbol con ese `type`, sin importar donde vivan.

    Recorrido generico a proposito: la maqueta cambia entre un aviso normal y un
    proyecto (`highlighted_specs_attrs_new` en uno, `content_left` en el otro),
    pero el `type` del componente se mantiene.
    """
    hallados: list[dict] = []
    pila: list[Any] = [nodo]
    while pila:
        n = pila.pop()
        if isinstance(n, dict):
            if n.get("type") == tipo:
                hallados.append(n)
            pila.extend(n.values())
        elif isinstance(n, list):
            pila.extend(n)
    return hallados


# --- fuente 2: JSON-LD ------------------------------------------------------
def json_ld(html: str) -> list[dict]:
    bloques = []
    for m in _LD.finditer(html):
        try:
            bloques.append(json.loads(m.group(1)))
        except ValueError:
            continue
    return bloques


def _de_tipo(bloques: list[dict], tipo: str) -> dict:
    return next((b for b in bloques if b.get("@type") == tipo), {})


# --- campos -----------------------------------------------------------------
def _moneda(codigo: str | None) -> str | None:
    if not codigo:
        return None
    return "UF" if codigo.upper() in ("CLF", "UF") else "CLP"


def _precio(est: dict | None, prod: dict) -> tuple[float | None, str | None]:
    """(valor, moneda). `CLF` es el codigo ISO de la UF; sin traducirlo, un
    precio en UF se leeria como pesos y el analisis quedaria 40.000x mal."""
    for c in componentes(est or {}, "price"):
        p = c.get("price") if isinstance(c.get("price"), dict) else c
        if isinstance(p, dict) and p.get("value") is not None:
            return float(p["value"]), _moneda(p.get("currency_id"))
    oferta = prod.get("offers") or {}
    if oferta.get("price") is not None:
        return float(oferta["price"]), _moneda(oferta.get("priceCurrency"))
    return None, None


def _ruta_categorias(bloques: list[dict]) -> list[str]:
    bc = _de_tipo(bloques, "BreadcrumbList")
    return [i.get("item", {}).get("name", "")
            for i in bc.get("itemListElement", [])]


def _de_la_ruta(ruta: list[str]) -> dict:
    """Operacion, tipo, comuna y barrio salen de la ruta de categorias.

    La comuna es la entrada siguiente a la region y el barrio la que sigue. Es
    mas fiable que partir la direccion por comas, que es lo que hacia el scraper
    anterior (`scraper/portalinmobiliario.py:104-106`) y fallaba seguido.
    """
    bajo = [r.lower() for r in ruta]
    salida: dict = {"operacion": None, "tipo": None, "comuna": None, "barrio": None}

    for r in bajo:
        if r.startswith("venta"):
            salida["operacion"] = "venta"
        elif r.startswith("arriendo"):
            salida["operacion"] = "arriendo"
        if r.startswith("casa"):
            salida["tipo"] = "casa"
        elif r.startswith("departamento"):
            salida["tipo"] = "departamento"

    idx = next((i for i, r in enumerate(bajo)
                if "metropolitana" in r or r.strip() == "rm"), None)
    if idx is not None:
        if idx + 1 < len(ruta):
            salida["comuna"] = ruta[idx + 1]
        if idx + 2 < len(ruta):
            salida["barrio"] = ruta[idx + 2]
    return salida


def _specs(est: dict | None, html: str) -> dict[str, str]:
    for c in componentes(est or {}, "technical_specifications"):
        pares = {a["id"]: a["text"]
                 for grupo in c.get("specs", [])
                 for a in grupo.get("attributes", [])
                 if isinstance(a, dict) and "id" in a and "text" in a}
        if pares:
            return pares
    return {_texto(k): _texto(v) for k, v in _THTD.findall(html)}


def _geo(est: dict | None, html: str) -> tuple[str | None, str | None]:
    for tipo in ("location_and_points", "location"):
        for c in componentes(est or {}, tipo):
            loc = (c.get("map_info") or {}).get("location") or {}
            if loc.get("latitude") and loc.get("longitude"):
                return str(loc["latitude"]), str(loc["longitude"])
    m = _CENTRO.search(html)
    return (m.group(1), m.group(2)) if m else (None, None)


def _direccion(est: dict | None, html: str) -> str | None:
    for tipo in ("location_and_points", "location"):
        for c in componentes(est or {}, tipo):
            for fila in c.get("content_rows", []):
                texto = (fila.get("title") or {}).get("text")
                if texto:
                    return str(texto).strip()
    m = _DIR_HTML.search(html)
    return _html.unescape(m.group(1)).strip() if m else None


def _descripcion(est: dict | None, html: str) -> str | None:
    for tipo in ("description_rex", "description"):
        for c in componentes(est or {}, tipo):
            cont = c.get("content")
            if isinstance(cont, str) and cont.strip():
                return cont.strip()
            if isinstance(cont, dict) and cont.get("text"):
                return str(cont["text"]).strip()
    m = _DESC_HTML.search(html)
    return _texto(m.group(1)) if m else None


def _titulo(est: dict | None, html: str, prod: dict) -> str | None:
    for c in componentes(est or {}, "header"):
        t = c.get("title")
        texto = t.get("text") if isinstance(t, dict) else t
        if texto:
            return str(texto).strip()
    m = _H1.search(html)
    if m:
        return _texto(m.group(1))
    return (prod.get("name") or "").strip() or None


def extraer(html: str) -> dict:
    """Todos los campos crudos de la ficha, tal como los publica el aviso.

    Devuelve textos sin convertir: pasar a numero y detectar rangos es trabajo de
    `normalize` y `validate`.
    """
    est = contexto(html)
    bloques = json_ld(html)
    prod = _de_tipo(bloques, "Product")
    ruta = _ruta_categorias(bloques)
    valor, moneda = _precio(est, prod)
    lat, lon = _geo(est, html)

    datos = {
        "id_aviso": (prod.get("productID") or "").replace("MLC", "") or None,
        "titulo": _titulo(est, html, prod),
        "precio_valor": valor,
        "precio_moneda": moneda,
        "lat": lat,
        "lon": lon,
        "direccion": _direccion(est, html),
        "descripcion": _descripcion(est, html),
        "specs": _specs(est, html),
        "ruta_categorias": ruta,
        "fuente_estructurada": est is not None,
    }
    datos.update(_de_la_ruta(ruta))
    return datos
