"""API FastAPI para el flujo de agentes. Lista para desplegar en DigitalOcean.

Endpoints:
    POST /chat     -> {"message": "..."}  conversación o análisis (router decide)
    POST /analyze  -> {"direccion": "...", "comuna": "..."}  fuerza el análisis
    GET  /health   -> healthcheck
"""
from __future__ import annotations

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.graph import graph  # noqa: E402

api = FastAPI(title="Inmobiliaria POC - Agentes LangGraph", version="0.1.0")


class ChatRequest(BaseModel):
    message: str


class AnalyzeRequest(BaseModel):
    direccion: str
    comuna: str | None = None


def _last_ai(messages: list) -> str | None:
    ai = [m for m in messages if isinstance(m, AIMessage)]
    return ai[-1].content if ai else None


@api.get("/health")
def health() -> dict:
    return {"status": "ok"}


@api.post("/chat")
def chat(req: ChatRequest) -> dict:
    state = graph.invoke({"messages": [HumanMessage(content=req.message)]})
    return {
        "intent": state.get("intent"),
        "respuesta": _last_ai(state["messages"]),
        "report": state.get("report"),
    }


@api.post("/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    texto = f"Quiero analizar la propiedad en {req.direccion}"
    if req.comuna:
        texto += f", comuna {req.comuna}"
    state = graph.invoke({"messages": [HumanMessage(content=texto)]})
    return {
        "respuesta": _last_ai(state["messages"]),
        "ubicacion": state.get("geo"),
        "report": state.get("report"),
    }
