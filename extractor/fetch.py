"""Descarga de la ficha, con el fallo tipado.

El punto ciego del scraper anterior (`scraper/portalinmobiliario.py:39-51`) era
devolver `None` para 403, 404, timeout y fin de paginacion por igual. Por eso sus
logs no tienen un solo codigo HTTP y nunca se supo si el portal bloqueaba o si
simplemente no habia mas datos. Aca cada final tiene nombre.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import httpx

from . import config as C


class Estado(str, Enum):
    OK = "ok"
    BLOQUEADO = "bloqueado"       # 403/429 tras agotar reintentos
    NO_EXISTE = "no_existe"       # 404/410, o el aviso se dio de baja
    CHALLENGE = "challenge"       # 200 pero es la pagina de verificacion
    RED = "red"                   # timeout, DNS, conexion caida
    ERROR_HTTP = "error_http"     # cualquier otro codigo


@dataclass
class Respuesta:
    estado: Estado
    status_code: int | None = None
    html: str | None = None
    motivo: str = ""
    desde_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.estado is Estado.OK


def _ruta_cache(id_aviso: str) -> Path:
    clave = hashlib.sha256(id_aviso.encode()).hexdigest()[:16]
    return C.CACHE_DIR / f"{id_aviso}-{clave}.html"


def _leer_cache(id_aviso: str) -> str | None:
    ruta = _ruta_cache(id_aviso)
    if not ruta.exists():
        return None
    edad_h = (time.time() - ruta.stat().st_mtime) / 3600
    if edad_h > C.CACHE_TTL_HORAS:
        return None
    return ruta.read_text(encoding="utf-8", errors="replace")


def _guardar_cache(id_aviso: str, html: str) -> None:
    C.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _ruta_cache(id_aviso).write_text(html, encoding="utf-8", errors="replace")


def es_challenge(html: str) -> bool:
    """Una pagina de verificacion responde 200 igual que una ficha.

    Se distingue por tamano y por la ausencia del bloque de datos: la ficha real
    trae el contexto de render o la tabla de especificaciones; el challenge no.
    """
    if len(html) < C.MIN_BYTES_FICHA:
        return True
    tiene_datos = ("__NORDIC_RENDERING_CTX__" in html
                   or "andes-table" in html
                   or "application/ld+json" in html)
    return not tiene_datos


def descargar(url: str, id_aviso: str, *, usar_cache: bool = True,
              cliente: httpx.Client | None = None) -> Respuesta:
    """Trae el HTML de una ficha. Una sola URL, sin paginacion ni rastreo."""
    if usar_cache:
        guardado = _leer_cache(id_aviso)
        if guardado is not None:
            return Respuesta(Estado.OK, 200, guardado, "cache", desde_cache=True)

    propio = cliente is None
    cli = cliente or httpx.Client(follow_redirects=True)
    try:
        for intento in range(MAX := C.MAX_REINTENTOS):
            try:
                r = cli.get(url, headers=C.CABECERAS, timeout=C.TIMEOUT_S)
            except httpx.HTTPError as e:
                if intento == MAX - 1:
                    return Respuesta(Estado.RED, None, None, f"{type(e).__name__}: {e}")
                time.sleep(2 * (intento + 1))
                continue

            if r.status_code == 200:
                if es_challenge(r.text):
                    return Respuesta(Estado.CHALLENGE, 200, None,
                                     f"HTTP 200 pero la pagina no trae la ficha "
                                     f"({len(r.text)} bytes): verificacion humana.")
                if usar_cache:
                    _guardar_cache(id_aviso, r.text)
                return Respuesta(Estado.OK, 200, r.text)

            if r.status_code in (403, 429):
                if intento == MAX - 1:
                    return Respuesta(Estado.BLOQUEADO, r.status_code, None,
                                     f"El portal respondio {r.status_code} tras "
                                     f"{MAX} intentos.")
                time.sleep(C.ESPERA_BLOQUEO_S[min(intento, len(C.ESPERA_BLOQUEO_S) - 1)])
                continue

            if r.status_code in (404, 410):
                return Respuesta(Estado.NO_EXISTE, r.status_code, None,
                                 "El aviso ya no existe o fue dado de baja.")

            return Respuesta(Estado.ERROR_HTTP, r.status_code, None,
                             f"Respuesta inesperada: HTTP {r.status_code}.")
        return Respuesta(Estado.RED, None, None, "Se agotaron los intentos.")
    finally:
        if propio:
            cli.close()
