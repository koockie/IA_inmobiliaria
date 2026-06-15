"""Wrapper de búsqueda web con Tavily (tier gratis ~1000 créditos/mes).

Devuelve contexto limpio (título, snippet, url) listo para que el LLM lo resuma. Tolera
ausencia de API key o errores de red devolviendo lista vacía (el synthesizer lo informa).
"""
from __future__ import annotations

from app.config import get_settings


def search(query: str, max_results: int = 3) -> list[dict]:
    """Ejecuta una búsqueda en Tavily y devuelve resultados normalizados."""
    settings = get_settings()
    if not settings.tavily_api_key:
        return []

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        resp = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
        )
    except Exception:  # noqa: BLE001 - cualquier fallo => sin resultados, no rompe el flujo
        return []

    results = []
    for item in resp.get("results", []):
        results.append(
            {
                "query": query,
                "titulo": item.get("title"),
                "contenido": item.get("content"),
                "url": item.get("url"),
            }
        )
    return results
