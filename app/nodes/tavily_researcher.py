"""Rama de investigación: ejecuta las queries del planner en Tavily y recolecta contexto."""
from __future__ import annotations

from app.state import GraphState
from app.tools.tavily_client import search


def tavily_researcher(state: GraphState) -> dict:
    queries = state.get("search_queries") or []
    hallazgos: list[dict] = []
    vistos: set[str] = set()

    for query in queries:
        for item in search(query, max_results=3):
            url = item.get("url")
            if url and url in vistos:
                continue
            if url:
                vistos.add(url)
            hallazgos.append(item)

    return {"research": hallazgos}
