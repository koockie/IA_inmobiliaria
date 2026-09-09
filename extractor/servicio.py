"""El flujo completo, en una funcion. Es lo que despues envolvera la API.

    URL -> validar -> descargar -> parsear -> validar campos -> guardar

Nunca lanza por un problema del portal: los fallos vienen como resultado con
motivo legible, para que el backend pueda mostrarselo al usuario tal cual.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import storage
from .fetch import Estado, descargar
from .parse import extraer
from .urls import UrlInvalida, analizar
from .validate import construir

_MENSAJES = {
    Estado.BLOQUEADO: "El portal esta rechazando las consultas en este momento. "
                      "Intentalo de nuevo en unos minutos.",
    Estado.CHALLENGE: "El portal pidio verificacion humana para esta ficha. "
                      "Intentalo de nuevo mas tarde.",
    Estado.NO_EXISTE: "Ese aviso ya no existe o fue dado de baja.",
    Estado.RED: "No se pudo conectar con el portal.",
    Estado.ERROR_HTTP: "El portal respondio de forma inesperada.",
}


@dataclass
class Resultado:
    ok: bool
    registro: dict | None = None
    error: str | None = None
    estado: str | None = None
    desde_cache: bool = False
    advertencias: list[str] = field(default_factory=list)

    def a_dict(self) -> dict:
        return {"ok": self.ok, "estado": self.estado, "error": self.error,
                "desde_cache": self.desde_cache, "registro": self.registro,
                "advertencias": self.advertencias}


def obtener(url: str, *, guardar: bool = True, usar_cache: bool = True,
            db: Path | None = None) -> Resultado:
    """Un aviso, desde su URL. Una sola peticion al portal, sin rastreo."""
    try:
        aviso = analizar(url)
    except UrlInvalida as e:
        return Resultado(False, error=str(e), estado="url_invalida")

    resp = descargar(aviso.url, aviso.id_aviso, usar_cache=usar_cache)
    if not resp.ok:
        return Resultado(False, error=_MENSAJES.get(resp.estado, resp.motivo),
                         estado=resp.estado.value)

    registro = construir(aviso, extraer(resp.html or ""))

    if guardar:
        conn = storage.abrir(db)
        try:
            storage.guardar(conn, registro)
        finally:
            conn.close()

    return Resultado(True, registro=registro, estado="ok",
                     desde_cache=resp.desde_cache,
                     advertencias=registro.get("advertencias", []))
