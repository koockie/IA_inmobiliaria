"""Rama de investigación: el LLM genera 3-4 queries de búsqueda específicas."""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.state import GraphState, SearchPlan

SYSTEM = (
    "Genera entre 3 y 4 consultas de búsqueda web ESPECÍFICAS para evaluar el potencial "
    "de plusvalía y desarrollo del entorno de una propiedad en Chile. Enfócate en: "
    "nuevos proyectos inmobiliarios/condominios, permisos de edificación, plan regulador "
    "y obras de conectividad o infraestructura de la comuna. Incluye el nombre de la "
    "comuna y, si aporta, el año actual. No incluyas consultas sobre delincuencia."
)


def query_planner(state: GraphState) -> dict:
    geo = state.get("geo") or {}
    prop = state.get("property") or {}
    comuna = geo.get("comuna") or prop.get("comuna") or ""
    direccion = prop.get("direccion") or geo.get("display_name") or ""

    if not comuna and not direccion:
        return {"search_queries": []}

    user = f"Dirección: {direccion}\nComuna: {comuna}"
    llm = get_llm(temperature=0.3).with_structured_output(SearchPlan)
    plan: SearchPlan = llm.invoke(
        [SystemMessage(content=SYSTEM), HumanMessage(content=user)]
    )
    return {"search_queries": plan.queries[:4]}
