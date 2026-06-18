"""Nodo analista: redacta el informe cualitativo final a partir de todo el estado."""
from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import get_llm
from app.state import GraphState


class QualitativeReport(BaseModel):
    resumen_ubicacion: str = Field(
        description="Dónde está la propiedad (dirección, comuna, barrio, región) y su entorno general"
    )
    detalle_entorno: list[str] = Field(
        description="Una línea por categoría de servicio con NÚMEROS CONCRETOS: cuántos hay dentro "
        "del radio, distancia al más cercano en metros y 2-3 ejemplos con su nombre. "
        "Cubre colegios, universidades, locomoción, abastecimiento, áreas verdes y salud."
    )
    contexto_sector: str = Field(
        description="Perfil socioeconómico del sector (Censo manzana) y noticias del barrio. "
        "Si el censo no fue consultado, dilo con precisión (no afirmes que no existen datos)."
    )
    factores_a_favor: list[str] = Field(description="Aspectos positivos para la inversión, concretos")
    factores_de_atencion: list[str] = Field(description="Aspectos a considerar o de riesgo, concretos")
    contexto_seguridad: str = Field(
        description="Lectura neutral del dato delictual comunal, indicando tasa, año, comparación "
        "con el promedio, Y la fuente con su enlace (CEAD)."
    )
    fuentes: list[str] = Field(
        description="Lista de fuentes usadas, cada una con su nombre y URL cuando exista "
        "(p. ej. 'Delincuencia: CEAD 2023 — https://...', 'Lugares: Google Places', etc.)"
    )
    disclaimers: list[str] = Field(description="Advertencias y límites del análisis")
    narrativa: str = Field(
        description="Resumen conversacional EXTENSO y detallado para el usuario (varios párrafos), "
        "integrando los números del entorno, el sector, la seguridad y las fuentes."
    )


SYSTEM = (
    "Eres un analista de inversión inmobiliaria en Chile. Redactas un análisis CUALITATIVO "
    "DETALLADO y EXTENSO del entorno de una propiedad, para complementar el análisis numérico.\n\n"
    "REGLAS:\n"
    "1. Usa SOLO los datos provistos; no inventes cifras, lugares ni proyectos.\n"
    "2. Sé CUANTITATIVO: cita números concretos de 'puntos_de_interes.categorias' — cuántos "
    "colegios/paraderos/supermercados/etc. hay, la distancia al más cercano (mas_cercano_m) y "
    "nombres de ejemplos. El conteo está topado en 20 por categoría (mencionarlo si llega a 20).\n"
    "3. NO confundas categorías: 'universidades' es distinto de 'colegios'; repórtalas por separado.\n"
    "4. CITA LAS FUENTES con su enlace: cada bloque de datos trae un campo 'fuente' con nombre y "
    "url. En seguridad indica SIEMPRE la fuente (CEAD), el año y el enlace.\n"
    "5. Sobre el sector (censo): si 'contexto_sector_censo_manzana.disponible' es false y el estado "
    "es 'no_configurado', di que la fuente del censo NO fue consultada todavía — NO digas que el "
    "censo no tiene datos. Si el estado es 'sin_cobertura', ahí sí di que no hay manzana censada.\n"
    "6. Seguridad: lenguaje neutral y factual, sin estigmatizar. Las noticias del barrio son "
    "contexto, no veredicto; cita su URL.\n"
    "7. Distingue dos niveles: SECTOR (manzana/barrio) y COMUNA (CEAD).\n"
    "Responde en español, claro y útil para alguien sin conocimiento técnico, con buen nivel de detalle."
)


def _build_context(state: GraphState) -> str:
    payload = {
        "propiedad": state.get("property"),
        "ubicacion": state.get("geo"),
        "puntos_de_interes": state.get("pois"),
        "contexto_sector_censo_manzana": state.get("census"),
        "seguridad_comunal_cead": state.get("crime"),
        "investigacion_web_y_noticias": state.get("research"),
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
