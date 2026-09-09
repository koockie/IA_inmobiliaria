"""Validacion y canonicalizacion de la URL que pega el usuario.

Portal Inmobiliario y MercadoLibre son la misma plataforma: una ficha vive en
`/MLC-<id>-<slug>-_JM` en ambos dominios y el `id` es el mismo. Por eso el
extractor acepta las dos y guarda de que sitio vino.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .config import DOMINIOS

_ID = re.compile(r"MLC-?(\d{6,})", re.I)

# Rutas que tienen forma de ficha pero no lo son.
_NO_FICHA = ("/perfil/", "/tienda/", "/pagina/", "/catalogo/", "/ofertas",
             "/listado.", "/propiedades/", "/diario/", "/financiamiento/")


class UrlInvalida(ValueError):
    """La URL no apunta a una ficha de aviso que sepamos leer."""


@dataclass(frozen=True)
class Aviso:
    sitio: str          # pi | ml
    id_aviso: str       # solo digitos, igual que en la base historica
    url: str            # canonica, sin query ni fragmento
    dominio: str


def analizar(url_cruda: str) -> Aviso:
    """`analizar(url)` -> Aviso, o `UrlInvalida` con el motivo exacto.

    Nunca adivina: si no reconoce el dominio o no encuentra el id, falla con un
    mensaje que el backend puede mostrarle al usuario tal cual.
    """
    texto = (url_cruda or "").strip()
    if not texto:
        raise UrlInvalida("No enviaste ninguna URL.")
    if not texto.startswith(("http://", "https://")):
        texto = "https://" + texto

    partes = urlparse(texto)
    dominio = partes.netloc.lower().split(":")[0]
    if dominio not in DOMINIOS:
        raise UrlInvalida(
            f"El dominio '{dominio}' no esta soportado. Solo funcionan avisos de "
            "portalinmobiliario.com y mercadolibre.cl.")

    ruta = partes.path
    if any(p in ruta.lower() for p in _NO_FICHA):
        raise UrlInvalida(
            "Ese link no es la ficha de un aviso (parece un listado, un perfil o "
            "un catalogo). Abri el aviso y copia la URL de esa pagina.")

    m = _ID.search(ruta) or _ID.search(partes.query)
    if not m:
        raise UrlInvalida(
            "No encontre el codigo del aviso (MLC-...) en esa URL. Copiala desde "
            "la barra del navegador con el aviso abierto.")

    # Se descartan query y fragmento: traen parametros de sesion y tracking que
    # no identifican el aviso y ensucian la clave de cache.
    return Aviso(sitio=DOMINIOS[dominio], id_aviso=m.group(1),
                 url=f"https://{dominio}{ruta}", dominio=dominio)
