"""Nodo conversacional básico: saluda y explica para qué sirve el asistente."""
from __future__ import annotations

from langchain_core.messages import SystemMessage

from app.config import get_llm
from app.state import GraphState

SYSTEM = (
    "Eres un asistente que ayuda a personas SIN conocimiento técnico a evaluar "
    "oportunidades de inversión inmobiliaria en Chile. Preséntate de forma breve y "
    "cordial. Explica que puedes enriquecer el análisis de una propiedad con factores "
    "cualitativos del entorno: cercanía a colegios, locomoción, supermercados, áreas "
    "verdes y salud; proyectos/desarrollo urbano futuro de la zona; y contexto de "
    "seguridad de la comuna. Pide la dirección o comuna de la propiedad para analizar. "
    "No inventes datos ni des cifras de rentabilidad aquí. Responde en español, claro y corto."
)


def conversational(state: GraphState) -> dict:
    llm = get_llm(temperature=0.4)
    messages = [SystemMessage(content=SYSTEM), *state.get("messages", [])]
    response = llm.invoke(messages)
    return {"messages": [response]}
