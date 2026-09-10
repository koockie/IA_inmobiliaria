"""Armado del registro final, con las reglas que impiden que entre basura.

Dos principios:

- **Ningun campo se adivina.** Si el aviso publica un rango en vez de un valor,
  el campo queda en None y el aviso se marca como proyecto. Tomar el minimo del
  rango es lo que produjo el `m2_util=21` con `m2_total=85` que hoy contamina 422
  filas de la base historica.
- **Todo rechazo deja motivo.** La lista `advertencias` viaja con el registro
  para que el informe pueda declarar lo que no supo leer.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime

from . import config as C
from .normalize import entero, es_rango, numero, precios, uf_actual
from .urls import Aviso

# Etiqueta de la ficha -> columna del esquema. Se compara sin tildes ni mayusculas
# y por prefijo, porque el portal alterna "Baños" / "Banos" / "Baños totales".
_ETIQUETAS = {
    "superficie total": "m2_total",
    "superficie util": "m2_util",
    "superficie construida": "m2_util",
    "dormitorios": "dormitorios",
    "banos": "banos",
    "estacionamientos": "estacionamientos",
    "bodegas": "bodegas",
    "antiguedad": "antiguedad_anos",
    "gastos comunes": "gastos_comunes_clp",
    "cantidad de pisos": None,
}
_ENTEROS = {"dormitorios", "banos", "estacionamientos", "bodegas", "antiguedad_anos"}


def _plano(texto: str) -> str:
    sin = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sin if not unicodedata.combining(c)).strip().lower()


def _columna(etiqueta: str) -> str | None:
    plano = _plano(etiqueta)
    for clave, col in _ETIQUETAS.items():
        if plano.startswith(clave):
            return col
    return None


def normalizar_comuna(nombre: str | None) -> str | None:
    return C.COMUNAS.get(_plano(nombre)) if nombre else None


def construir(aviso: Aviso, crudo: dict) -> dict:
    """Registro listo para guardar y para pasarle al analisis."""
    avisos: list[str] = []
    reg: dict = {c: None for c in _COLUMNAS}

    reg["sitio"] = aviso.sitio
    reg["id_aviso"] = crudo.get("id_aviso") or aviso.id_aviso
    reg["url"] = aviso.url
    reg["titulo"] = crudo.get("titulo")
    reg["descripcion"] = crudo.get("descripcion")
    reg["direccion"] = crudo.get("direccion")
    reg["barrio"] = crudo.get("barrio")
    reg["operacion"] = crudo.get("operacion")
    reg["tipo"] = crudo.get("tipo")
    reg["detalle_ok"] = 1
    reg["fecha_scrape"] = date.today().isoformat()
    reg["fecha_consulta"] = datetime.now().isoformat(timespec="seconds")
    reg["origen"] = "url_usuario"

    # El portal reconoce al cliente como automatizado y sirve una variante sin el
    # modelo JSON de la pagina. Es la ruta habitual, no un fallo: los datos se leen
    # igual desde JSON-LD y el HTML renderizado. Se registra para poder auditarlo.
    reg["fuente"] = "json_render" if crudo.get("fuente_estructurada") else "html"

    # --- comuna y cobertura -------------------------------------------------
    comuna = normalizar_comuna(crudo.get("comuna"))
    reg["comuna"] = comuna or (crudo.get("comuna") or None)
    fuera = comuna is None
    if fuera:
        avisos.append(
            f"La comuna '{crudo.get('comuna') or 'desconocida'}' esta fuera de la "
            "cobertura de los modelos (Macul, La Florida, Nunoa y San Miguel).")

    # --- especificaciones ---------------------------------------------------
    es_proyecto = False
    for etiqueta, texto in (crudo.get("specs") or {}).items():
        col = _columna(etiqueta)
        if col is None:
            continue
        if es_rango(texto):
            es_proyecto = True
            avisos.append(f"'{etiqueta}' viene como rango ('{texto}'): el aviso es "
                          "un proyecto con varias unidades, no una propiedad concreta.")
            continue
        valor = entero(texto) if col in _ENTEROS else numero(texto)
        if valor is not None:
            reg[col] = valor

    if es_proyecto:
        avisos.append("Aviso de proyecto: los campos con rango quedaron sin valor "
                      "en vez de inventar una cifra.")
    reg["es_proyecto"] = 1 if es_proyecto else 0

    # --- precio -------------------------------------------------------------
    reg["precio_valor"] = crudo.get("precio_valor")
    reg["precio_moneda"] = crudo.get("precio_moneda")
    uf, origen_uf = uf_actual()
    reg["uf_usada"] = uf
    if uf is None:
        avisos.append("No se pudo obtener el valor de la UF, asi que el precio "
                      "queda solo en la moneda publicada.")
    reg["precio_clp"], reg["precio_uf"] = precios(
        reg["precio_valor"], reg["precio_moneda"], uf)
    if reg["precio_valor"] is None:
        avisos.append("El aviso no publica un precio legible.")

    # --- geo ----------------------------------------------------------------
    lat, lon = numero(crudo.get("lat")), numero(crudo.get("lon"))
    if lat is not None and lon is not None:
        if C.LAT_RANGO[0] <= lat <= C.LAT_RANGO[1] and C.LON_RANGO[0] <= lon <= C.LON_RANGO[1]:
            reg["lat"], reg["lon"] = lat, lon
        else:
            avisos.append(f"Las coordenadas ({lat}, {lon}) caen fuera de Santiago; "
                          "se descartan y la estimacion pierde el bloque de ubicacion.")
    else:
        avisos.append("El aviso no publica coordenadas.")

    avisos.extend(_sanidad(reg))
    reg["advertencias"] = avisos
    reg["fuera_de_cobertura"] = fuera
    return reg


def _sanidad(reg: dict) -> list[str]:
    """Descarta valores imposibles. Anula el campo dudoso en vez de arrastrarlo."""
    avisos: list[str] = []

    for col in ("m2_util", "m2_total"):
        v = reg.get(col)
        if v is not None and not (C.M2_RANGO[0] <= v <= C.M2_RANGO[1]):
            avisos.append(f"{col} = {v} m2 esta fuera de rango razonable; se descarta.")
            reg[col] = None

    if reg.get("m2_util") and reg.get("m2_total") and reg["m2_util"] > reg["m2_total"]:
        # Una superficie util mayor que la total es imposible. Se anula la total,
        # que es la prescindible: el modelo se apoya en la util.
        avisos.append(f"La superficie util ({reg['m2_util']} m2) supera la total "
                      f"({reg['m2_total']} m2); se descarta la total por incoherente.")
        reg["m2_total"] = None

    if reg.get("dormitorios") is not None and not (0 <= reg["dormitorios"] <= C.MAX_DORMITORIOS):
        avisos.append(f"dormitorios = {reg['dormitorios']} no es plausible; se descarta.")
        reg["dormitorios"] = None
    if reg.get("banos") is not None and not (1 <= reg["banos"] <= C.MAX_BANOS):
        avisos.append(f"banos = {reg['banos']} no es plausible; se descarta.")
        reg["banos"] = None

    if reg.get("antiguedad_anos") is not None and 0 <= reg["antiguedad_anos"] <= 200:
        reg["ano_construccion"] = date.today().year - int(reg["antiguedad_anos"])

    op, uf_p, clp = reg.get("operacion"), reg.get("precio_uf"), reg.get("precio_clp")
    if op == "venta" and uf_p is not None and not (
            C.PRECIO_UF_RANGO[0] <= uf_p <= C.PRECIO_UF_RANGO[1]):
        avisos.append(f"El precio de venta ({uf_p} UF) queda fuera del rango que "
                      "vio el modelo; la estimacion no seria confiable.")
    if op == "arriendo" and clp is not None and not (
            C.PRECIO_CLP_ARRIENDO_RANGO[0] <= clp <= C.PRECIO_CLP_ARRIENDO_RANGO[1]):
        avisos.append(f"El precio de arriendo (${clp:,.0f}) queda fuera del rango "
                      "que vio el modelo; puede ser una venta mal etiquetada.")
    return avisos


# Las 30 columnas historicas mas las cuatro que agrega este flujo.
_COLUMNAS = [
    "sitio", "id_aviso", "url", "operacion", "tipo", "comuna", "barrio",
    "direccion", "titulo", "precio_valor", "precio_moneda", "precio_clp",
    "precio_uf", "m2_util", "m2_total", "dormitorios", "banos",
    "estacionamientos", "bodegas", "antiguedad_anos", "ano_construccion",
    "gastos_comunes_clp", "antiguedad_aviso_dias", "fecha_publicacion",
    "lat", "lon", "descripcion", "publica", "detalle_ok", "fecha_scrape",
    "es_proyecto", "uf_usada", "origen", "fecha_consulta", "fuente",
]
COLUMNAS = _COLUMNAS
