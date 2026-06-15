"""Nodo analista: redacta el informe cualitativo final a partir de todo el estado."""
from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import get_llm
from app.state import GraphState


class QualitativeReport(BaseModel):
    resumen_ubicacion: str = Field(description="Dónde está la propiedad y su entorno general")
    factores_a_favor: list[str] = Field(description="Aspectos positivos para la inversión")
    factores_de_atencion: list[str] = Field(description="Aspectos a considerar o de riesgo")
    contexto_seguridad: str = Field(description="Lectura neutral del dato delictual comunal")
    disclaimers: list[str] = Field(description="Advertencias y límites del análisis")
    narrativa: str = Field(description="Resumen conversacional para mostrar al usuario")


SYSTEM = (
    "Eres un analista de inversión inmobiliaria en Chile. Redactas un análisis CUALITATIVO "
    "del entorno de una propiedad para complementar (no reemplazar) el análisis numérico. "
    "Usa SOLO los datos provistos; no inventes cifras ni proyectos. Si un dato falta, dilo. "
    "Sobre seguridad: usa lenguaje neutral y factual, sin estigmatizar, y deja claro que es "
    "referencial a nivel comunal. Cita fuentes (URLs) cuando uses hallazgos de búsqueda web. "
    "Responde en español, claro y útil para alguien sin conocimiento técnico."
)


def _build_context(state: GraphState) -> str:
    payload = {
        "propiedad": state.get("property"),
        "ubicacion": state.get("geo"),
        "puntos_de_interes": state.get("pois"),
        "seguridad_comunal": state.get("crime"),
        "investigacion_web": state.get("research"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def synthesizer(state: GraphState) -> dict:
    if not state.get("geo"):
        msg = (
            "No pude ubicar la dirección entregada, así que no fue posible analizar el "
            "entorno. ¿Puedes darme una dirección o comuna más precisa?"
        )
        return {"report": {"error": "geocoding_failed", "narrativa": msg},
                "messages": [AIMessage(content=msg)]}

    context = _build_context(state)
    llm = get_llm(temperature=0.3).with_structured_output(QualitativeReport)
    report: QualitativeReport = llm.invoke(
        [
            SystemMessage(content=SYSTEM),
            HumanMessage(content=f"Datos recopilados:\n{context}"),
        ]
    )
    return {
        "report": report.model_dump(),
        "messages": [AIMessage(content=report.narrativa)],
    }
