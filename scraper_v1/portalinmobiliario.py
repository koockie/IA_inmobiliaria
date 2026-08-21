"""Scraper v1 de PortalInmobiliario: igual que el v0 pero EXCLUYE PROYECTOS
y aborta si el portal empieza a bloquear.

Diferencias con `scraper/portalinmobiliario.py` (que no se modifica):
  - descarta los avisos de proyectos ya en la tarjeta del listado (ahorra requests)
  - segunda verificación en la ficha, por si alguno pasó el primer filtro
  - detecta el bloqueo anti-bot y detiene la corrida en vez de guardar basura
"""
from __future__ import annotations

import random
import re
import time
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

from scraper.normalize import extract_int, parse_precio, precios_normalizados
from scraper_v1.config import (
    COMUNAS_PI, MAX_RETRIES, PI_BASE, PI_PAGE_SIZE, RATE_MAX_S, RATE_MIN_S,
    TAM_MINIMO_FICHA, TIMEOUT_S, USER_AGENT,
)
from scraper_v1.proyectos import es_proyecto, senales_en_ficha, senales_en_tarjeta
from scraper_v1.storage import empty_record

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "es-CL,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

_RE_MLC = re.compile(r"MLC-?(\d+)")
_RE_LATLON = re.compile(r"center=(-?\d+\.\d+)(?:%2C|,)(-?\d+\.\d+)")
_RE_PUBLICADO = re.compile(r"[Pp]ublicado hace\s+(\d+)\s+(día|dias|días|mes|meses|año|años)")


class PortalBloqueado(RuntimeError):
    """El portal está pidiendo verificación anti-bot: hay que detener la corrida."""


def _sleep() -> None:
    time.sleep(random.uniform(RATE_MIN_S, RATE_MAX_S))


def _revisar_bloqueo(resp: httpx.Response, es_ficha: bool) -> None:
    url_final = str(resp.url)
    if "account-verification" in url_final or "/gz/" in url_final:
        raise PortalBloqueado(
            f"El portal redirigió a verificación anti-bot ({url_final[:70]}...)")
    if es_ficha and len(resp.text) < TAM_MINIMO_FICHA:
        raise PortalBloqueado(
            f"Respuesta anormalmente corta ({len(resp.text)} caracteres): "
            "probable bloqueo encubierto.")


def _get(client: httpx.Client, url: str, es_ficha: bool = False) -> str | None:
    for intento in range(1, MAX_RETRIES + 1):
        try:
            resp = client.get(url, headers=_HEADERS, timeout=TIMEOUT_S, follow_redirects=True)
            if resp.status_code == 200:
                _revisar_bloqueo(resp, es_ficha)
                return resp.text
            if resp.status_code in (403, 429):
                time.sleep(5 * intento)
                continue
            return None
        except httpx.HTTPError:
            time.sleep(2 * intento)
    return None


def build_search_url(operacion: str, tipo: str, comuna: str, offset: int = 0) -> str:
    url = f"{PI_BASE}/{operacion}/{tipo}/{COMUNAS_PI[comuna]}"
    return url + (f"_Desde_{offset + 1}" if offset else "")


def _parse_card(card, operacion: str, tipo: str, comuna: str) -> dict | None:
    link = card.select_one("a[href*='MLC-'], a[href*='MLC']")
    if not link or not link.get("href"):
        return None
    href = link["href"].split("#")[0].split("?")[0]
    m = _RE_MLC.search(href)
    if not m:
        return None

    rec = empty_record()
    rec.update({"sitio": "pi", "id_aviso": m.group(1), "url": href,
                "operacion": operacion, "tipo": tipo, "comuna": comuna,
                "fecha_scrape": date.today().isoformat(), "es_proyecto": 0})

    # ── Filtro de proyectos, ya en la tarjeta ──
    senales = senales_en_tarjeta(card)
    if es_proyecto(senales):
        rec["es_proyecto"] = 1
        rec["senales_proyecto"] = " | ".join(senales)

    titulo = card.select_one("h3, .poly-component__title, .ui-search-item__title")
    rec["titulo"] = titulo.get_text(strip=True) if titulo else None

    moneda = card.select_one(".andes-money-amount__currency-symbol")
    valor = card.select_one(".andes-money-amount__fraction")
    precio_valor, precio_moneda = parse_precio(
        moneda.get_text(strip=True) if moneda else None,
        valor.get_text(strip=True) if valor else None)
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
    offset, pagina = 0, 0
    while True:
        pagina += 1
        if max_paginas and pagina > max_paginas:
            return
        html = _get(client, build_search_url(operacion, tipo, comuna, offset))
        if html is None:
            print(f"    [v1] sin respuesta en pág.{pagina}")
            return
        cards = BeautifulSoup(html, "lxml").select("li.ui-search-layout__item")
        if not cards:
            return
        n_ok = n_proy = 0
        for card in cards:
            rec = _parse_card(card, operacion, tipo, comuna)
            if rec:
                n_proy += rec["es_proyecto"]
                n_ok += not rec["es_proyecto"]
                yield rec
        print(f"    [v1] {comuna}/{operacion}/{tipo} pág.{pagina}: "
              f"{n_ok} viviendas, {n_proy} proyectos excluidos")
        offset += PI_PAGE_SIZE
        _sleep()


def scrape_detalle(client: httpx.Client, url: str) -> dict | None:
    """Campos extra de la ficha. Si resulta ser un proyecto, devuelve {es_proyecto: 1}."""
    html = _get(client, url, es_ficha=True)
    if html is None:
        return None
    soup = BeautifulSoup(html, "lxml")

    specs: dict[str, str] = {}
    for row in soup.select("tr.andes-table__row, .andes-table tr"):
        th, td = row.find("th"), row.find("td")
        if th and td:
            specs[th.get_text(" ", strip=True)] = td.get_text(" ", strip=True)

    # ── Segunda barrera: ¿se coló un proyecto? ──
    senales = senales_en_ficha(html, specs)
    if es_proyecto(senales):
        _sleep()
        return {"es_proyecto": 1, "senales_proyecto": " | ".join(senales)}

    campos: dict = {}

    def _set(clave: str, valor_texto: str) -> None:
        v = extract_int(valor_texto)
        if v is not None:
            campos[clave] = v

    for etiqueta, valor in specs.items():
        low = etiqueta.lower()
        if "superficie total" in low:
            _set("m2_total", valor)
        elif "superficie útil" in low or "superficie util" in low:
            _set("m2_util", valor)
        elif "dormitorio" in low:
            if "monoambiente" in valor.lower():
                campos["dormitorios"] = 0
            else:
                _set("dormitorios", valor)
        elif low.startswith("baño"):
            _set("banos", valor)
        elif "estacionamiento" in low:
            _set("estacionamientos", valor)
        elif "bodega" in low:
            _set("bodegas", valor)
        elif "antigüedad" in low or "antiguedad" in low:
            anos = extract_int(valor)
            if anos is not None:
                campos["antiguedad_anos"] = anos
                campos["ano_construccion"] = date.today().year - anos
        elif "gastos comunes" in low:
            _set("gastos_comunes_clp", valor)

    desc = soup.select_one(".ui-pdp-description__content")
    if desc:
        campos["descripcion"] = desc.get_text(" ", strip=True)[:2000]

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
