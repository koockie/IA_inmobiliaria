r"""CLI del scraper v1 — extracción SIN proyectos.

USO
---
  # prueba corta
  python -m scraper_v1.run --comuna nunoa --operacion venta --tipo casa --max-paginas 1

  # extracción completa (4 comunas x venta/arriendo x casa/departamento)
  python -m scraper_v1.run

  # por partes
  python -m scraper_v1.run --solo-listado
  python -m scraper_v1.run --solo-detalle
  python -m scraper_v1.run --export

SALIDAS
-------
  data/ofertas_v1.sqlite           base del v1 (incluye los proyectos, marcados)
  data/dataset_ofertas_v1.csv      SOLO viviendas individuales (es_proyecto = 0)
  data/proyectos_excluidos_v1.csv  qué proyectos se excluyeron y por qué señal

Si el portal empieza a bloquear, la corrida se detiene con un mensaje claro en vez de
guardar datos inválidos. Comprueba antes con:  python comprobar_acceso.py
"""
from __future__ import annotations

import argparse

import httpx

from scraper_v1 import portalinmobiliario as pi
from scraper_v1 import storage
from scraper_v1.config import COMUNAS_PI, OPERACIONES, TIPOS
from scraper_v1.portalinmobiliario import PortalBloqueado


def _combos(args):
    comunas = list(COMUNAS_PI) if args.comuna == "all" else [args.comuna]
    operaciones = OPERACIONES if args.operacion == "all" else [args.operacion]
    tipos = TIPOS if args.tipo == "all" else [args.tipo]
    for c in comunas:
        for o in operaciones:
            for t in tipos:
                yield c, o, t


def main() -> None:
    ap = argparse.ArgumentParser(description="Scraper v1 (excluye proyectos)")
    ap.add_argument("--comuna", choices=[*COMUNAS_PI, "all"], default="all")
    ap.add_argument("--operacion", choices=[*OPERACIONES, "all"], default="all")
    ap.add_argument("--tipo", choices=[*TIPOS, "all"], default="all")
    ap.add_argument("--max-paginas", type=int, default=None)
    ap.add_argument("--max-detalles", type=int, default=None)
    ap.add_argument("--solo-listado", action="store_true")
    ap.add_argument("--solo-detalle", action="store_true")
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args()

    conn = storage.connect()

    if args.export:
        _export(conn)
        return

    try:
        with httpx.Client() as client:
            # ── Pasada A: listados ──
            if not args.solo_detalle:
                for comuna, operacion, tipo in _combos(args):
                    print(f"[listado] {comuna} / {operacion} / {tipo}")
                    n = proy = 0
                    for rec in pi.scrape_listado(client, operacion, tipo, comuna,
                                                 args.max_paginas):
                        storage.upsert_listado(conn, rec)
                        proy += rec["es_proyecto"]
                        n += 1
                    conn.commit()
                    print(f"  -> {n} avisos ({proy} proyectos marcados para excluir)")

            # ── Pasada B: fichas (los proyectos ya no se visitan) ──
            if not args.solo_listado:
                pendientes = storage.pendientes_detalle(conn, "pi", args.max_detalles)
                print(f"[detalle] {len(pendientes)} fichas pendientes")
                for i, (id_aviso, url) in enumerate(pendientes, 1):
                    campos = pi.scrape_detalle(client, url)
                    if campos is None:
                        continue
                    if campos.get("es_proyecto"):
                        storage.marcar_proyecto(
                            conn, "pi", id_aviso,
                            campos["senales_proyecto"].split(" | "))
                    else:
                        storage.update_detalle(conn, "pi", id_aviso, campos)
                    if i % 25 == 0:
                        conn.commit()
                        print(f"  ... {i}/{len(pendientes)}")
                conn.commit()

    except PortalBloqueado as e:
        conn.commit()
        print(f"\n  !! CORRIDA DETENIDA: {e}")
        print("     El portal está bloqueando el scraping. Lo avanzado quedó guardado.")
        print("     Verifica con:  python comprobar_acceso.py")
        print("     Reanuda el mismo comando cuando el acceso se restablezca.\n")
        _export(conn)
        return

    _export(conn)


def _export(conn) -> None:
    viviendas = storage.export_csv(conn)
    excluidos = storage.export_excluidos(conn)
    print(f"\nCSV de viviendas   : data/dataset_ofertas_v1.csv ({viviendas} filas)")
    print(f"Proyectos excluidos: data/proyectos_excluidos_v1.csv ({excluidos} filas)")
    print(f"\n{'comuna':<12}{'operacion':<10}{'tipo':<14}{'total':>7}{'detalle':>9}{'proyectos':>11}")
    for _sitio, comuna, operacion, tipo, n, det, proy in storage.resumen(conn):
        print(f"{comuna:<12}{operacion:<10}{tipo:<14}{n:>7}{det or 0:>9}{proy or 0:>11}")


if __name__ == "__main__":
    main()
