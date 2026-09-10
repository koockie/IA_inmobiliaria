"""CLI del scraper.

Ejemplos:
  python -m scraper.run --sitio pi --comuna nunoa --operacion venta --tipo casa --max-paginas 1
  python -m scraper.run --sitio pi                      # todo PortalInmobiliario (4 comunas)
  python -m scraper.run --sitio pi --solo-detalle --max-detalles 50
  python -m scraper.run --export                        # solo exportar CSV + resumen
"""
from __future__ import annotations

import argparse

import httpx

from scraper import portalinmobiliario as pi
from scraper import storage
from scraper.config import COMUNAS_PI, OPERACIONES, TIPOS


def _combos(args):
    comunas = list(COMUNAS_PI) if args.comuna == "all" else [args.comuna]
    operaciones = OPERACIONES if args.operacion == "all" else [args.operacion]
    tipos = TIPOS if args.tipo == "all" else [args.tipo]
    for c in comunas:
        for o in operaciones:
            for t in tipos:
                yield c, o, t


def main() -> None:
    ap = argparse.ArgumentParser(description="Scraper de ofertas inmobiliarias (dataset ML)")
    ap.add_argument("--sitio", choices=["pi", "toctoc"], default="pi")
    ap.add_argument("--comuna", choices=[*COMUNAS_PI, "all"], default="all")
    ap.add_argument("--operacion", choices=[*OPERACIONES, "all"], default="all")
    ap.add_argument("--tipo", choices=[*TIPOS, "all"], default="all")
    ap.add_argument("--max-paginas", type=int, default=None, help="tope de páginas por combo")
    ap.add_argument("--solo-listado", action="store_true")
    ap.add_argument("--solo-detalle", action="store_true")
    ap.add_argument("--max-detalles", type=int, default=None, help="tope de fichas a visitar")
    ap.add_argument("--export", action="store_true", help="solo exportar CSV y resumen")
    args = ap.parse_args()

    conn = storage.connect()

    if args.export:
        _export(conn)
        return

    if args.sitio == "toctoc":
        print("TocToc: pendiente de capturar su endpoint de búsqueda (ver plan). Usa --sitio pi.")
        return

    with httpx.Client() as client:
        # Pasada A: listados
        if not args.solo_detalle:
            for comuna, operacion, tipo in _combos(args):
                print(f"[listado] {comuna} / {operacion} / {tipo}")
                n = 0
                for rec in pi.scrape_listado(client, operacion, tipo, comuna, args.max_paginas):
                    storage.upsert_listado(conn, rec)
                    n += 1
                conn.commit()
                print(f"  -> {n} avisos guardados/actualizados")

        # Pasada B: fichas de detalle pendientes
        if not args.solo_listado:
            pendientes = storage.pendientes_detalle(conn, "pi", args.max_detalles)
            print(f"[detalle] {len(pendientes)} fichas pendientes")
            for i, (id_aviso, url) in enumerate(pendientes, 1):
                campos = pi.scrape_detalle(client, url)
                if campos:
                    storage.update_detalle(conn, "pi", id_aviso, campos)
                if i % 25 == 0:
                    conn.commit()
                    print(f"  ... {i}/{len(pendientes)}")
            conn.commit()

    _export(conn)


def _export(conn) -> None:
    total = storage.export_csv(conn)
    print(f"\nCSV exportado: data/dataset_ofertas.csv ({total} filas)")
    print(f"{'sitio':<8}{'comuna':<12}{'operacion':<10}{'tipo':<14}{'avisos':>7}{'c/detalle':>10}")
    for sitio, comuna, operacion, tipo, n, det in storage.resumen(conn):
        print(f"{sitio:<8}{comuna:<12}{operacion:<10}{tipo:<14}{n:>7}{det or 0:>10}")


if __name__ == "__main__":
    main()
