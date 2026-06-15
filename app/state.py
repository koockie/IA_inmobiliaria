"""Esquemas de estado del grafo y modelos estructurados de salida de los LLM."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


# ---- Salidas estructuradas de los LLM ----

class RouterDecision(BaseModel):
    """Clasificación de la intención del usuario."""
    intent: Literal["chat", "analyze"] = Field(
        description="'analyze' si el usuario quiere evaluar una propiedad/dirección; "
        "'chat' para saludos, preguntas generales o ayuda."
    )


class PropertyInput(BaseModel):
    """Datos de la oferta inmobiliaria extraídos del mensaje del usuario."""
    direccion: str = Field(description="Dirección o ubicación de la propiedad")
    comuna: Optional[str] = Field(default=None, description="Comuna, si se menciona")
    region: Optional[str] = Field(default=None, description="Región, si se menciona")
    tipo: Optional[str] = Field(
        default=None, description="Tipo: departamento, casa, terreno, etc."
    )
    precio_uf: Optional[float] = Field(default=None, description="Precio en UF, si se da")
    metros_cuadrados: Optional[float] = Field(default=None, description="m², si se da")


class SearchPlan(BaseModel):
    """Plan de búsquedas web que generará el query_planner."""
    queries: list[str] = Field(
        description="Entre 3 y 4 consultas de búsqueda específicas sobre desarrollo "
        "urbano, proyectos inmobiliarios, permisos de edificación y plan regulador."
    )


# ---- Estado del grafo ----

class GraphState(TypedDict, total=False):
    # Conversación
    messages: Annotated[list, add_messages]
    intent: str

    # Análisis de propiedad
    property: dict[str, Any]          # PropertyInput serializado
    geo: Optional[dict[str, Any]]     # {lat, lon, comuna, display_name} o None si falla
    pois: dict[str, Any]              # resultado rama POIs
    crime: dict[str, Any]             # resultado rama delincuencia
    search_queries: list[str]         # queries del planner
    research: list[dict[str, Any]]    # hallazgos de Tavily
    report: dict[str, Any]            # informe final del synthesizer
