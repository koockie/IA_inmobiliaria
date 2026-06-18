"""Rama estructurada: POIs cercanos (Google Places). Determinista, sin LLM."""
from __future__ import annotations

from app.config import get_settings
from app.state import GraphState
from app.tools.google_places import fetch_pois as _fetch_pois


def fetch_pois(state: GraphState) -> dict:
    geo = state.get("geo")
    if not geo:
        return {"pois": {"error": "Sin geocodificación, no se consultan POIs."}}
    radius = get_settings().poi_radius_m
    return {"pois": _fetch_pois(geo["lat"], geo["lon"], radius)}
