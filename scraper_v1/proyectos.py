"""Detección de PROYECTOS inmobiliarios (un aviso = varias viviendas).

Por qué se excluyen del dataset
-------------------------------
En un proyecto, el aviso no describe una vivienda concreta: la superficie, los
dormitorios y los baños vienen como RANGOS ("21.5 m² a 239.48 m²", "1 a 3") y el precio
es un "Desde". El parser guarda el mínimo de cada campo, produciendo una fila que
describe una vivienda que no existe — peor que un dato faltante, porque es un dato falso.

Se verificó que las unidades individuales sí se pueden listar (endpoint
/noindex/unregistered_quotations), con superficie, orientación y piso reales, pero
NO traen el precio: se carga por JavaScript al seleccionar la unidad. Sin precio no
sirven para entrenar el modelo, así que se excluye el aviso completo.

Estrategia
----------
Dos barreras, para gastar el mínimo de requests:
  1. En la TARJETA del listado (gratis: ya tenemos el HTML del listado).
  2. En la FICHA de detalle (por si algo pasó la primera).
Cada exclusión registra QUÉ señal la delató, para poder auditar el criterio.
"""
from __future__ import annotations

import re

# Un rango tipo "21.5 m² a 239.48 m²" o "1 a 3"
_RE_RANGO = re.compile(r"\d+(?:[.,]\d+)?\s*(?:m²)?\s*(?:a|-)\s*\d+(?:[.,]\d+)?")


def senales_en_tarjeta(card) -> list[str]:
    """Señales de proyecto visibles en la tarjeta del listado (BeautifulSoup Tag)."""
    senales: list[str] = []
    texto = card.get_text(" ", strip=True)

    if re.search(r"\bPROYECTO\b", texto):
        senales.append("etiqueta_PROYECTO")
    if re.search(r"\bDesde\b", texto):
        senales.append("precio_desde")
    if re.search(r"\bunidades disponibles\b", texto, re.I):
        senales.append("unidades_disponibles")

    # atributos en rango: "1 a 3 dormitorios", "21 - 239 m² útiles"
    for attr in card.select(".poly-attributes_list__item, .ui-search-card-attributes__attribute"):
        t = attr.get_text(" ", strip=True)
        if _RE_RANGO.search(t):
            senales.append("atributos_en_rango")
            break
    return senales


def senales_en_ficha(html: str, specs: dict[str, str]) -> list[str]:
    """Señales de proyecto en la ficha de detalle (segunda barrera)."""
    senales: list[str] = []

    if "quotable_models" in html:
        senales.append("quotable_models")
    if "Proyecto desde" in html:
        senales.append("precio_proyecto_desde")

    for etiqueta in specs:
        low = etiqueta.lower()
        if "unidades totales" in low:
            senales.append("campo_unidades_totales")
        elif "fecha de entrega" in low:
            senales.append("campo_fecha_entrega")

    for etiqueta, valor in specs.items():
        low = etiqueta.lower()
        if ("superficie" in low or "dormitorio" in low or "baño" in low) and _RE_RANGO.search(valor):
            senales.append("especificaciones_en_rango")
            break
    return senales


def es_proyecto(senales: list[str]) -> bool:
    """Basta una señal fuerte, o dos débiles, para clasificar como proyecto."""
    fuertes = {"etiqueta_PROYECTO", "quotable_models", "precio_proyecto_desde",
               "campo_unidades_totales", "especificaciones_en_rango"}
    if any(s in fuertes for s in senales):
        return True
    return len(senales) >= 2
