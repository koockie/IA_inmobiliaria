"""Scraper de PortalInmobiliario (MercadoLibre Chile inmuebles).

Listados server-rendered con clases estables `ui-search-*` / `poly-*` (verificado 2026-06).
- Búsqueda:   {PI_BASE}/{operacion}/{tipo}/{slug_comuna}[_Desde_N]
- Ficha:      https://portalinmobiliario.com/MLC-<id>-...-_JM  (tabla andes-table + mapa)
"""
from __future__ import annotations

import random
import re
import time
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

from scraper.config import (
    COMUNAS_PI, MAX_RETRIES, PI_BASE, PI_PAGE_SIZE, RATE_MAX_S, RATE_MIN_S,
    TIMEOUT_S, USER_AGENT,
)
from scraper.normalize import extract_int, parse_precio, precios_normalizados
from scraper.schema import empty_record

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "es-CL,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

_RE_MLC = re.compile(r"MLC-?(\d+)")
_RE_LATLON = re.compile(r"center=(-?\d+\.\d+)(?:%2C|,)(-?\d+\.\d+)")
_RE_PUBLICADO = re.compile(r"[Pp]ublicado hace\s+(\d+)\s+(día|dias|días|mes|meses|año|años)")


def _sleep() -> None:
    time.sleep(random.uniform(RATE_MIN_S, RATE_MAX_S))


def _get(client: httpx.Client, url: str) -> str | None:
    for intento in range(1, MAX_RETRIES + 1):
        try:
            resp = client.get(url, headers=_HEADERS, timeout=TIMEOUT_S, follow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 429):
                time.sleep(5 * intento)  # backoff si nos frenan
                continue
            return None
        except httpx.HTTPError:
            time.sleep(2 * intento)
    return None


def build_search_url(operacion: str, tipo: str, comuna: str, offset: int = 0) -> str:
    slug = COMUNAS_PI[comuna]
    url = f"{PI_BASE}/{operacion}/{tipo}/{slug}"
    if offset:
        url += f"_Desde_{offset + 1}"
    return url


def _parse_card(card, operacion: str, tipo: str, comuna: str) -> dict | None:
    link = card.select_one("a[href*='MLC-'], a[href*='MLC']")
    if not link or not link.get("href"):
        return None
    href = link["href"].split("#")[0].split("?")[0]
    m = _RE_MLC.search(href)
    if not m:
        return None  # tarjeta de publicidad u otro artefacto

    rec = empty_record()
    rec["sitio"] = "pi"
    rec["id_aviso"] = m.group(1)
    rec["url"] = href
    rec["operacion"] = operacion
    rec["tipo"] = tipo
    rec["comuna"] = comuna
    rec["fecha_scrape"] = date.today().isoformat()

    titulo = card.select_one("h3, .poly-component__title, .ui-search-item__title")
    rec["titulo"] = titulo.get_text(strip=True) if titulo else None

    moneda = card.select_one(".andes-money-amount__currency-symbol")
    valor = card.select_one(".andes-money-amount__fraction")
    precio_valor, precio_moneda = parse_precio(
        moneda.get_text(strip=True) if moneda else None,
        valor.get_text(strip=True) if valor else None,
    )
    rec["precio_valor"], rec["precio_moneda"] = precio_valor, precio_moneda
    rec["precio_clp"], rec["precio_uf"] = precios_normalizados(precio_valor, precio_moneda)

    for attr in card.select(".poly-attributes_list__item, .ui-search-card-attributes__attribute"):
        texto = attr.get_text(" ", strip=True).lower()
        if "dormitorio" in texto or "monoambiente" in texto:
            rec["dormitorios"] = 0 if "monoambiente" in texto else extract_int(texto)
        elif "baño" in texto:
            rec["banos"] = extract_int(texto)
        elif "m²" in texto or "m2" in texto:
            rec["m2_util"] = extract_int(texto)

    ubic = card.select_one(".poly-component__location, .ui-search-item__location")
    if ubic:
        rec["direccion"] = ubic.get_text(" ", strip=True)
        partes = [p.strip() for p in rec["direccion"].split(",")]
        if len(partes) >= 2:
            rec["barrio"] = partes[-2]
    return rec


def scrape_listado(client: httpx.Client, operacion: str, tipo: str, comuna: str,
                   max_paginas: int | None = None):
    """Generador de registros de tarjetas, recorriendo la paginación."""
    offset, pagina = 0, 0
    while True:
        pagina += 1
        if max_paginas and pagina > max_paginas:
            return
        url = build_search_url(operacion, tipo, comuna, offset)
        html = _get(client, url)
        if html is None:
            print(f"    [pi] sin respuesta: {url}")
            return
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("li.ui-search-layout__item")
        if not cards:
            return  # fin de la paginación
        vistos = 0
        for card in cards:
            rec = _parse_card(card, operacion, tipo, comuna)
            if rec:
                vistos += 1
                yield rec
        print(f"    [pi] {comuna}/{operacion}/{tipo} pág.{pagina}: {vistos} avisos")
        offset += PI_PAGE_SIZE
        _sleep()


def scrape_detalle(client: httpx.Client, url: str) -> dict | None:
    """Extrae campos extra desde la ficha MLC. None si la página no responde."""
    html = _get(client, url)
    if html is None:
        return None
    soup = BeautifulSoup(html, "lxml")
    campos: dict = {}

    # Tabla de especificaciones (andes-table): th = etiqueta, td = valor.
    # OJO: solo escribir cuando el valor parsea a número — un None aquí pisaría
    # el dato bueno que ya viene de la tarjeta del listado (bug corregido).
    def _set(clave: str, valor_texto: str) -> None:
        v = extract_int(valor_texto)
        if v is not None:
            campos[clave] = v

    for row in soup.select("tr.andes-table__row, .andes-table tr"):
        th, td = row.find("th"), row.find("td")
        if not th or not td:
            continue
        etiqueta = th.get_text(" ", strip=True).lower()
        valor = td.get_text(" ", strip=True)
        if "superficie total" in etiqueta:
            _set("m2_total", valor)
        elif "superficie útil" in etiqueta or "superficie util" in etiqueta:
            _set("m2_util", valor)
        elif "dormitorio" in etiqueta:
            if "monoambiente" in valor.lower():
                campos["dormitorios"] = 0
            else:
                _set("dormitorios", valor)
        elif etiqueta.startswith("baño"):
            _set("banos", valor)
        elif "estacionamiento" in etiqueta:
            _set("estacionamientos", valor)
        elif "bodega" in etiqueta:
            _set("bodegas", valor)
        elif "antigüedad" in etiqueta or "antiguedad" in etiqueta:
            anos = extract_int(valor)
            if anos is not None:
                campos["antiguedad_anos"] = anos
                campos["ano_construccion"] = date.today().year - anos
        elif "gastos comunes" in etiqueta:
            _set("gastos_comunes_clp", valor)

    desc = soup.select_one(".ui-pdp-description__content")
    if desc:
        campos["descripcion"] = desc.get_text(" ", strip=True)[:2000]

    # "Publicado hace N días/meses/años" (los proyectos no lo muestran -> NULL)
    m_pub = _RE_PUBLICADO.search(html)
    if m_pub:
        n, unidad = int(m_pub.group(1)), m_pub.group(2)
        dias = n if unidad.startswith("d") else n * 30 if unidad.startswith("m") else n * 365
        campos["antiguedad_aviso_dias"] = dias
        campos["fecha_publicacion"] = (date.today() - timedelta(days=dias)).isoformat()

    m = _RE_LATLON.search(html)
    if m:
        campos["lat"], campos["lon"] = m.group(1), m.group(2)

    _sleep()
    return campos
