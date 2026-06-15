"""Tests de las tools que no requieren LLM ni red (usan mocks/datos locales)."""
from __future__ import annotations

from app.tools.crime import crime_context
from app.tools.geocoding import haversine_m
from app.tools.pois import _build_query, _classify


def test_haversine_zero():
    assert haversine_m(-33.45, -70.66, -33.45, -70.66) == 0


def test_haversine_known_distance():
    # ~ distancia Plaza de Armas (Stgo) a un punto ~1km al norte
    d = haversine_m(-33.4372, -70.6506, -33.4282, -70.6506)
    assert 950 < d < 1050


def test_classify_categories():
    assert _classify({"amenity": "school"}) == "colegios"
    assert _classify({"highway": "bus_stop"}) == "locomocion"
    assert _classify({"shop": "supermarket"}) == "abastecimiento"
    assert _classify({"leisure": "park"}) == "areas_verdes"
    assert _classify({"amenity": "hospital"}) == "salud"
    assert _classify({"amenity": "fuel"}) is None


def test_build_query_contains_point_and_radius():
    q = _build_query(-33.45, -70.66, 800)
    assert "around:800,-33.45,-70.66" in q
    assert q.startswith("[out:json]")


def test_crime_context_known_comuna():
    res = crime_context("Las Condes")
    assert res["disponible"] is True
    assert res["tasa_100k_hab"] > 0
    assert "disclaimer" in res


def test_crime_context_accent_insensitive():
    # "Ñuñoa" debe matchear "Nunoa" del dataset
    res = crime_context("Ñuñoa")
    assert res["disponible"] is True


def test_crime_context_unknown_comuna():
    res = crime_context("ComunaInexistente")
    assert res["disponible"] is False
    assert "promedio_dataset_100k" in res
