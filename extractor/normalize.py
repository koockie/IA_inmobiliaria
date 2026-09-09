"""Conversion de textos a numeros y normalizacion de precios.

Corrige el bug mas caro del scraper anterior. `scraper/normalize.py:10` decora
`uf_del_dia()` con `@lru_cache(maxsize=1)`, que cachea tambien el `None`: cuando
mindicador.cl no respondio el 2026-07-27, los 3.804 avisos publicados en UF de
ese dia quedaron sin `precio_clp`, el 100 % de ellos, un cuarto del dataset.

Aca el fallo no se cachea, hay respaldo en disco del ultimo valor bueno, y la UF
que se uso queda guardada en la fila para que la conversion sea reproducible.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date

import httpx

from . import config as C

_NUM = re.compile(r"-?\d+(?:[.,]\d+)*")
# "1 a 3", "21.5 m2 a 239.48 m2", "85.4 - 239.48 m2": el aviso publica un rango
# porque es un proyecto con varias unidades, no una propiedad concreta.
_RANGO = re.compile(r"\d[\d.,]*\s*(?:m²|m2)?\s*(?:a|-|hasta|–)\s*\d[\d.,]*", re.I)

_cache_uf: tuple[float, str, float] | None = None   # (valor, origen, momento)


def es_rango(texto: str | None) -> bool:
    return bool(texto and _RANGO.search(texto))


def numero(texto: str | float | int | None) -> float | None:
    """Primer numero del texto, en formato chileno (`.` miles, `,` decimal).

    Devuelve None en vez de adivinar cuando no hay nada que leer.
    """
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto)
    m = _NUM.search(str(texto))
    if not m:
        return None
    crudo = m.group(0)
    if "," in crudo:                       # 1.234,56 -> 1234.56
        crudo = crudo.replace(".", "").replace(",", ".")
    elif crudo.count(".") == 1:
        entero, dec = crudo.split(".")
        # "1.234" son mil doscientos treinta y cuatro; "21.5" son veintiuno y medio.
        if len(dec) == 3 and len(entero) <= 3:
            crudo = entero + dec
    else:
        crudo = crudo.replace(".", "")
    try:
        return float(crudo)
    except ValueError:
        return None


def entero(texto: str | None) -> int | None:
    v = numero(texto)
    return int(v) if v is not None else None


def _guardar_uf(valor: float) -> None:
    try:
        C.UF_RESPALDO.parent.mkdir(parents=True, exist_ok=True)
        C.UF_RESPALDO.write_text(
            json.dumps({"valor": valor, "fecha": date.today().isoformat()}),
            encoding="utf-8")
    except OSError:
        pass


def _uf_de_respaldo() -> tuple[float | None, str]:
    try:
        d = json.loads(C.UF_RESPALDO.read_text(encoding="utf-8"))
        return float(d["valor"]), f"respaldo del {d.get('fecha', '?')}"
    except (OSError, ValueError, KeyError):
        return None, "sin valor"


def uf_actual(*, forzar: bool = False) -> tuple[float | None, str]:
    """(valor de la UF en pesos, de donde salio).

    Solo se cachea el exito, y por una hora. Un fallo de red nunca queda pegado
    para el resto del proceso, que es exactamente lo que arruino la corrida del
    2026-07-27.
    """
    global _cache_uf
    if _cache_uf and not forzar and (time.time() - _cache_uf[2]) < 3600:
        return _cache_uf[0], _cache_uf[1]
    try:
        r = httpx.get("https://mindicador.cl/api/uf", timeout=15)
        r.raise_for_status()
        serie = r.json().get("serie", [])
        if serie:
            valor = float(serie[0]["valor"])
            _cache_uf = (valor, "mindicador.cl", time.time())
            _guardar_uf(valor)
            return valor, "mindicador.cl"
    except Exception:
        pass
    return _uf_de_respaldo()


def precios(valor: float | None, moneda: str | None,
            uf: float | None) -> tuple[float | None, float | None]:
    """(precio_clp, precio_uf) desde lo publicado. Bidireccional, como debio ser
    siempre: el scraper anterior solo convertia en un sentido y perdio filas por
    los dos lados."""
    if valor is None or moneda is None:
        return None, None
    if moneda == "UF":
        return (round(valor * uf) if uf else None), round(valor, 2)
    return round(valor), (round(valor / uf, 2) if uf else None)
