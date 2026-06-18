"""Contexto socioeconómico a nivel MANZANA desde el Censo 2024 (INE).

El INE publica la capa "Manzana Entidad Censo 2024" (189 variables) sobre infraestructura
ArcGIS. Se consulta el FeatureServer REST por punto (intersección espacial), que devuelve
la manzana que contiene la coordenada y sus atributos, en GeoJSON. Solo usa `httpx`.

Para activarlo: confirmar la URL de la capa en geoine-ine-chile.opendata.arcgis.com y
ponerla en `INE_ARCGIS_LAYER_URL` (.env). Mientras no esté, devuelve {disponible: False}.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

from app.config import get_settings

# Campos "interesantes" del censo (nombres aproximados; varían según la capa publicada).
# Se hace match flexible por patrón sobre las propiedades devueltas.
INTERES = {
    "poblacion": r"(total.*pers|pobl|personas)",
    "viviendas": r"(total.*viv|viviendas)",
    "hogares": r"(hogares)",
    "escolaridad": r"(escolarid|a[nñ]os.*estudio)",
}

FUENTE = {
    "nombre": "INE — Censo de Población y Vivienda 2024 (nivel manzana)",
    "url": "https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos",
}


def _pick_fields(props: dict) -> dict:
    """Extrae algunas variables de interés haciendo match flexible por nombre."""
    out: dict[str, object] = {}
    for etiqueta, patron in INTERES.items():
        for key, value in props.items():
            if re.search(patron, key, re.IGNORECASE):
                out[etiqueta] = {"campo": key, "valor": value}
                break
    return out


def manzana_context(lat: float, lon: float) -> dict:
    """Devuelve el contexto socioeconómico de la manzana que contiene el punto."""
    settings = get_settings()
    layer_url = settings.ine_arcgis_layer_url
    if not layer_url:
        return {
            "disponible": False,
            "estado": "no_configurado",
            "motivo": (
                "El contexto socioeconómico del sector NO fue consultado porque aún no se "
                "configuró la capa del Censo (INE_ARCGIS_LAYER_URL). NO significa que el censo "
                "no tenga datos para esta ubicación; simplemente no se consultó la fuente."
            ),
            "fuente": FUENTE,
        }

    # ArcGIS REST: query por punto con intersección, salida GeoJSON.
    params = {
        "f": "geojson",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
    }
    query_url = layer_url.rstrip("/") + "/query"
    try:
        resp = httpx.get(query_url, params=params, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"disponible": False, "estado": "error_consulta",
                "motivo": f"Se intentó consultar el INE pero falló: {exc}", "fuente": FUENTE}

    features = data.get("features", [])
    if not features:
        return {"disponible": False, "estado": "sin_cobertura",
                "motivo": "Se consultó el censo pero el punto no cae en ninguna manzana censada.",
                "fuente": FUENTE}

    # Soporta GeoJSON ("properties") y Esri JSON ("attributes") según el tipo de servicio.
    first = features[0]
    props = first.get("properties") or first.get("attributes") or {}
    return {
        "disponible": True,
        "nivel": "manzana",
        "variables_clave": _pick_fields(props),
        "atributos_crudos": props,  # el synthesizer puede usar lo que necesite
        "fuente": FUENTE,
    }
