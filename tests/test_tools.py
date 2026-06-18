"""Tests de las tools que no requieren LLM ni red (usan mocks/datos locales)."""
from __future__ import annotations

from app.tools.crime import crime_context
from app.tools.google_geocoding import haversine_m, parse_geocode_result
from app.tools.google_places import CATEGORIES


def test_haversine_zero():
    assert haversine_m(-33.45, -70.66, -33.45, -70.66) == 0


def test_haversine_known_distance():
    # ~ distancia Plaza de Armas (Stgo) a un punto ~1km al norte
    d = haversine_m(-33.4372, -70.6506, -33.4282, -70.6506)
    assert 950 < d < 1050


def test_google_categories_cubren_lo_esperado():
    # Las categorías del análisis deben existir con tipos de Google asociados
    assert set(CATEGORIES) == {
        "colegios", "universidades", "locomocion", "abastecimiento", "areas_verdes", "salud"
    }
    assert "school" in CATEGORIES["colegios"]
    # 'university' debe estar SEPARADO de 'colegios' (no contaminar)
    assert "university" not in CATEGORIES["colegios"]
    assert CATEGORIES["universidades"] == ["university"]
    assert "supermarket" in CATEGORIES["abastecimiento"]
    assert all(len(types) >= 1 for types in CATEGORIES.values())


def test_parse_geocode_result_extrae_comuna_y_region():
    # Respuesta simulada de la Geocoding API v4 para una dirección en Las Condes
    result = {
        "formattedAddress": "Av. Apoquindo 4000, Las Condes, Región Metropolitana, Chile",
        "location": {"latitude": -33.41, "longitude": -70.58},
        "addressComponents": [
            {"longText": "4000", "types": ["street_number"]},
            {"longText": "Avenida Apoquindo", "types": ["route"]},
            {"longText": "Barrio El Golf", "types": ["neighborhood", "political"]},
            {"longText": "Las Condes", "types": ["locality", "political"]},
            {"longText": "Las Condes", "types": ["administrative_area_level_3", "political"]},
            {"longText": "Santiago", "types": ["administrative_area_level_2", "political"]},
            {"longText": "Región Metropolitana", "types": ["administrative_area_level_1", "political"]},
            {"longText": "Chile", "types": ["country", "political"]},
        ],
    }
    parsed = parse_geocode_result(result)
    assert parsed["lat"] == -33.41
    assert parsed["lon"] == -70.58
    assert parsed["comuna"] == "Las Condes"
    assert parsed["region"] == "Región Metropolitana"
    assert parsed["barrio"] == "Barrio El Golf"
    assert "Apoquindo" in parsed["display_name"]


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
