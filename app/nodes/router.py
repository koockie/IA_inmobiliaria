"""Nodo router: clasifica si el usuario quiere conversar o analizar una propiedad."""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.state import GraphState, RouterDecision

SYSTEM = (
    "Eres un clasificador de intención para un asistente de inversión inmobiliaria. "
    "Decide si el último mensaje del usuario busca ANALIZAR una propiedad (trae una "
    "dirección, comuna o pide evaluar una oferta) o es solo conversación general "
    "(saludo, dudas, ayuda)."
)


def _last_user_text(state: GraphState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return msg.content
        # también soporta dicts {"role": "user", ...}
        if isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def router(state: GraphState) -> dict:
    text = _last_user_text(state)
    llm = get_llm(temperature=0).with_structured_output(RouterDecision)
    decision: RouterDecision = llm.invoke(
        [SystemMessage(content=SYSTEM), HumanMessage(content=text)]
    )
    return {"intent": decision.intent}


def route_intent(state: GraphState) -> str:
    """Edge condicional: nombre del siguiente nodo."""
    return "extract" if state.get("intent") == "analyze" else "conversational"
