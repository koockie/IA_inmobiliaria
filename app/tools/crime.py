"""Contexto delictual por comuna desde un dataset CEAD (semilla CSV).

NOTA DE SESGO: se usa estadística OFICIAL a nivel comunal (no alertas comunitarias) y se
entrega siempre con contexto (comparación vs promedio del dataset) y disclaimers. El CSV
incluido es PLACEHOLDER: debe reemplazarse por la descarga real de CEAD.
"""
from __future__ import annotations

import csv
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "crime_by_comuna.csv"

DISCLAIMER = (
    "Cifra referencial a nivel comunal (no del punto exacto). No debe ser el único "
    "factor de decisión y puede inducir sesgo. Dataset de ejemplo: reemplazar por datos "
    "oficiales de CEAD."
)


def _normalize(name: str) -> str:
    """minúsculas + sin acentos, para hacer match robusto de comunas."""
    nfkd = unicodedata.normalize("NFKD", name.strip().lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    rows: list[dict] = []
    if not DATA_FILE.exists():
        return rows
    with DATA_FILE.open(encoding="utf-8") as fh:
        # saltar líneas de comentario que empiezan con '#'
        lines = [ln for ln in fh if not ln.lstrip().startswith("#")]
    for row in csv.DictReader(lines):
        try:
            row["tasa_delitos_100k_hab"] = float(row["tasa_delitos_100k_hab"])
        except (KeyError, ValueError):
            continue
        rows.append(row)
    return rows


def crime_context(comuna: Optional[str]) -> dict:
    """Devuelve la tasa de la comuna con contexto vs el promedio del dataset."""
    rows = _load()
    if not comuna or not rows:
        return {
            "disponible": False,
            "motivo": "Sin comuna identificada o dataset vacío.",
            "disclaimer": DISCLAIMER,
        }

    target = _normalize(comuna)
    match = next((r for r in rows if _normalize(r["comuna"]) == target), None)

    promedio = sum(r["tasa_delitos_100k_hab"] for r in rows) / len(rows)
    if match is None:
        return {
            "disponible": False,
            "motivo": f"Comuna '{comuna}' no está en el dataset.",
            "promedio_dataset_100k": round(promedio),
            "disclaimer": DISCLAIMER,
        }

    tasa = match["tasa_delitos_100k_hab"]
    if tasa > promedio * 1.1:
        relativo = "sobre el promedio del dataset"
    elif tasa < promedio * 0.9:
        relativo = "bajo el promedio del dataset"
    else:
        relativo = "en torno al promedio del dataset"

    return {
        "disponible": True,
        "comuna": match["comuna"],
        "tasa_100k_hab": tasa,
        "anio": match.get("anio"),
        "promedio_dataset_100k": round(promedio),
        "comparacion": relativo,
        "disclaimer": DISCLAIMER,
    }
