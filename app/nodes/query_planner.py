"""Rama de investigación: el LLM genera 3-4 queries de búsqueda específicas."""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.state import GraphState, SearchPlan

SYSTEM = (
    "Genera entre 3 y 4 consultas de búsqueda web ESPECÍFICAS para profundizar en el "
    "entorno de una propiedad en Chile, mezclando dos niveles:\n"
    "1) COMUNA: nuevos proyectos inmobiliarios/condominios, permisos de edificación, plan "
    "regulador, obras de conectividad o infraestructura.\n"
    "2) BARRIO/SECTOR (más fino que la comuna): usa el nombre del barrio, villa o calle "
    "principal si está disponible para buscar desarrollo del sector y también noticias "
    "recientes de seguridad o incidentes del sector.\n"
    "Incluye el nombre de la comuna y, si aporta, el barrio y el año actual. Las consultas "
    "de seguridad son para CONTEXTO noticioso del sector; el dato oficial de delincuencia "
    "viene aparte (CEAD), así que no las plantees como cifras definitivas."
)


def query_planner(state: GraphState) -> dict:
    geo = state.get("geo") or {}
    prop = state.get("property") or {}
    comuna = geo.get("comuna") or prop.get("comuna") or ""
    direccion = prop.get("direccion") or geo.get("display_name") or ""

    if not comuna and not direccion:
        return {"search_queries": []}

    display = geo.get("display_name") or ""
    user = f"Dirección: {direccion}\nComuna: {comuna}\nUbicación completa: {display}"
    llm = get_llm(temperature=0.3).with_structured_output(SearchPlan)
    plan: SearchPlan = llm.invoke(
        [SystemMessage(content=SYSTEM), HumanMessage(content=user)]
    )
    return {"search_queries": plan.queries[:4]}
