"""Normalización de valores: precios UF/CLP, superficies, enteros."""
from __future__ import annotations

import re
from functools import lru_cache

import httpx


@lru_cache(maxsize=1)
def uf_del_dia() -> float | None:
    """Valor de la UF en pesos hoy (mindicador.cl, gratis). None si no responde."""
    try:
        resp = httpx.get("https://mindicador.cl/api/uf", timeout=15)
        resp.raise_for_status()
        serie = resp.json().get("serie", [])
        return float(serie[0]["valor"]) if serie else None
    except Exception:  # noqa: BLE001 - sin UF igual guardamos el precio original
        return None


def parse_number(text: str | None) -> float | None:
    """'5.500' -> 5500.0 ; '350.000.000' -> 350000000.0 ; '99,5' -> 99.5"""
    if not text:
        return None
    cleaned = re.sub(r"[^\d,\.]", "", str(text))
    if not cleaned:
        return None
    # formato chileno: '.' miles, ',' decimales
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_precio(moneda_texto: str | None, valor_texto: str | None) -> tuple[float | None, str | None]:
    """('UF', '5.500') -> (5500.0, 'UF') ; ('$', '350.000.000') -> (350000000.0, 'CLP')"""
    valor = parse_number(valor_texto)
    if valor is None:
        return None, None
    moneda_raw = (moneda_texto or "").strip().upper()
    moneda = "UF" if "UF" in moneda_raw else "CLP"
    return valor, moneda


def precios_normalizados(valor: float | None, moneda: str | None) -> tuple[float | None, float | None]:
    """Devuelve (precio_clp, precio_uf) usando la UF del día."""
    if valor is None:
        return None, None
    uf = uf_del_dia()
    if moneda == "UF":
        return (round(valor * uf) if uf else None, valor)
    return (valor, round(valor / uf, 2) if uf else None)


def extract_int(text: str | None) -> int | None:
    """'3 dormitorios' -> 3 ; '243 m² útiles' -> 243"""
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d{3})*)", str(text))
    return int(m.group(1).replace(".", "")) if m else None
