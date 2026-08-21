"""Carga, reparacion y filtrado del dataset de ofertas.

Este modulo NUNCA escribe en data/: abre el SQLite en modo solo lectura.

Dos convenciones del dataset que hay que deshacer aqui:
  1. Las celdas vacias contienen el texto "SIN_DATO", no NULL.
  2. Todas las columnas estan tipadas TEXT (salvo detalle_ok), incluidos los numeros.

Ningun otro script del repo lee "SIN_DATO" de vuelta como faltante. Ojo con el
patron de resumen_dataset.py:132, que hace CAST(precio_uf AS REAL) en SQL sin
filtrar: SQLite devuelve 0.0 para "SIN_DATO" y contamina las medianas en
silencio. Aqui todo el casting pasa por pandas con errors="coerce".
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ml import config

COLUMNAS_NUMERICAS = [
    "precio_valor", "precio_clp", "precio_uf", "m2_util", "m2_total",
    "dormitorios", "banos", "estacionamientos", "bodegas",
    "antiguedad_anos", "ano_construccion", "gastos_comunes_clp",
    "lat", "lon", "antiguedad_aviso_dias", "detalle_ok",
]


@dataclass(frozen=True)
class PasoFiltro:
    """Registro auditable de un paso de limpieza.

    `eliminadas` son filas que se van; `anuladas` son celdas puestas a NaN sin
    descartar la fila. La distincion importa: descartar 410 filas por una
    inconsistencia en m2_total (campo secundario) seria caro cuando venta-casa
    tiene ~3.100 filas utilizables.
    """
    nombre: str
    antes: int
    despues: int
    eliminadas: int
    anuladas: int
    motivo: str

    def a_dict(self) -> dict:
        return {"nombre": self.nombre, "antes": self.antes, "despues": self.despues,
                "eliminadas": self.eliminadas, "anuladas": self.anuladas,
                "motivo": self.motivo}


@dataclass
class ReporteReparacion:
    uf_usada: float
    procedencia: str
    clp_a_uf: int = 0
    uf_a_clp: int = 0
    sin_ningun_precio: int = 0

    def a_dict(self) -> dict:
        return {"uf_usada": self.uf_usada, "uf_procedencia": self.procedencia,
                "clp_a_uf": self.clp_a_uf, "uf_a_clp": self.uf_a_clp,
                "sin_ningun_precio": self.sin_ningun_precio}


@dataclass
class InformeCarga:
    operacion: str
    tipo: str
    filas_crudas: int
    filas_finales: int
    reparacion: ReporteReparacion
    pasos: list[PasoFiltro] = field(default_factory=list)

    def a_dict(self) -> dict:
        return {"operacion": self.operacion, "tipo": self.tipo,
                "filas_crudas": self.filas_crudas, "filas_finales": self.filas_finales,
                "reparacion": self.reparacion.a_dict(),
                "filtros": [p.a_dict() for p in self.pasos]}

    def como_tabla(self) -> str:
        anchos = (34, 9, 9, 11, 10)
        cab = f"{'filtro':<{anchos[0]}}{'antes':>{anchos[1]}}{'despues':>{anchos[2]}}"
        cab += f"{'eliminadas':>{anchos[3]}}{'anuladas':>{anchos[4]}}   motivo"
        lineas = [cab, "-" * 100]
        for p in self.pasos:
            fila = f"{p.nombre:<{anchos[0]}}{p.antes:>{anchos[1]},}{p.despues:>{anchos[2]},}"
            fila += f"{p.eliminadas:>{anchos[3]},}{p.anuladas:>{anchos[4]},}   {p.motivo}"
            lineas.append(fila)
        lineas.append("-" * 100)
        lineas.append(f"{'TOTAL':<{anchos[0]}}{self.filas_crudas:>{anchos[1]},}"
                      f"{self.filas_finales:>{anchos[2]},}")
        return "\n".join(lineas)


# --------------------------------------------------------------------------
# Carga
# --------------------------------------------------------------------------
def cargar_crudo(db_path: Path | str = config.DB_PATH, *, tabla: str = "ofertas") -> pd.DataFrame:
    """Lee la tabla completa en modo SOLO LECTURA, sin transformar nada."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"no existe la base: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=15) as con:
        return pd.read_sql_query(f"SELECT * FROM {tabla}", con)


def a_faltantes(df: pd.DataFrame, marcador: str = config.MARCADOR) -> pd.DataFrame:
    """Convierte el centinela "SIN_DATO" en NA. Debe correr ANTES del casteo.

    Con el orden correcto, cualquier valor que despues no parsee a numero es
    basura real y no un faltante disfrazado.
    """
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object:
            serie = df[col].astype("string").str.strip()
            df[col] = serie.mask(serie == marcador)
    return df


def castear_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Numeros a float64 (no nullable) y texto normalizado.

    Se usa float64 con np.nan y no Float64 nullable a proposito: LightGBM y
    XGBoost manejan np.nan nativamente, mientras que los dtypes nullable rompen
    el paso a numpy en varios estimadores.
    """
    df = df.copy()
    for col in COLUMNAS_NUMERICAS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    for col in ("operacion", "tipo", "comuna", "sitio", "barrio"):
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip().str.lower()
    return df


def normalizar_texto(valor: object) -> str:
    """Minusculas, sin tildes y con espacios colapsados. Para claves de agrupacion."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)) or valor is pd.NA:
        return ""
    s = unicodedata.normalize("NFKD", str(valor).strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


# --------------------------------------------------------------------------
# Reparacion de precios
# --------------------------------------------------------------------------
def uf_implicita(df: pd.DataFrame) -> float | None:
    """Deriva la UF de las filas que tienen ambos precios.

    Es preferible a consultar mindicador.cl: la API devolveria la UF de hoy, y
    la que hace falta es la del dia del scrape.
    """
    ambos = df["precio_clp"].notna() & df["precio_uf"].notna() & (df["precio_uf"] > 0)
    if ambos.sum() < 100:
        return None
    razon = (df.loc[ambos, "precio_clp"] / df.loc[ambos, "precio_uf"]).median()
    minimo, maximo = config.UF_BANDA_VALIDA
    return float(razon) if minimo <= razon <= maximo else None


def uf_referencia(df: pd.DataFrame | None = None, *, online: bool = False) -> tuple[float, str]:
    """Devuelve (valor, procedencia). Prioriza la UF implicita en los datos."""
    if online:
        try:
            from scraper.normalize import uf_del_dia
            valor = uf_del_dia()
            if valor and config.UF_BANDA_VALIDA[0] <= valor <= config.UF_BANDA_VALIDA[1]:
                return float(valor), "mindicador.cl"
        except Exception:
            pass
    if df is not None:
        valor = uf_implicita(df)
        if valor is not None:
            return valor, "mediana_implicita_dataset"
    return config.UF_FALLBACK_CLP, "constante_empirica"


def reparar_precios(df: pd.DataFrame, uf: float) -> tuple[pd.DataFrame, ReporteReparacion]:
    """Reconstruye el precio faltante en AMBAS direcciones.

    El 27/07/2026 la API de la UF fallo y el scraper guardo solo el precio en la
    moneda original. El fallo fue bidireccional, cosa que el documento de
    traspaso solo diagnostica a medias:

      - 3.102 filas en CLP quedaron sin precio_uf  -> recupera ~1.179 ventas
      - 3.747 filas en UF  quedaron sin precio_clp -> recupera 266 arriendos

    `precio_origen` queda como columna de auditoria (nunca como feature) para
    poder comparar despues el error del modelo entre filas originales y
    reconstruidas.
    """
    df = df.copy()
    origen = pd.Series("scraper", index=df.index, dtype="object")

    falta_uf = df["precio_uf"].isna() & df["precio_clp"].notna() & (df["precio_clp"] > 0)
    falta_clp = df["precio_clp"].isna() & df["precio_uf"].notna() & (df["precio_uf"] > 0)

    df.loc[falta_uf, "precio_uf"] = df.loc[falta_uf, "precio_clp"] / uf
    origen[falta_uf] = "reconstruido_clp_a_uf"

    df.loc[falta_clp, "precio_clp"] = df.loc[falta_clp, "precio_uf"] * uf
    origen[falta_clp] = "reconstruido_uf_a_clp"

    df["precio_origen"] = origen
    reporte = ReporteReparacion(
        uf_usada=round(float(uf), 2), procedencia="",
        clp_a_uf=int(falta_uf.sum()), uf_a_clp=int(falta_clp.sum()),
        sin_ningun_precio=int((df["precio_uf"].isna() & df["precio_clp"].isna()).sum()),
    )
    return df, reporte


# --------------------------------------------------------------------------
# Filtros
# --------------------------------------------------------------------------
class _Registro:
    """Acumula los pasos de filtrado midiendo filas y celdas afectadas."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.pasos: list[PasoFiltro] = []

    def eliminar(self, mascara_conservar: pd.Series, nombre: str, motivo: str) -> None:
        antes = len(self.df)
        self.df = self.df[mascara_conservar.reindex(self.df.index, fill_value=True)]
        despues = len(self.df)
        self.pasos.append(PasoFiltro(nombre, antes, despues, antes - despues, 0, motivo))

    def anular(self, mascara: pd.Series, columnas: list[str], nombre: str, motivo: str) -> None:
        antes = len(self.df)
        mascara = mascara.reindex(self.df.index, fill_value=False)
        anuladas = 0
        for col in columnas:
            if col in self.df.columns:
                afectadas = int((mascara & self.df[col].notna()).sum())
                self.df.loc[mascara, col] = np.nan
                anuladas += afectadas
        self.pasos.append(PasoFiltro(nombre, antes, antes, 0, anuladas, motivo))


def _recorte_por_grupo(df: pd.DataFrame, columna: str,
                       percentiles: tuple[float, float] = config.RECORTE_PERCENTILES) -> pd.Series:
    """Marca las filas fuera de [p1, p99] dentro de cada (comuna, tipo).

    Los grupos con menos de RECORTE_N_MINIMO filas usan los percentiles
    globales, porque un p99 calculado sobre 20 observaciones no significa nada.
    """
    conservar = pd.Series(True, index=df.index)
    bajo, alto = percentiles
    valores = df[columna]
    g_bajo, g_alto = np.nanpercentile(valores.dropna(), [bajo, alto]) if valores.notna().any() else (np.nan, np.nan)

    for _, idx in df.groupby(["comuna", "tipo"], observed=True).groups.items():
        sub = valores.loc[idx].dropna()
        if len(sub) >= config.RECORTE_N_MINIMO:
            lo, hi = np.percentile(sub, [bajo, alto])
        else:
            lo, hi = g_bajo, g_alto
        if np.isnan(lo) or np.isnan(hi):
            continue
        fuera = valores.loc[idx].notna() & ((valores.loc[idx] < lo) | (valores.loc[idx] > hi))
        conservar.loc[idx[fuera]] = False
    return conservar


def aplicar_filtros(df: pd.DataFrame, operacion: str, tipo: str | None = None, *,
                    con_recorte_final: bool = True
                    ) -> tuple[pd.DataFrame, list[PasoFiltro]]:
    """Cadena de filtros de calidad, de estructurales a estadisticos.

    El orden importa: los percentiles del ultimo paso se calculan sobre datos ya
    limpios, o los propios outliers los distorsionarian.
    """
    target = config.TARGET[operacion]
    reg = _Registro(df)

    reg.eliminar(df["operacion"] == operacion, "segmento_operacion", operacion)
    if tipo and tipo != "todos":
        reg.eliminar(reg.df["tipo"] == tipo, "segmento_tipo", tipo)

    d = reg.df
    reg.eliminar(d[target].notna() & (d[target] > 0), "target_presente",
                 f"{target} > 0 (post reparacion UF)")

    d = reg.df
    reg.eliminar(d["m2_util"].notna(), "m2_util_presente", "m2_util no nulo")

    # Rango de superficie por segmento. El dataset trae m2_util minimo 1,0 en
    # los tres segmentos grandes y maximos de hasta 138.000.
    d = reg.df
    tipos = [tipo] if tipo and tipo != "todos" else list(config.TIPOS)
    conservar = pd.Series(False, index=d.index)
    detalle = []
    for t in tipos:
        u = config.UMBRALES[(operacion, t)]
        es_t = d["tipo"] == t
        conservar |= es_t & d["m2_util"].between(*u.m2_util)
        detalle.append(f"{t} {u.m2_util[0]:g}-{u.m2_util[1]:g}")
    reg.eliminar(conservar, "m2_util_rango", " / ".join(detalle) + " m2")

    # m2_util > m2_total es inconsistencia del publicador (410 filas). Se anula
    # el campo secundario en vez de perder la fila: el target no esta afectado.
    d = reg.df
    inconsistente = d["m2_total"].notna() & (d["m2_util"] > d["m2_total"])
    reg.df = reg.df.assign(m2_inconsistente=inconsistente.astype("int8"))
    reg.anular(inconsistente, ["m2_total"], "m2_total_inconsistente", "m2_util > m2_total")

    # Rango duro de precio. Ataca la contaminacion de operacion: el dataset trae
    # "arriendos" de 194 y 220 millones de CLP, que son ventas mal etiquetadas.
    d = reg.df
    u = config.UMBRALES[(operacion, tipos[0])]
    reg.eliminar(d[target].between(*u.precio), "precio_rango_duro",
                 f"{target} {u.precio[0]:,.0f}-{u.precio[1]:,.0f}")

    # Coherencia entre las dos monedas: detecta parseos rotos en cualquiera de
    # los dos campos (precio_uf llega a tener un minimo de 0,2).
    d = reg.df
    ambos = d["precio_clp"].notna() & d["precio_uf"].notna() & (d["precio_uf"] > 0)
    razon = d["precio_clp"] / d["precio_uf"]
    coherente = ~ambos | razon.between(*config.UF_BANDA_VALIDA)
    reg.eliminar(coherente, "coherencia_uf_clp",
                 f"precio_clp/precio_uf en {config.UF_BANDA_VALIDA}")

    # Red autocalibrada contra contaminacion residual de operacion.
    d = reg.df
    mediana_seg = d.groupby(["comuna", "tipo"], observed=True)[target].transform("median")
    reg.eliminar(d[target] <= 20 * mediana_seg, "contaminacion_relativa",
                 "precio <= 20x mediana de su (comuna, tipo)")

    # Coordenadas fuera de las 4 comunas: el dataset trae lon minimo -71,2193,
    # unos 70 km al oeste. Se anula la geo y se marca con un flag.
    d = reg.df
    geo_ok = d["lat"].between(*config.BBOX_LAT) & d["lon"].between(*config.BBOX_LON)
    reg.df = reg.df.assign(geo_valida=geo_ok.astype("int8"))
    reg.anular(d["lat"].notna() & ~geo_ok, ["lat", "lon"], "geo_fuera_de_bbox",
               f"lat {config.BBOX_LAT} lon {config.BBOX_LON}")

    d = reg.df
    reg.anular(d["ano_construccion"].notna()
               & ~d["ano_construccion"].between(*config.ANIO_CONSTRUCCION_VALIDO),
               ["ano_construccion"], "ano_construccion_rango",
               f"{config.ANIO_CONSTRUCCION_VALIDO}")

    # dormitorios = 0 es valido en departamento (monoambiente); banos = 0 no
    # existe fisicamente. El dataset trae 30 dormitorios y 34 banos.
    d = reg.df
    fuera = pd.Series(False, index=d.index)
    for t in tipos:
        u = config.UMBRALES[(operacion, t)]
        es_t = d["tipo"] == t
        fuera |= es_t & d["dormitorios"].notna() & ~d["dormitorios"].between(*u.dormitorios)
        fuera |= es_t & d["banos"].notna() & ~d["banos"].between(*u.banos)
    reg.anular(fuera, ["dormitorios", "banos"], "dormitorios_banos_rango",
               "fuera del rango del segmento")

    # Algunos avisos informan los estacionamientos y bodegas del EDIFICIO en vez
    # de los de la unidad: hay estudios de 29 m2 con 540 estacionamientos. Se
    # anula el campo (la fila es valida) y el flag tiene_* queda en 0, que es
    # menos danino que dejar el numero: el modelo lo leia como caracteristica cara.
    d = reg.df
    fuera = pd.Series(False, index=d.index)
    for t in tipos:
        u = config.UMBRALES[(operacion, t)]
        es_t = d["tipo"] == t
        fuera |= es_t & d["estacionamientos"].notna() & ~d["estacionamientos"].between(*u.estacionamientos)
        fuera |= es_t & d["bodegas"].notna() & ~d["bodegas"].between(*u.bodegas)
    reg.anular(fuera, ["estacionamientos", "bodegas"], "estac_bodegas_del_edificio",
               "conteo del edificio, no de la unidad")

    # gastos_comunes = 0 significa cosas distintas segun el tipo: en casa es cero
    # real (53,6% de las casas), en departamento es "no informado" (solo 6,2%).
    d = reg.df
    gc_sospechoso = ((d["tipo"] == "departamento") & (d["gastos_comunes_clp"] == 0)) \
        | (d["gastos_comunes_clp"] > config.GASTOS_COMUNES_MAX)
    reg.anular(gc_sospechoso, ["gastos_comunes_clp"], "gastos_comunes_ambiguos",
               "0 en depto (no informado) o > 3.000.000")

    # Misma propiedad publicada dos veces (misma direccion, m2 y precio).
    # Al desempatar se prefiere el precio original del scraper por sobre uno
    # reconstruido, y solo despues la captura mas reciente: las filas del
    # 27/07 son justamente las que perdieron un precio por el fallo de la UF.
    d = reg.df.copy()
    d["_dir"] = d["direccion"].map(normalizar_texto)
    con_dir = d["_dir"] != ""
    d["_reconstruido"] = (d["precio_origen"] != "scraper").astype("int8")
    orden = d.sort_values(["_reconstruido", "fecha_scrape"], ascending=[True, False])
    duplicada = orden.duplicated(subset=["_dir", "m2_util", target], keep="first") \
        & con_dir.reindex(orden.index)
    reg.eliminar(~duplicada.reindex(reg.df.index, fill_value=False),
                 "duplicados_duros", "(direccion, m2_util, precio) repetido")

    # Recorte estadistico final sobre precio/m2 dentro de (comuna, tipo).
    # En venta el uf_por_m2 va de 0,078 a 24.780 con p1=20,7 y p99=138: la cola
    # es ruido de captura, no mercado. Usa el target, asi que es una decision de
    # definicion de poblacion; se controla con --sin-recorte-final.
    if con_recorte_final:
        d = reg.df.copy()
        d["_precio_m2"] = d[target] / d["m2_util"]
        reg.df = d
        bajo, alto = config.RECORTE_PERCENTILES
        reg.eliminar(_recorte_por_grupo(d, "_precio_m2"), "recorte_precio_m2",
                     f"p{bajo}-p{alto} de precio/m2 en (comuna, tipo)")

    return reg.df.drop(columns=["_dir", "_precio_m2", "_reconstruido"],
                       errors="ignore"), reg.pasos


def cargar_segmento(operacion: str, tipo: str = "todos", *,
                    db_path: Path | str = config.DB_PATH,
                    uf_online: bool = False,
                    con_recorte_final: bool = True) -> tuple[pd.DataFrame, InformeCarga]:
    """Pipeline completo: carga -> faltantes -> casteo -> reparacion -> filtros."""
    if operacion not in config.OPERACIONES:
        raise ValueError(f"operacion invalida: {operacion}")

    crudo = cargar_crudo(db_path)
    n_crudas = len(crudo)
    df = castear_tipos(a_faltantes(crudo))
    df = df.drop(columns=["publica"], errors="ignore")   # 100% vacia en las 15.808 filas

    uf, procedencia = uf_referencia(df, online=uf_online)
    df, rep = reparar_precios(df, uf)
    rep.procedencia = procedencia

    df, pasos = aplicar_filtros(df, operacion, tipo, con_recorte_final=con_recorte_final)

    informe = InformeCarga(operacion=operacion, tipo=tipo, filas_crudas=n_crudas,
                           filas_finales=len(df), reparacion=rep, pasos=pasos)
    return df.reset_index(drop=True), informe
