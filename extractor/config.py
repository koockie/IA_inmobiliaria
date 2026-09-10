"""Constantes del extractor. Sin logica, solo valores que gobiernan el resto."""
from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# --- red -------------------------------------------------------------------
# El User-Agent se identifica de verdad. No imitamos un navegador: el robots.txt
# de mercadolibre.cl bloquea agentes de IA declarados (ClaudeBot, GPTBot y otros)
# pero su grupo `User-agent: *` no prohibe las fichas, y el de
# portalinmobiliario.com solo excluye /propiedades/, que no es donde viven.
# Si algun dia bloquean este UA, se respeta y se migra a la API oficial.
USER_AGENT = ("InmobiliarioMVP/0.1 (proyecto academico; "
              "+https://github.com/koockie/IA_inmobiliaria)")
CABECERAS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-CL,es;q=0.9",
}
TIMEOUT_S = 30
MAX_REINTENTOS = 3
ESPERA_BLOQUEO_S = (5, 10, 15)   # backoff ante 403/429

# Una ficha legitima pesa cientos de KB y trae la tabla de especificaciones.
# Una pagina de verificacion tambien responde 200, pero es corta y no la trae.
MIN_BYTES_FICHA = 50_000

# --- dominios --------------------------------------------------------------
DOMINIOS = {
    "portalinmobiliario.com": "pi",
    "www.portalinmobiliario.com": "pi",
    "mercadolibre.cl": "ml",
    "www.mercadolibre.cl": "ml",
    "casa.mercadolibre.cl": "ml",
    "departamento.mercadolibre.cl": "ml",
    "inmueble.mercadolibre.cl": "ml",
    "articulo.mercadolibre.cl": "ml",
}

# --- cobertura de los modelos ----------------------------------------------
COMUNAS = {
    "nunoa": "nunoa", "ñuñoa": "nunoa",
    "macul": "macul",
    "la florida": "la-florida", "la-florida": "la-florida",
    "san miguel": "san-miguel", "san-miguel": "san-miguel",
}

# --- rangos de sanidad ------------------------------------------------------
# Los mismos limites que usa el pipeline de ML, para que no entre a la base algo
# que el modelo despues no pueda tasar.
LAT_RANGO = (-33.70, -33.40)
LON_RANGO = (-70.70, -70.45)
M2_RANGO = (10.0, 2000.0)
PRECIO_UF_RANGO = (200.0, 100_000.0)        # venta
PRECIO_CLP_ARRIENDO_RANGO = (80_000.0, 10_000_000.0)
MAX_DORMITORIOS = 12
MAX_BANOS = 12

# --- rutas ------------------------------------------------------------------
DB_CONSULTAS = RAIZ / "data" / "consultas_usuario.sqlite"
CACHE_DIR = RAIZ / "data" / "cache_fichas"
CACHE_TTL_HORAS = 24
UF_RESPALDO = RAIZ / "data" / "uf_ultimo_valor.json"
