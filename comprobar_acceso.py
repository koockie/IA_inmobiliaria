r"""COMPROBAR ACCESO a PortalInmobiliario — ¿nos está bloqueando el portal?

Hace UNA sola petición a una ficha conocida y dice si el portal responde normal o si
está pidiendo verificación anti-bot. Útil para saber cuándo se puede lanzar una
extracción, sin gastar miles de requests probando.

USO
---
    .\.venv\Scripts\python.exe comprobar_acceso.py
    .\.venv\Scripts\python.exe comprobar_acceso.py --esperar     (reintenta cada 10 min)

CONTEXTO
--------
Tras un volumen alto de peticiones, el portal redirige a /gz/account-verification y
devuelve ~22 KB en vez de los ~470 KB de una ficha real. El bloqueo es por IP y volumen
(el scraper nunca usa credenciales) y suele ceder solo con el tiempo.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime

import httpx

# Ficha de referencia (proyecto conocido, estable)
URL = "https://portalinmobiliario.com/MLC-3585368896-castillo-velasco-_JM"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9",
}
TAM_MINIMO_FICHA = 100_000    # una ficha real pesa ~470 KB; el bloqueo devuelve ~22 KB


def comprobar() -> bool:
    """True si el portal responde con una ficha real."""
    try:
        r = httpx.get(URL, headers=HEADERS, timeout=30, follow_redirects=True)
    except httpx.HTTPError as e:
        print(f"  ERROR de red: {e}")
        return False

    url_final = str(r.url)
    tam = len(r.text)
    bloqueado = ("account-verification" in url_final
                 or "gz/" in url_final
                 or tam < TAM_MINIMO_FICHA)

    print(f"  status HTTP : {r.status_code}")
    print(f"  tamaño      : {tam:,} caracteres".replace(",", "."))
    print(f"  URL final   : {url_final[:88]}")

    if bloqueado:
        print("\n  >>> BLOQUEADO: el portal está pidiendo verificación anti-bot.")
        print("      No lances la extracción todavía: guardaría datos inválidos.")
        print("      Suele ceder tras unas horas. También ayuda espaciar más los requests.")
        return False

    print("\n  >>> ACCESO OK: el portal responde con la ficha completa.")
    print("      Se puede lanzar la extracción.")
    return True


def main() -> None:
    print(f"\nComprobando acceso a PortalInmobiliario  ({datetime.now():%H:%M:%S})")
    print("-" * 66)
    ok = comprobar()

    if not ok and "--esperar" in sys.argv:
        print("\n  Modo --esperar: reintentando cada 10 minutos (Ctrl+C para salir)\n")
        intento = 1
        while not ok:
            time.sleep(600)
            intento += 1
            print(f"\nIntento {intento}  ({datetime.now():%H:%M:%S})")
            print("-" * 66)
            ok = comprobar()

    print()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
