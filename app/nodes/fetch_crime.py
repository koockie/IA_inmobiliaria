"""Rama estructurada: contexto delictual comunal (CEAD). Determinista, sin LLM."""
from __future__ import annotations

from app.config import get_settings
from app.state import GraphState
from app.tools.crime import crime_context


def fetch_crime(state: GraphState) -> dict:
    if not get_settings().enable_crime:
        return {"crime": {"disponible": False, "motivo": "Componente desactivado."}}
    geo = state.get("geo") or {}
    return {"crime": crime_context(geo.get("comuna"))}
