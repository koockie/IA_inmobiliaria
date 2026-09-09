"""Prueba manual del extractor.

    ./.venv/Scripts/python.exe -m extractor.cli <url> [--json] [--sin-cache]
"""
from __future__ import annotations

import argparse
import json
import sys

from .servicio import obtener

_ORDEN = ["sitio", "id_aviso", "operacion", "tipo", "comuna", "barrio", "direccion",
          "precio_valor", "precio_moneda", "precio_uf", "precio_clp", "uf_usada",
          "m2_util", "m2_total", "dormitorios", "banos", "estacionamientos",
          "bodegas", "antiguedad_anos", "ano_construccion", "gastos_comunes_clp",
          "lat", "lon", "es_proyecto"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Extrae los datos de un aviso desde su URL.")
    p.add_argument("url")
    p.add_argument("--json", action="store_true", help="salida cruda en JSON")
    p.add_argument("--sin-cache", action="store_true", help="ignora la copia local")
    p.add_argument("--no-guardar", action="store_true", help="no escribe en la base")
    a = p.parse_args(argv)

    r = obtener(a.url, guardar=not a.no_guardar, usar_cache=not a.sin_cache)

    if a.json:
        print(json.dumps(r.a_dict(), ensure_ascii=False, indent=2, default=str))
        return 0 if r.ok else 1

    if not r.ok:
        print(f"  FALLO [{r.estado}]  {r.error}")
        return 1

    reg = r.registro or {}
    print(f"  {reg.get('titulo') or '(sin titulo)'}")
    print(f"  {reg.get('url')}")
    print("  " + "-" * 66)
    for c in _ORDEN:
        v = reg.get(c)
        print(f"  {c:22} {'-' if v is None else v}")
    print(f"  {'descripcion':22} {len(reg.get('descripcion') or '')} caracteres")
    if r.desde_cache:
        print("\n  (servido desde la copia local, sin pedirle la pagina al portal)")
    if r.advertencias:
        print("\n  Advertencias:")
        for adv in r.advertencias:
            print(f"    - {adv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
