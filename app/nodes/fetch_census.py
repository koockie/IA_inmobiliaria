"""Rama estructurada: contexto socioeconómico del sector (Censo manzana). Sin LLM."""
from __future__ import annotations

from app.state import GraphState
from app.tools.census import manzana_context


def fetch_census(state: GraphState) -> dict:
    geo = state.get("geo")
    if not geo:
        return {"census": {"disponible": False, "motivo": "Sin geocodificación."}}
    return {"census": manzana_context(geo["lat"], geo["lon"])}
