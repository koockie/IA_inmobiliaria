"""Verificacion de la aritmetica financiera de `api/inversion.py`.

Es matematica de dinero: un signo cambiado no lanza ninguna excepcion, solo
produce un consejo de inversion equivocado. Cada comprobacion contrasta el
resultado contra un valor conocido o contra un calculo independiente hecho de
otra forma, nunca contra el mismo codigo que se esta probando.

    ./.venv/Scripts/python.exe qa/qa_inversion.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from api.inversion import (Supuestos, _flujos, dividendo, flujo_operacional,   # noqa: E402
                           metricas_estaticas, plusvalia_requerida,
                           saldo_insoluto, simular, tasa_mensual, tir_anual, van)

FALLOS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    print(f"  [{'OK ' if ok else 'FALLA'}] {nombre}{('  ->  ' + detalle) if detalle else ''}")
    if not ok:
        FALLOS.append(nombre)


def titulo(t: str) -> None:
    print(f"\n{'='*74}\n{t}\n{'='*74}")


# ---------------------------------------------------------------------------
def probar_credito() -> None:
    titulo("1. CREDITO HIPOTECARIO")
    monto, tasa, plazo = 1000.0, 4.01, 25
    cuota = dividendo(monto, tasa, plazo)
    i, n = tasa_mensual(tasa), plazo * 12
    print(f"  1.000 UF al {tasa}% a {plazo} anos -> cuota {cuota:.4f} UF/mes")

    # Verificacion independiente: el valor presente de las 300 cuotas,
    # descontado a la misma tasa, tiene que devolver el monto prestado.
    vp = sum(cuota / (1 + i) ** k for k in range(1, n + 1))
    check("el valor presente de las cuotas reconstruye el monto prestado",
          abs(vp - monto) < 1e-6, f"{vp:.6f} vs {monto}")

    # Verificacion independiente del saldo: se amortiza mes a mes a mano.
    saldo = monto
    saldos = []
    for _ in range(n):
        saldo = saldo * (1 + i) - cuota
        saldos.append(saldo)
    for k in (12, 96, 180, 300):
        formula = saldo_insoluto(monto, tasa, plazo, k)
        check(f"el saldo insoluto al mes {k} coincide con la amortizacion mes a mes",
              abs(formula - saldos[k - 1]) < 1e-6,
              f"formula {formula:.4f} vs simulado {saldos[k-1]:.4f}")
    check("el credito queda pagado al final del plazo", abs(saldos[-1]) < 1e-6,
          f"saldo final {saldos[-1]:.8f}")
    check("sin deuda no hay dividendo", dividendo(0, tasa, plazo) == 0.0)

    # Una tasa mas alta tiene que dar una cuota mas alta, y un plazo mas largo
    # una cuota mas baja: dos monotonias que un signo cambiado rompe.
    check("mas tasa, mas cuota", dividendo(monto, 6.0, plazo) > cuota)
    check("mas plazo, menos cuota", dividendo(monto, tasa, 30) < cuota)


def probar_van_tir() -> None:
    titulo("2. VAN Y TIR")
    # Caso de valor conocido: 100 hoy que devuelven 100*(1+r)^12 en 12 meses
    # tiene TIR anual exactamente r.
    for r in (0.05, 0.12, -0.03):
        f = np.zeros(13)
        f[0], f[12] = -100.0, 100.0 * (1 + r)
        t = tir_anual(f)
        check(f"TIR de un flujo con retorno conocido de {100*r:+.0f}%",
              t is not None and abs(t - r) < 1e-6,
              f"{100*t:.6f}%" if t is not None else "None")

    # El VAN descontado a la propia TIR tiene que ser cero: es la definicion.
    f = np.array([-1000.0] + [20.0] * 59 + [1500.0])
    t = tir_anual(f)
    check("el VAN descontado a la TIR es cero",
          abs(van(f, 100 * t)) < 1e-6, f"VAN {van(f, 100*t):.8f}")
    check("el VAN cae al subir la tasa de descuento", van(f, 2) > van(f, 8))
    check("sin flujos positivos no existe TIR",
          tir_anual(np.array([-100.0, -10.0, -10.0])) is None)


def probar_operacion() -> None:
    titulo("3. FLUJO OPERACIONAL")
    s = Supuestos()
    op = flujo_operacional(arriendo_uf_mes=20.0, precio_uf=5000.0, s=s)
    check("el bruto anual son 12 arriendos", abs(op["bruto_anual_uf"] - 240) < 1e-9)
    check("la vacancia descuenta los meses declarados",
          abs(op["vacancia_uf"] - 20 * s.vacancia_meses_ano) < 1e-9)
    suma = (op["administracion_uf"] + op["mantencion_uf"] + op["contribuciones_uf"]
            + op["seguros_uf"] + op["impuesto_arriendo_uf"])
    check("los gastos suman sus componentes", abs(suma - op["gastos_anuales_uf"]) < 1e-9)
    check("el NOI es lo cobrado menos los gastos",
          abs(op["noi_anual_uf"] - (op["cobrado_anual_uf"] - op["gastos_anuales_uf"])) < 1e-9)
    check("el NOI es menor que el bruto", op["noi_anual_uf"] < op["bruto_anual_uf"])
    print(f"  yield bruto 4,80% -> cap rate neto "
          f"{100*op['noi_anual_uf']/5000:.2f}% (gastos "
          f"{100*op['gastos_anuales_uf']/op['bruto_anual_uf']:.0f}% del bruto)")

    # El precio maximo autofinanciable tiene que autofinanciarse, por definicion.
    m = metricas_estaticas(5000.0, 20.0, s)
    p_max = m["precio_maximo_autofinanciable_uf"]
    m2 = metricas_estaticas(p_max, 20.0, s)
    check("al precio maximo autofinanciable el flujo mensual es ~0",
          abs(m2["flujo_mensual_uf"]) < 0.05,
          f"{m2['flujo_mensual_uf']:+.4f} UF/mes a {p_max:,.0f} UF")
    check("por encima de ese precio ya no se autofinancia",
          not metricas_estaticas(p_max * 1.1, 20.0, s)["se_autofinancia"])


def probar_horizonte() -> None:
    titulo("4. HORIZONTE Y PLUSVALIA REQUERIDA")
    s = Supuestos()
    precio, valor, arr = 5000.0, 5000.0, 20.0

    g = plusvalia_requerida(precio, valor, arr, s)
    check("la plusvalia requerida existe", g is not None, f"{g:.3f}%" if g else "None")
    if g is not None:
        v = van(_flujos(precio, valor, arr, s, g), s.retorno_alternativo_real_pct)
        check("al aplicar la plusvalia requerida el VAN es ~0", abs(v) < 0.5,
              f"VAN {v:+.4f} UF")
        # Con mas apreciacion el VAN tiene que ser positivo, y al reves.
        v_mas = van(_flujos(precio, valor, arr, s, g + 2), s.retorno_alternativo_real_pct)
        v_menos = van(_flujos(precio, valor, arr, s, g - 2), s.retorno_alternativo_real_pct)
        check("el VAN crece con la plusvalia", v_menos < 0 < v_mas,
              f"{v_menos:+.0f} / {v_mas:+.0f} UF")

    # Sobrepagar tiene que empeorar el resultado: el mismo inmueble, mismo
    # arriendo, pero pagando un 20% mas exige mas plusvalia para funcionar.
    g_caro = plusvalia_requerida(precio * 1.2, valor, arr, s)
    check("pagar un 20% mas exige mas plusvalia", g_caro is not None and g_caro > g,
          f"{g:.2f}% comprando a valor vs {g_caro:.2f}% sobrepagando")

    # Un arriendo mayor tiene que reducir la plusvalia requerida.
    g_renta = plusvalia_requerida(precio, valor, arr * 1.3, s)
    check("mas arriendo exige menos plusvalia", g_renta is not None and g_renta < g,
          f"{g_renta:.2f}% vs {g:.2f}%")

    # Sin deuda el flujo mensual no puede ser peor que con deuda.
    sin_deuda = Supuestos(**{**s.a_dict(), "pie_pct": 100.0})
    check("sin credito el flujo mensual mejora",
          metricas_estaticas(precio, arr, sin_deuda)["flujo_mensual_uf"]
          > metricas_estaticas(precio, arr, s)["flujo_mensual_uf"])
    check("sin credito el dividendo es cero",
          metricas_estaticas(precio, arr, sin_deuda)["dividendo_mensual_uf"] == 0.0)


def probar_simulacion() -> None:
    titulo("5. SIMULACION")
    s = Supuestos()
    a = simular(5000.0, 5000.0, 20.0, s, 0.13, 0.115, n=1200, semilla=1)
    b = simular(5000.0, 5000.0, 20.0, s, 0.13, 0.115, n=1200, semilla=1)
    check("la simulacion es reproducible con la misma semilla",
          a["van_mediano_uf"] == b["van_mediano_uf"])
    check("los percentiles del VAN estan ordenados",
          a["van_p10_uf"] <= a["van_mediano_uf"] <= a["van_p90_uf"])
    check("la probabilidad esta en [0, 100]",
          0 <= a["prob_batir_alternativa_pct"] <= 100,
          f"{a['prob_batir_alternativa_pct']:.1f}%")

    # Mas error del modelo tiene que ensanchar el resultado. Se aisla apagando el
    # escenario de plusvalia: con el encendido, su dispersion tapa el efecto, que
    # es en si mismo el hallazgo -- el rango del VAN lo domina el supuesto de
    # apreciacion, no la precision de la tasacion.
    quieto = Supuestos(**{**s.a_dict(), "sd_plusvalia_pct": 0.0})
    a0 = simular(5000.0, 5000.0, 20.0, quieto, 0.13, 0.115, n=1200, semilla=1)
    c0 = simular(5000.0, 5000.0, 20.0, quieto, 0.26, 0.23, n=1200, semilla=1)
    an, cn = (a0["van_p90_uf"] - a0["van_p10_uf"]), (c0["van_p90_uf"] - c0["van_p10_uf"])
    check("doblar el error de los modelos ensancha la distribucion del VAN",
          cn > 1.5 * an, f"{an:,.0f} -> {cn:,.0f} UF (sin ruido de plusvalia)")

    d = simular(5000.0, 5000.0, 20.0, s, 0.13, 0.115, n=1200, semilla=1,
                descomponer=True)
    check("la descomposicion atribuye la dispersion a sus dos fuentes",
          d["peso_error_modelos_pct"] is not None
          and 0 <= d["peso_error_modelos_pct"] <= 100,
          f"error de modelos {d['peso_error_modelos_pct']:.0f}% del total, "
          f"plusvalia el resto")

    # Comprar mas barato el mismo inmueble no puede empeorar la probabilidad.
    barato = simular(4000.0, 5000.0, 20.0, s, 0.13, 0.115, n=1200, semilla=1)
    check("comprar por debajo del valor sube la probabilidad de exito",
          barato["prob_batir_alternativa_pct"] >= a["prob_batir_alternativa_pct"],
          f"{a['prob_batir_alternativa_pct']:.0f}% -> "
          f"{barato['prob_batir_alternativa_pct']:.0f}%")
    print(f"  a valor de mercado: VAN mediano {a['van_mediano_uf']:+,.0f} UF, "
          f"prob de exito {a['prob_batir_alternativa_pct']:.0f}%")


def main() -> int:
    probar_credito()
    probar_van_tir()
    probar_operacion()
    probar_horizonte()
    probar_simulacion()
    titulo("RESUMEN")
    print(f"  fallos: {len(FALLOS)}")
    for f in FALLOS:
        print(f"     - {f}")
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
