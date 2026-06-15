"""Nodo extract: extrae los datos de la propiedad y geocodifica la dirección."""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.state import GraphState, PropertyInput
from app.tools.geocoding import geocode

SYSTEM = (
    "Extrae los datos de la oferta inmobiliaria mencionada por el usuario. Si falta un "
    "dato, déjalo nulo. La dirección es lo más importante para ubicar la propiedad."
)


def _last_user_text(state: GraphState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return msg.content
        if isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def extract(state: GraphState) -> dict:
    text = _last_user_text(state)
    llm = get_llm(temperature=0).with_structured_output(PropertyInput)
    prop: PropertyInput = llm.invoke(
        [SystemMessage(content=SYSTEM), HumanMessage(content=text)]
    )

    geo = geocode(prop.direccion, prop.comuna)
    return {"property": prop.model_dump(), "geo": geo}
