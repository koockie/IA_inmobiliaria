"""Render del analisis a un informe HTML legible por el usuario final.

El destinatario no es un analista: es alguien que esta pensando en comprar un
departamento y quiere saber si le conviene. Tres decisiones de presentacion se
siguen de eso:

- **El veredicto va en dos ejes separados**, retorno y exigencia de caja, porque
  juntarlos en una sola etiqueta es como se le vende a alguien una inversion con
  buen retorno esperado que no va a poder sostener mes a mes.
- **Ningun numero aparece sin su rango.** Las estimaciones traen intervalo, el
  resultado del horizonte trae percentiles y probabilidad.
- **Hay una seccion dedicada a lo que el informe NO puede decir.** Los informes
  comerciales de tasacion traen plusvalia historica, tiempo de colocacion y
  transacciones del Conservador; con una foto de 15 dias de avisos no se puede
  hacer ninguna de las tres, y callarlo seria lo unico deshonesto.

La paleta es la misma que usan los notebooks del proyecto.
"""
from __future__ import annotations

from html import escape

# El modelo trabaja con slugs; el informe se lee en castellano.
NOMBRES_COMUNA = {"nunoa": "Ñuñoa", "la-florida": "La Florida",
                  "san-miguel": "San Miguel", "macul": "Macul"}

PALETA = {
    "acento": "#0A6B67", "alerta": "#8A3E5C", "aviso": "#C08A2E",
    "apoyo": "#3B6EA5",
}


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------
def _miles(n: float, dec: int = 0) -> str:
    """Formato chileno: punto para miles, coma para decimales."""
    s = f"{n:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def clp(n: float) -> str:
    m = round(n / 1000) * 1000
    return f"{'-' if m < 0 else ''}${_miles(abs(m))}"


def uf(n: float, dec: int = 0) -> str:
    return f"UF {_miles(n, dec)}"


def pct(n: float | None, dec: int = 1) -> str:
    return "—" if n is None else f"{_miles(n, dec)} %"


# ---------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------
def _ficha(rotulo: str, valor: str, nota: str = "", tono: str = "") -> str:
    clase = f"ficha{' ' + tono if tono else ''}"
    pie = f'<p class="nota">{escape(nota)}</p>' if nota else ""
    return (f'<div class="{clase}"><p class="rotulo">{escape(rotulo)}</p>'
            f'<p class="cifra">{valor}</p>{pie}</div>')


def _barra(p: float) -> str:
    """La probabilidad de exito, como barra: se lee antes que el numero."""
    tono = "bien" if p >= 65 else ("medio" if p >= 40 else "mal")
    return (f'<div class="barra"><div class="relleno {tono}" '
            f'style="width:{max(1.0, min(99.0, p)):.1f}%"></div>'
            f'<span class="marca" title="umbral de decision"></span></div>')


def _tabla(filas: list[tuple[str, str]], clase: str = "") -> str:
    cuerpo = "".join(f"<tr><th scope=\"row\">{escape(k)}</th><td>{v}</td></tr>"
                     for k, v in filas)
    return f'<div class="scroll"><table class="{clase}"><tbody>{cuerpo}</tbody></table></div>'


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------
def render(resultado: dict, propiedad: dict, documento: bool = True) -> str:
    """`resultado` es la respuesta de POST /analizar; `propiedad` sus atributos."""
    t, inv = resultado["tasacion"], resultado["inversion"]
    jp = resultado["juicio_de_precio"]
    ren, fin, hor = inv["rentabilidad"], inv["financiamiento"], inv["horizonte"]
    sup, rel = inv["supuestos"], inv.get("valor_relativo")

    tipo = str(propiedad.get("tipo", "propiedad")).capitalize()
    slug = str(propiedad.get("comuna", "") or "")
    comuna = NOMBRES_COMUNA.get(slug, slug.replace("-", " ").title())
    m2 = propiedad.get("m2_util")
    dorm = propiedad.get("dormitorios")
    banos = propiedad.get("banos")
    resumen = " · ".join(x for x in [
        f"{_miles(m2)} m² útiles" if m2 else "",
        f"{int(dorm)}D" if dorm else "", f"{int(banos)}B" if banos else "",
        f"año {int(propiedad['ano_construccion'])}"
        if propiedad.get("ano_construccion") else ""] if x)

    tono_caja = ("bien" if fin["se_autofinancia"]
                 else ("medio" if inv["veredicto_exigencia_caja"] == "APORTE BAJO"
                       else ("medio" if inv["veredicto_exigencia_caja"] == "APORTE MODERADO"
                             else "mal")))
    tono_ret = {"BUENA": "bien", "RAZONABLE": "medio",
                "DUDOSA": "medio", "MALA": "mal"}[inv["veredicto_retorno"]]

    partes: list[str] = []
    partes.append(f"""
<header class="portada">
  <p class="eyebrow">Análisis de inversión · modelo propio</p>
  <h1>{escape(tipo)} en {escape(comuna)}</h1>
  <p class="resumen">{escape(resumen)}</p>
</header>

<section class="veredicto">
  <div class="eje">
    <p class="rotulo">Retorno esperado</p>
    <p class="chip {tono_ret}">{escape(inv['veredicto_retorno'])}</p>
    <p class="nota">{pct(hor['prob_batir_alternativa_pct'], 0)} de probabilidad de
      superar una alternativa en UF+{_miles(sup['retorno_alternativo_real_pct'])} %
      en {sup['horizonte_anos']} años</p>
    {_barra(hor['prob_batir_alternativa_pct'])}
  </div>
  <div class="eje">
    <p class="rotulo">Exigencia de caja</p>
    <p class="chip {tono_caja}">{escape(inv['veredicto_exigencia_caja'])}</p>
    <p class="nota">{'El arriendo cubre el dividendo.' if fin['se_autofinancia']
      else f"Hay que aportar {clp(-fin['flujo_mensual_clp'])} al mes, además del pie."}</p>
  </div>
</section>

<section>
  <h2>Qué dicen los dos modelos</h2>
  <div class="fichas">
    {_ficha("Valor de venta estimado", uf(t['venta']['valor']),
            f"rango {uf(t['venta']['rango'][0])} – {uf(t['venta']['rango'][1])} · "
            f"confianza {t['venta']['confianza']}")}
    {_ficha("Arriendo mensual estimado", clp(t['arriendo']['valor']),
            f"rango {clp(t['arriendo']['rango'][0])} – {clp(t['arriendo']['rango'][1])} · "
            f"confianza {t['arriendo']['confianza']}")}
    {_ficha("Precio pedido", uf(jp['precio_pedido_uf']),
            f"{jp['veredicto'].lower()} · {_miles(jp['brecha_pct'], 1)} % respecto del estimado")}
  </div>
  <p class="cuerpo">Cada rango contiene el valor real cerca del 80 % de las veces:
    está calibrado sobre propiedades que el modelo nunca vio, no es un ±10 % puesto
    a ojo. El error típico es de {pct(t['venta']['error_tipico_pct'])} en venta y
    {pct(t['arriendo']['error_tipico_pct'])} en arriendo.</p>
</section>

<section>
  <h2>Rentabilidad</h2>
  <div class="fichas">
    {_ficha("Yield bruto", pct(ren['yield_bruto_pct'], 2), "arriendo anual sobre precio")}
    {_ficha("Cap rate neto", pct(ren['cap_rate_neto_pct'], 2),
            f"después de {pct(ren['gastos_sobre_bruto_pct'], 0)} de gastos y vacancia")}
    {_ficha("Cobertura del dividendo",
            f"{_miles(fin['cobertura_dividendo'], 2)}×" if fin['cobertura_dividendo'] else "—",
            "arriendo neto ÷ dividendo")}
  </div>
  {_tabla([
      ("Capital inicial (pie + gastos de compra)", uf(fin['capital_inicial_uf'])),
      ("Dividendo mensual", f"{clp(fin['dividendo_mensual_clp'])} "
       f"<span class='sec'>({uf(fin['dividendo_mensual_uf'], 2)})</span>"),
      ("Flujo mensual después del dividendo", f"<b class='{tono_caja}'>"
       f"{clp(fin['flujo_mensual_clp'])}</b>"),
      ("Precio máximo al que se autofinanciaría",
       uf(fin['precio_maximo_autofinanciable_uf'])),
  ])}
</section>

<section>
  <h2>Tenerla {sup['horizonte_anos']} años y venderla</h2>
  <p class="cuerpo destacado">Este informe <b>no predice la plusvalía</b>. Con
    datos de 15 días no se puede, y afirmarlo sería inventar. La pregunta se
    invierte: <b>cuánta apreciación real anual necesitaría esta propiedad para
    que la inversión valga la pena</b>. Ese umbral sí se deduce, y es contra él
    que conviene contrastar lo que ha hecho el sector.</p>
  <div class="fichas">
    {_ficha("Plusvalía real anual requerida", pct(hor['plusvalia_real_requerida_pct'], 1),
            f"para igualar UF+{_miles(sup['retorno_alternativo_real_pct'])} %", "ancha")}
    {_ficha("Resultado mediano", uf(hor['van_mediano_uf']),
            f"entre {uf(hor['van_p10_uf'])} y {uf(hor['van_p90_uf'])} en 8 de cada 10 casos")}
    {_ficha("Aporte total del período", uf(hor['aporte_total_mediano_uf']),
            f"un {pct(hor['aporte_sobre_capital_inicial_pct'], 0)} sobre el capital inicial"
            if hor.get('aporte_sobre_capital_inicial_pct') else "")}
  </div>
  {_tabla([
      ("Probabilidad de superar la alternativa",
       f"<b>{pct(hor['prob_batir_alternativa_pct'], 0)}</b>"),
      ("Probabilidad de terminar con pérdida real", pct(hor['prob_tir_negativa_pct'], 0)),
      ("Retorno anual real, mediano", pct(hor['tir_mediana_pct'], 1)),
      ("Retorno anual real, escenario malo (p10)", pct(hor['tir_p10_pct'], 1)),
      ("Retorno anual real, escenario bueno (p90)", pct(hor['tir_p90_pct'], 1)),
  ])}
  <p class="cuerpo">De la dispersión de ese resultado,
    {pct(hor.get('peso_error_modelos_pct'), 0)} viene del error de los modelos y el
    resto del supuesto de apreciación. Dicho de otro modo: afinar la tasación
    movería poco la aguja; lo que hay que discutir es cuánto va a subir el sector.</p>
</section>
""")

    if rel:
        partes.append(f"""
<section>
  <h2>Comparada con su comuna</h2>
  <p class="cuerpo">El ratio arriendo/precio es, en el marco de valor presente de
    Campbell y Shiller, el resumen de lo que el mercado espera ganar con un activo.
    Comparar el de esta propiedad con el de las {_miles(rel['n_comparables'])} de su
    comuna dice si se está pagando más o menos por cada peso de arriendo.</p>
  {_tabla([
      ("Yield de esta propiedad", pct(rel['yield_bruto_pct'], 2)),
      (f"Yield mediano en {escape(comuna)}", pct(rel['yield_mediano_comuna_pct'], 2)),
      ("Percentil dentro de su comuna", f"<b>{rel['percentil_en_su_comuna']}</b> de 100"),
  ])}
  <p class="cuerpo"><b>{escape(rel['lectura'].capitalize())}.</b></p>
</section>""")

    filas_sup = [
        ("Pie", pct(sup["pie_pct"], 0)),
        ("Tasa del crédito (UF, anual)", pct(sup["tasa_anual_pct"], 2)),
        ("Plazo", f"{sup['plazo_anos']} años"),
        ("Vacancia supuesta", f"{_miles(sup['vacancia_meses_ano'], 1)} meses al año"),
        ("Administración y mantención",
         f"{pct(sup['administracion_pct_arriendo'], 0)} + "
         f"{pct(sup['mantencion_pct_arriendo'], 0)} del arriendo"),
        ("Contribuciones y seguros",
         f"{pct(sup['contribuciones_pct_precio'], 2)} + "
         f"{pct(sup['seguros_pct_precio'], 2)} del precio, al año"),
        ("Costos de compra y de venta",
         f"{pct(sup['costos_compra_pct'], 1)} y {pct(sup['costos_venta_pct'], 1)}"),
        ("Apreciación real supuesta",
         f"{pct(sup['plusvalia_real_anual_pct'], 1)} ± {pct(sup['sd_plusvalia_pct'], 1)} al año"),
        ("Crecimiento real del arriendo", pct(sup["crecimiento_arriendo_real_pct"], 1)),
        ("Alternativa de comparación", f"UF + {pct(sup['retorno_alternativo_real_pct'], 0)}"),
    ]
    avisos = "".join(f"<li>{escape(a)}</li>" for a in resultado["advertencias"])
    partes.append(f"""
<section>
  <h2>Supuestos</h2>
  <p class="cuerpo">Todos son editables y todos cambian el resultado. Están aquí
    porque un veredicto de inversión sin sus supuestos a la vista no es
    verificable.</p>
  {_tabla(filas_sup, "supuestos")}
</section>

<section class="limites">
  <h2>Lo que este informe no puede decirte</h2>
  <p class="cuerpo">Los informes comerciales de tasación traen tres secciones que
    aquí no aparecen. No es una omisión: los datos disponibles no las soportan y
    fabricarlas sería el único error grave posible en un documento como este.</p>
  <ul class="limites-lista">
    <li><b>Evolución histórica y plusvalía del sector.</b> Exige series de
      precios de varios años. El dataset es una fotografía de 15 días.</li>
    <li><b>Tiempo esperado de colocación.</b> Exige saber cuándo se publicó y
      cuándo se cerró cada aviso. Solo se observa el stock publicado.</li>
    <li><b>Transacciones efectivas del Conservador.</b> Exige el registro de
      compraventas. Aquí se observan precios <i>pedidos</i>, que en Chile suelen
      quedar entre 5 % y 15 % por encima del cierre.</li>
  </ul>
  <h3>Advertencias de esta estimación</h3>
  <ul class="avisos">{avisos}</ul>
</section>

<footer>
  <p>Estimaciones generadas por modelos hedónicos propios sobre
    {escape(str(propiedad.get('_n_avisos', 'avisos publicados')))} en Macul, La
    Florida, Ñuñoa y San Miguel. Error típico de {pct(t['venta']['error_tipico_pct'])}
    en venta y {pct(t['arriendo']['error_tipico_pct'])} en arriendo, medido sobre
    propiedades nunca vistas por el modelo. <b>No constituye una tasación
    comercial ni asesoría financiera.</b></p>
</footer>""")

    cuerpo = "\n".join(partes)
    titulo = f"{tipo} en {comuna}"
    pagina = (f"<title>{escape(titulo)}</title>" + _FUENTES
              + f"<style>{_CSS}</style><main>{cuerpo}</main>")
    if not documento:
        return pagina
    return ("<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"{pagina}</body></html>".replace("<main>", "</head><body><main>"))


_FUENTES = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
            'family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&'
            'family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">')

_CSS = """
:root{
  --papel:#F6F8F7; --tarjeta:#FFFFFF; --tinta:#101C1B; --tenue:#5C6E6B;
  --linea:#DBE4E2; --acento:#0A6B67; --acento-suave:#E4EFEE;
  --alerta:#8A3E5C; --aviso:#9A6B18; --bien:#0A6B67;
  --sombra:0 1px 2px rgba(16,28,27,.05), 0 6px 20px -12px rgba(16,28,27,.18);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --papel:#0D1413; --tarjeta:#141F1D; --tinta:#E7EEEC; --tenue:#93A5A2;
    --linea:#243330; --acento:#4FA8A2; --acento-suave:#16302E;
    --alerta:#D08AA4; --aviso:#D6A94A; --bien:#4FA8A2;
    --sombra:0 1px 2px rgba(0,0,0,.3), 0 8px 24px -14px rgba(0,0,0,.6);
  }
}
:root[data-theme="dark"]{
  --papel:#0D1413; --tarjeta:#141F1D; --tinta:#E7EEEC; --tenue:#93A5A2;
  --linea:#243330; --acento:#4FA8A2; --acento-suave:#16302E;
  --alerta:#D08AA4; --aviso:#D6A94A; --bien:#4FA8A2;
  --sombra:0 1px 2px rgba(0,0,0,.3), 0 8px 24px -14px rgba(0,0,0,.6);
}
*{box-sizing:border-box}
body{margin:0;background:var(--papel);color:var(--tinta);
  font-family:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
  font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
main{max-width:60rem;margin:0 auto;padding:clamp(1.5rem,4vw,3.5rem) clamp(1rem,4vw,2rem) 4rem;
  display:flex;flex-direction:column;gap:clamp(2rem,4vw,3rem)}
h1,h2,h3{font-family:"Source Serif 4",Georgia,serif;text-wrap:balance;
  font-weight:600;margin:0;letter-spacing:-.01em}
h1{font-size:clamp(2rem,5vw,2.9rem);line-height:1.12}
h2{font-size:1.4rem;margin-bottom:1rem;padding-bottom:.5rem;
  border-bottom:1px solid var(--linea)}
h3{font-size:1.05rem;margin:1.75rem 0 .6rem}
p{margin:0}
section{display:flex;flex-direction:column;gap:.35rem}
.eyebrow,.rotulo{font-size:.72rem;font-weight:600;letter-spacing:.09em;
  text-transform:uppercase;color:var(--tenue);margin-bottom:.35rem}
.portada{border-bottom:3px solid var(--acento);padding-bottom:1.25rem}
.resumen{font-size:1.05rem;color:var(--tenue);margin-top:.5rem}
.cuerpo{max-width:62ch;color:var(--tinta);margin-top:.9rem}
.destacado{border-left:3px solid var(--acento);padding:.15rem 0 .15rem 1rem}
.nota{font-size:.85rem;color:var(--tenue);margin-top:.4rem}
.sec{color:var(--tenue)}

.veredicto{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(17rem,1fr))}
.eje{background:var(--tarjeta);border:1px solid var(--linea);border-radius:4px;
  padding:1.25rem;box-shadow:var(--sombra)}
.chip{display:inline-block;font-family:"IBM Plex Mono",monospace;font-weight:500;
  font-size:.95rem;letter-spacing:.02em;padding:.3rem .7rem;border-radius:3px;
  border:1px solid currentColor}
.chip.bien{color:var(--bien);background:var(--acento-suave)}
.chip.medio{color:var(--aviso);background:color-mix(in srgb,var(--aviso) 12%,transparent)}
.chip.mal{color:var(--alerta);background:color-mix(in srgb,var(--alerta) 12%,transparent)}
b.bien{color:var(--bien)} b.medio{color:var(--aviso)} b.mal{color:var(--alerta)}

.barra{position:relative;height:.5rem;background:var(--linea);border-radius:99px;
  margin-top:.9rem;overflow:visible}
.relleno{height:100%;border-radius:99px}
.relleno.bien{background:var(--bien)} .relleno.medio{background:var(--aviso)}
.relleno.mal{background:var(--alerta)}
.marca{position:absolute;left:50%;top:-.28rem;width:1px;height:1.05rem;
  background:var(--tenue)}

.fichas{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));
  margin-top:.5rem}
.ficha{background:var(--tarjeta);border:1px solid var(--linea);border-radius:4px;
  padding:1.1rem}
.ficha.ancha{border-color:var(--acento);border-width:1px 1px 1px 3px}
.cifra{font-family:"IBM Plex Mono",monospace;font-size:1.5rem;font-weight:500;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em;line-height:1.2}

.scroll{overflow-x:auto;margin-top:1.1rem}
table{width:100%;border-collapse:collapse;font-size:.94rem}
th,td{text-align:left;padding:.6rem .75rem;border-bottom:1px solid var(--linea);
  vertical-align:baseline}
th{font-weight:400;color:var(--tenue)}
td{font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums;
  text-align:right;white-space:nowrap}
tr:last-child th,tr:last-child td{border-bottom:none}
table.supuestos td{font-size:.9rem}

.limites{background:var(--tarjeta);border:1px solid var(--linea);border-radius:4px;
  padding:clamp(1.1rem,3vw,1.75rem)}
.limites h2{margin-top:0}
.limites-lista,.avisos{max-width:62ch;padding-left:1.1rem;margin:1rem 0 0;
  display:flex;flex-direction:column;gap:.55rem}
.avisos{font-size:.88rem;color:var(--tenue)}
footer{border-top:1px solid var(--linea);padding-top:1.25rem;font-size:.82rem;
  color:var(--tenue);max-width:70ch}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""
