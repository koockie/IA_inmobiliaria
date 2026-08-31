"""Capa de decision de inversion: de dos estimaciones a un veredicto.

Los dos modelos responden "cuanto vale" y "cuanto renta". Este modulo responde
la tercera pregunta -- **conviene comprarla y tenerla N anos** -- y esta
construido alrededor de tres decisiones metodologicas que conviene leer antes
de usar los numeros.

**1. No se predice la plusvalia; se calcula cuanta hace falta.**
El dataset es una foto de 15 dias: no permite estimar apreciacion futura y
prometerlo seria inventar. La pregunta se invierte: dado el precio, el arriendo
y el costo del credito, *cuanta apreciacion real anual necesita esta propiedad
para batir la alternativa financiera*. Eso si se deduce de los datos, y ademas
es mas util: el usuario puede contrastar ese umbral contra la apreciacion
historica de su comuna (IPV del Banco Central) y decidir si es realista.

**2. El error de los modelos se propaga hasta la decision.**
Un cap rate calculado con dos estimaciones que fallan ~8 % cada una no se puede
reportar con dos decimales. La simulacion convierte los MdAPE medidos en las
fichas en la dispersion del resultado, y el veredicto sale como probabilidad,
no como numero unico.

**3. El yield es la senal de retorno esperado, no un adorno.**
En el marco de Campbell y Shiller (1988) aplicado a vivienda, el log del ratio
arriendo/precio equivale al valor presente de los retornos futuros esperados
mas el crecimiento futuro de los arriendos. Comparar el yield de una propiedad
contra la distribucion de yields de su propia comuna es, por tanto, una medida
de valor relativo con fundamento, no una regla de dedo.

Todo el modulo trabaja en **UF**, es decir, en terminos reales: los
crecimientos son sobre inflacion y el dividendo de un credito en UF es constante
en terminos reales, que es justamente lo que hace comparables los flujos.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
MESES = 12


# ---------------------------------------------------------------------------
# Supuestos
# ---------------------------------------------------------------------------
@dataclass
class Supuestos:
    """Parametros del analisis. Todos los defaults son declarados y editables.

    Las tasas de referencia son de agosto de 2026: la tasa hipotecaria promedio
    oficial estaba en 4,01 % anual en UF y la UF en $40.844,79 (el mismo valor
    que la mediana empirica del dataset, lo que confirma la coherencia temporal).
    """
    # --- financiamiento ---
    pie_pct: float = 20.0
    tasa_anual_pct: float = 4.01
    plazo_anos: int = 25
    costos_compra_pct: float = 1.5      # notaria, conservador, estudio de titulos

    # --- operacion (todo anual salvo lo indicado) ---
    vacancia_meses_ano: float = 1.0     # supuesto estandar del mercado chileno
    administracion_pct_arriendo: float = 8.0
    mantencion_pct_arriendo: float = 5.0
    contribuciones_pct_precio: float = 0.35
    seguros_pct_precio: float = 0.05
    impuesto_arriendo_pct: float = 0.0  # 0 si es DFL2 o si el dueno esta exento

    # --- salida ---
    horizonte_anos: int = 8
    costos_venta_pct: float = 2.4       # corretaje 2 % + IVA
    exencion_ganancia_uf: float = 8000.0
    impuesto_ganancia_pct: float = 10.0

    # --- escenario real (sobre inflacion) ---
    plusvalia_real_anual_pct: float = 2.0
    crecimiento_arriendo_real_pct: float = 1.0
    sd_plusvalia_pct: float = 4.0       # incertidumbre anual de la apreciacion

    # --- costo de oportunidad ---
    retorno_alternativo_real_pct: float = 3.0   # UF + 3 %, deposito o renta fija

    def a_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Aritmetica del credito
# ---------------------------------------------------------------------------
def tasa_mensual(tasa_anual_pct: float) -> float:
    """Anual efectiva -> mensual equivalente, por composicion."""
    return (1 + tasa_anual_pct / 100) ** (1 / MESES) - 1


def dividendo(monto_uf: float, tasa_anual_pct: float, plazo_anos: int) -> float:
    """Cuota mensual de un credito de amortizacion francesa, en UF."""
    if monto_uf <= 0:
        return 0.0
    i, n = tasa_mensual(tasa_anual_pct), plazo_anos * MESES
    if i == 0:
        return monto_uf / n
    return monto_uf * i / (1 - (1 + i) ** -n)


def saldo_insoluto(monto_uf: float, tasa_anual_pct: float, plazo_anos: int,
                   meses_pagados: int) -> float:
    """Capital que queda por pagar tras `meses_pagados` cuotas."""
    if monto_uf <= 0:
        return 0.0
    i, n = tasa_mensual(tasa_anual_pct), plazo_anos * MESES
    k = min(meses_pagados, n)
    if i == 0:
        return monto_uf * (1 - k / n)
    return monto_uf * ((1 + i) ** n - (1 + i) ** k) / ((1 + i) ** n - 1)


# ---------------------------------------------------------------------------
# Flujo operacional
# ---------------------------------------------------------------------------
def flujo_operacional(arriendo_uf_mes: float, precio_uf: float,
                      s: Supuestos) -> dict:
    """Del arriendo pedido al ingreso operativo neto (NOI), anual y en UF.

    El NOI es el arriendo efectivamente cobrado menos lo que cuesta mantener la
    propiedad arrendada. No incluye el dividendo: eso es financiamiento, no
    operacion, y mezclarlos es el error mas comun al comparar propiedades.
    """
    bruto = arriendo_uf_mes * MESES
    vacancia = arriendo_uf_mes * s.vacancia_meses_ano
    cobrado = bruto - vacancia
    administracion = cobrado * s.administracion_pct_arriendo / 100
    mantencion = cobrado * s.mantencion_pct_arriendo / 100
    contribuciones = precio_uf * s.contribuciones_pct_precio / 100
    seguros = precio_uf * s.seguros_pct_precio / 100
    impuesto = cobrado * s.impuesto_arriendo_pct / 100
    gastos = administracion + mantencion + contribuciones + seguros + impuesto
    return {"bruto_anual_uf": bruto, "vacancia_uf": vacancia,
            "cobrado_anual_uf": cobrado, "administracion_uf": administracion,
            "mantencion_uf": mantencion, "contribuciones_uf": contribuciones,
            "seguros_uf": seguros, "impuesto_arriendo_uf": impuesto,
            "gastos_anuales_uf": gastos, "noi_anual_uf": cobrado - gastos,
            "noi_mensual_uf": (cobrado - gastos) / MESES}


def metricas_estaticas(precio_uf: float, arriendo_uf_mes: float,
                       s: Supuestos) -> dict:
    """Las razones que se leen de un vistazo, todas sobre el mismo flujo."""
    op = flujo_operacional(arriendo_uf_mes, precio_uf, s)
    deuda = precio_uf * (1 - s.pie_pct / 100)
    cuota = dividendo(deuda, s.tasa_anual_pct, s.plazo_anos)
    capital_inicial = precio_uf * (s.pie_pct / 100 + s.costos_compra_pct / 100)
    flujo_mes = op["noi_mensual_uf"] - cuota

    # Precio maximo al que la propiedad todavia se autofinancia. Dos partidas
    # crecen con el precio -- el dividendo, y tambien contribuciones y seguros --
    # mientras que el resto del NOI depende solo del arriendo. Separando ambas:
    #     (A - k*P)/12 = P * c1     =>     P = (A/12) / (c1 + k/12)
    # donde A es el NOI anual antes de las partidas proporcionales al precio,
    # k su tasa conjunta y c1 el dividendo mensual por cada UF de precio.
    A = (op["noi_anual_uf"] + op["contribuciones_uf"] + op["seguros_uf"])
    k = (s.contribuciones_pct_precio + s.seguros_pct_precio) / 100
    c1 = dividendo(1 - s.pie_pct / 100, s.tasa_anual_pct, s.plazo_anos)
    precio_autofinanciable = ((A / MESES) / (c1 + k / MESES)
                              if (c1 + k / MESES) > 0 else float("inf"))

    return {
        "yield_bruto_pct": 100 * op["bruto_anual_uf"] / precio_uf,
        "cap_rate_neto_pct": 100 * op["noi_anual_uf"] / precio_uf,
        "gastos_sobre_bruto_pct": 100 * op["gastos_anuales_uf"] / op["bruto_anual_uf"],
        "dividendo_mensual_uf": cuota,
        "capital_inicial_uf": capital_inicial,
        "flujo_mensual_uf": flujo_mes,
        "cobertura_dividendo": (op["noi_mensual_uf"] / cuota) if cuota > 0 else None,
        "se_autofinancia": bool(flujo_mes >= 0),
        "cash_on_cash_pct": (100 * flujo_mes * MESES / capital_inicial
                             if capital_inicial > 0 else None),
        "precio_maximo_autofinanciable_uf": precio_autofinanciable,
        "operacion": op,
    }


# ---------------------------------------------------------------------------
# Horizonte de tenencia
# ---------------------------------------------------------------------------
def _flujos(precio_compra_uf: float, valor_mercado_uf: float,
            arriendo_uf_mes: float, s: Supuestos, plusvalia_pct: float,
            crecimiento_arriendo_pct: float | None = None) -> np.ndarray:
    """Serie mensual de flujos del capital propio, en UF reales.

    `precio_compra_uf` es lo que se paga; `valor_mercado_uf` es lo que la
    propiedad realmente vale. Separarlos es lo que permite que sobrepagar se
    refleje en el resultado: la venta futura parte del valor, no del precio.
    """
    g_arr = (s.crecimiento_arriendo_real_pct if crecimiento_arriendo_pct is None
             else crecimiento_arriendo_pct)
    n = s.horizonte_anos * MESES
    deuda = precio_compra_uf * (1 - s.pie_pct / 100)
    cuota = dividendo(deuda, s.tasa_anual_pct, s.plazo_anos)

    f = np.zeros(n + 1)
    f[0] = -precio_compra_uf * (s.pie_pct / 100 + s.costos_compra_pct / 100)
    for anio in range(s.horizonte_anos):
        arr = arriendo_uf_mes * (1 + g_arr / 100) ** anio
        noi_mes = flujo_operacional(arr, precio_compra_uf, s)["noi_mensual_uf"]
        f[anio * MESES + 1: (anio + 1) * MESES + 1] = noi_mes - cuota

    valor_final = valor_mercado_uf * (1 + plusvalia_pct / 100) ** s.horizonte_anos
    ganancia = max(0.0, valor_final - precio_compra_uf)
    gravable = max(0.0, ganancia - s.exencion_ganancia_uf)
    impuesto = gravable * s.impuesto_ganancia_pct / 100
    f[n] += (valor_final
             - valor_final * s.costos_venta_pct / 100
             - impuesto
             - saldo_insoluto(deuda, s.tasa_anual_pct, s.plazo_anos, n))
    return f


def van(flujos: np.ndarray, tasa_anual_pct: float) -> float:
    """Valor presente neto de la serie mensual, descontada al costo de oportunidad.

    El VAN es la vara limpia: positivo significa que la propiedad rinde mas que
    poner el mismo dinero, en los mismos momentos, en la alternativa. La TIR
    tambien se reporta, pero como referencia: con flujos mensuales negativos
    -- lo normal en una compra apalancada -- la TIR supone que esos aportes
    rinden a la propia TIR, que es justamente lo que no se sabe.
    """
    r = tasa_mensual(tasa_anual_pct)
    return float(np.sum(flujos / (1 + r) ** np.arange(len(flujos))))


def tir_anual(flujos: np.ndarray) -> float | None:
    """TIR anualizada de una serie mensual, por biseccion sobre la tasa.

    Se usa biseccion y no una raiz polinomica porque la serie tiene un unico
    cambio de signo (inversion inicial, luego flujos y venta): la TIR es unica y
    la biseccion no puede devolver una raiz espuria.
    """
    def vpn(r: float) -> float:
        d = (1 + r) ** np.arange(len(flujos))
        return float(np.sum(flujos / d))

    lo, hi = -0.9, 1.0
    if vpn(lo) * vpn(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if vpn(lo) * vpn(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (1 + (lo + hi) / 2) ** MESES - 1


def plusvalia_requerida(precio_compra_uf: float, valor_mercado_uf: float,
                        arriendo_uf_mes: float, s: Supuestos,
                        objetivo_pct: float | None = None) -> float | None:
    """Apreciacion real anual necesaria para igualar el retorno alternativo.

    Es la pieza central del analisis: en vez de fingir un pronostico de
    plusvalia, entrega el umbral que el usuario tiene que creerse. Si el numero
    sale en 1 %, la inversion se sostiene casi sola; si sale en 7 %, hace falta
    un supuesto heroico sobre el barrio.
    """
    objetivo = (s.retorno_alternativo_real_pct if objetivo_pct is None
                else objetivo_pct)

    # Se resuelve VAN(g) = 0 y no TIR(g) = objetivo. Son la misma condicion en el
    # punto de corte, pero el VAN esta siempre definido: cuando la apreciacion es
    # muy negativa no existe TIR (todos los flujos son negativos) y la biseccion
    # sobre TIR se queda sin extremo inferior. El VAN, ademas, es monotono
    # creciente en g, asi que la raiz es unica.
    def f(g: float) -> float:
        return van(_flujos(precio_compra_uf, valor_mercado_uf, arriendo_uf_mes,
                           s, g), objetivo)

    lo, hi = -20.0, 30.0
    if f(lo) > 0 or f(hi) < 0:
        return None
    for _ in range(120):
        mid = (lo + hi) / 2
        if f(mid) >= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# Simulacion
# ---------------------------------------------------------------------------
def simular(precio_compra_uf: float, valor_estimado_uf: float,
            arriendo_estimado_uf: float, s: Supuestos,
            sigma_venta: float, sigma_arriendo: float,
            n: int = 4000, semilla: int = 42,
            descomponer: bool = False) -> dict:
    """Monte Carlo sobre las cuatro incertidumbres que mueven el resultado.

    Las dos primeras no son supuestos: son el error medido de cada modelo,
    convertido a escala lognormal desde su MdAPE. Las otras dos son escenario
    declarado. Simularlas juntas es lo que convierte "cap rate 4,6 %" en
    "probabilidad de batir la alternativa: 41 %", que es lo que el usuario
    necesita para decidir.
    """
    rng = np.random.default_rng(semilla)
    valor = valor_estimado_uf * np.exp(rng.normal(0, sigma_venta, n))
    arriendo = arriendo_estimado_uf * np.exp(rng.normal(0, sigma_arriendo, n))
    g = rng.normal(s.plusvalia_real_anual_pct, s.sd_plusvalia_pct, n)
    vac = np.clip(rng.normal(s.vacancia_meses_ano, 0.6, n), 0, 4)

    tires, vanes, flujos_mes, aportes = (np.empty(n), np.empty(n),
                                         np.empty(n), np.empty(n))
    for k in range(n):
        sk = Supuestos(**{**s.a_dict(), "vacancia_meses_ano": float(vac[k])})
        f = _flujos(precio_compra_uf, float(valor[k]), float(arriendo[k]), sk,
                    float(g[k]))
        ti = tir_anual(f)
        tires[k] = np.nan if ti is None else ti
        vanes[k] = van(f, s.retorno_alternativo_real_pct)
        flujos_mes[k] = f[1]
        # Cuanto dinero hay que poner ademas del pie a lo largo del horizonte:
        # es la exigencia de caja real, la que decide si el inversionista aguanta.
        aportes[k] = -float(np.sum(f[1:][f[1:] < 0]))

    ok = np.isfinite(tires)
    t = tires[ok]
    umbral = s.retorno_alternativo_real_pct / 100
    return {
        "n_simulaciones": int(n),
        "n_con_tir_definida": int(ok.sum()),
        "van_mediano_uf": float(np.median(vanes)),
        "van_p10_uf": float(np.percentile(vanes, 10)),
        "van_p90_uf": float(np.percentile(vanes, 90)),
        "prob_batir_alternativa_pct": float(100 * np.mean(vanes > 0)),
        "tir_p10_pct": float(100 * np.percentile(t, 10)) if ok.any() else None,
        "tir_mediana_pct": float(100 * np.median(t)) if ok.any() else None,
        "tir_p90_pct": float(100 * np.percentile(t, 90)) if ok.any() else None,
        "prob_tir_negativa_pct": float(100 * (np.mean(t < 0) * ok.mean()
                                              + (1 - ok.mean()))),
        "prob_flujo_mensual_negativo_pct": float(100 * np.mean(flujos_mes < 0)),
        "flujo_mensual_p10_uf": float(np.percentile(flujos_mes, 10)),
        "flujo_mensual_p90_uf": float(np.percentile(flujos_mes, 90)),
        "aporte_total_mediano_uf": float(np.median(aportes)),
        **(_descomponer(precio_compra_uf, valor_estimado_uf, arriendo_estimado_uf,
                        s, sigma_venta, sigma_arriendo, n, semilla,
                        float(np.percentile(vanes, 90) - np.percentile(vanes, 10)))
           if descomponer else {}),
    }


def _descomponer(precio, valor, arriendo, s, sig_v, sig_a, n, semilla,
                 ancho_total: float) -> dict:
    """De donde viene la incertidumbre del resultado.

    Se repite la simulacion apagando una fuente cada vez. Sirve para responder
    la pregunta correcta cuando el rango sale ancho: no siempre es culpa del
    modelo. Si el escenario de plusvalia domina, afinar la tasacion no cambiaria
    nada y lo que hay que discutir es el supuesto de apreciacion.
    """
    m = max(400, n // 4)
    solo_modelo = Supuestos(**{**s.a_dict(), "sd_plusvalia_pct": 0.0})
    a = simular(precio, valor, arriendo, solo_modelo, sig_v, sig_a, n=m,
                semilla=semilla)
    b = simular(precio, valor, arriendo, s, 0.0, 0.0, n=m, semilla=semilla)
    ancho_modelo = a["van_p90_uf"] - a["van_p10_uf"]
    ancho_escenario = b["van_p90_uf"] - b["van_p10_uf"]
    suma = ancho_modelo + ancho_escenario
    return {"dispersion_van_uf": ancho_total,
            "dispersion_por_error_de_los_modelos_uf": ancho_modelo,
            "dispersion_por_escenario_de_plusvalia_uf": ancho_escenario,
            "peso_error_modelos_pct": (100 * ancho_modelo / suma) if suma else None}


# ---------------------------------------------------------------------------
# Valor relativo por yield (Campbell-Shiller aplicado a la comuna)
# ---------------------------------------------------------------------------
REFERENCIAS = RAIZ / "modelos" / "referencias_yield.json"


def _slug(texto: str | None) -> str | None:
    """La comuna como la vieron los modelos, venga escrita como venga."""
    from .features import normalizar_comuna
    return normalizar_comuna(texto)


def cargar_referencias() -> dict:
    if REFERENCIAS.exists():
        return json.loads(REFERENCIAS.read_text(encoding="utf-8"))
    return {}


def valor_relativo(yield_bruto_pct: float, comuna: str | None,
                   referencias: dict | None = None) -> dict | None:
    """Situa el yield de la propiedad dentro de la distribucion de su comuna.

    Dos propiedades con el mismo precio no tienen el mismo retorno esperado. El
    ratio arriendo/precio es la variable que, en el marco de valor presente de
    Campbell-Shiller, resume ese retorno esperado. Un percentil alto significa
    que se esta pagando menos por cada peso de arriendo que el resto del barrio.
    """
    ref = referencias if referencias is not None else cargar_referencias()
    d = (ref.get("comunas") or {}).get(comuna or "")
    if not d:
        return None
    cortes = np.asarray(d["percentiles_yield"], float)   # p10..p90 de 10 en 10
    pct = float(np.interp(yield_bruto_pct, cortes,
                          np.linspace(10, 90, len(cortes))))
    pct = float(np.clip(pct, 1, 99))
    if pct >= 70:
        lectura = "renta más que la mayoría de su comuna para el precio que pide"
    elif pct >= 40:
        lectura = "renta lo típico de su comuna para el precio que pide"
    else:
        lectura = "renta menos que la mayoría de su comuna para el precio que pide"
    return {"comuna": comuna, "yield_bruto_pct": round(yield_bruto_pct, 2),
            "yield_mediano_comuna_pct": round(float(d["mediana_yield"]), 2),
            "percentil_en_su_comuna": round(pct),
            "lectura": lectura, "n_comparables": int(d["n"])}


# ---------------------------------------------------------------------------
# Veredicto
# ---------------------------------------------------------------------------
def analizar(precio_pedido_uf: float, estimacion_venta_uf: float,
             arriendo_estimado_clp: float, uf: float,
             sigma_venta: float, sigma_arriendo: float,
             comuna: str | None = None, s: Supuestos | None = None,
             n_simulaciones: int = 4000) -> dict:
    """El analisis completo de una propiedad, listo para el informe."""
    s = s or Supuestos()
    arriendo_uf = arriendo_estimado_clp / uf
    est = metricas_estaticas(precio_pedido_uf, arriendo_uf, s)

    g_req = plusvalia_requerida(precio_pedido_uf, estimacion_venta_uf,
                                arriendo_uf, s)
    sim = simular(precio_pedido_uf, estimacion_venta_uf, arriendo_uf, s,
                  sigma_venta, sigma_arriendo, n=n_simulaciones,
                  descomponer=True)
    rel = valor_relativo(est["yield_bruto_pct"], _slug(comuna))

    # El veredicto tiene DOS dimensiones y se informan por separado a proposito.
    # Una compra apalancada puede tener retorno esperado excelente y aun asi ser
    # inviable para quien no puede poner la diferencia todos los meses. Juntar
    # ambas cosas en una sola etiqueta es como se le vende a la gente una
    # inversion que no puede sostener.
    p = sim["prob_batir_alternativa_pct"]
    if p >= 65:
        retorno = "BUENA"
    elif p >= 50:
        retorno = "RAZONABLE"
    elif p >= 35:
        retorno = "DUDOSA"
    else:
        retorno = "MALA"

    aporte_mes_clp = max(0.0, -est["flujo_mensual_uf"]) * uf
    carga = (sim["aporte_total_mediano_uf"] / est["capital_inicial_uf"]
             if est["capital_inicial_uf"] > 0 else 0.0)
    if est["se_autofinancia"]:
        exigencia = "SE AUTOFINANCIA"
    elif carga < 0.10:
        exigencia = "APORTE BAJO"
    elif carga < 0.35:
        exigencia = "APORTE MODERADO"
    else:
        exigencia = "APORTE ALTO"

    etiqueta = f"{retorno} POR RETORNO / {exigencia}"

    razones = []
    if est["se_autofinancia"]:
        razones.append(f"el arriendo cubre el dividendo con "
                       f"{est['cobertura_dividendo']:.2f}x de holgura")
    else:
        razones.append(
            f"no se autofinancia: hay que poner ${aporte_mes_clp:,.0f} al mes "
            f"además del pie: {sim['aporte_total_mediano_uf']:,.0f} UF en "
            f"{s.horizonte_anos} años, un {100*carga:.0f} % adicional sobre el "
            f"capital inicial")
    razones.append(f"probabilidad de batir una alternativa en UF+"
                   f"{s.retorno_alternativo_real_pct:.0f}%: {p:.0f}%")
    if g_req is not None:
        razones.append(f"necesita {g_req:.1f} % real anual de plusvalía para "
                       f"igualar esa alternativa")
    if rel:
        razones.append(rel["lectura"])

    return {
        "supuestos": s.a_dict(),
        "precio_pedido_uf": round(precio_pedido_uf, 1),
        "arriendo_estimado_uf_mes": round(arriendo_uf, 2),
        "rentabilidad": {
            "yield_bruto_pct": round(est["yield_bruto_pct"], 2),
            "cap_rate_neto_pct": round(est["cap_rate_neto_pct"], 2),
            "gastos_sobre_bruto_pct": round(est["gastos_sobre_bruto_pct"], 1),
        },
        "financiamiento": {
            "capital_inicial_uf": round(est["capital_inicial_uf"], 1),
            "dividendo_mensual_uf": round(est["dividendo_mensual_uf"], 2),
            "dividendo_mensual_clp": round(est["dividendo_mensual_uf"] * uf, -3),
            "flujo_mensual_clp": round(est["flujo_mensual_uf"] * uf, -3),
            "cobertura_dividendo": (round(est["cobertura_dividendo"], 2)
                                    if est["cobertura_dividendo"] else None),
            "se_autofinancia": est["se_autofinancia"],
            "cash_on_cash_pct": (round(est["cash_on_cash_pct"], 2)
                                 if est["cash_on_cash_pct"] is not None else None),
            "precio_maximo_autofinanciable_uf":
                round(est["precio_maximo_autofinanciable_uf"], 1),
        },
        "horizonte": {
            "anos": s.horizonte_anos,
            "plusvalia_real_requerida_pct": (round(g_req, 2)
                                             if g_req is not None else None),
            "plusvalia_supuesta_pct": s.plusvalia_real_anual_pct,
            "aporte_total_mediano_uf": round(sim["aporte_total_mediano_uf"], 1),
            "aporte_sobre_capital_inicial_pct": round(100 * carga, 1),
            **{k: round(v, 2) for k, v in sim.items() if k != "n_simulaciones"},
            "n_simulaciones": sim["n_simulaciones"],
        },
        "valor_relativo": rel,
        "supuesto_clave": (
            "El precio de salida se proyecta desde el VALOR ESTIMADO por el "
            "modelo, no desde el precio pagado: comprar bajo el valor de mercado "
            "se refleja como ganancia y sobrepagar como perdida. La simulacion "
            "incorpora el error del propio modelo alrededor de ese valor."),
        "veredicto": etiqueta,
        "veredicto_retorno": retorno,
        "veredicto_exigencia_caja": exigencia,
        "razones": razones,
    }
