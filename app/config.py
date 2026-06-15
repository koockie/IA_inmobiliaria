"""Configuración central y factory de LLM agnóstico de proveedor.

La idea: los nodos del grafo NUNCA importan un proveedor concreto. Piden un LLM con
`get_llm()` y, según `LLM_PROVIDER`, se entrega Groq (gratis, local) u OpenAI (producción
en DigitalOcean). Cambiar de proveedor es solo cambiar variables de entorno.
"""
from __future__ import annotations

from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM
    llm_provider: str = "groq"          # "groq" (local/gratis) | "openai" (prod)
    llm_model: str = "llama-3.3-70b-versatile"
    groq_api_key: str | None = None
    openai_api_key: str | None = None

    # Búsqueda web
    tavily_api_key: str | None = None

    # Geocoding
    nominatim_user_agent: str = "inmobiliaria-poc/0.1"

    # Parámetros
    poi_radius_m: int = 1000
    enable_crime: bool = True

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_llm(temperature: float = 0.2, model: str | None = None) -> BaseChatModel:
    """Devuelve un chat model configurado según el proveedor activo.

    `model` permite sobrescribir el modelo por nodo (p. ej. uno barato para el router
    y uno más capaz para el synthesizer). Si es None usa `LLM_MODEL`.
    """
    settings = get_settings()
    return init_chat_model(
        model or settings.llm_model,
        model_provider=settings.llm_provider,
        temperature=temperature,
    )
