# Inmobiliaria POC — Flujo de agentes (LangGraph)


1. **Agente conversacional**: saluda y explica para qué sirve.
2. **Agente cualitativo**: dada una dirección,da el análisis con el entorno
   (colegios, locomoción, supermercados, áreas verdes, salud), contexto socioeconómico del
   sector (Censo manzana), desarrollo urbano futuro y noticias del barrio (búsqueda web) y
   contexto de seguridad comunal — con disclaimers.

## Arquitectura

```
router ─(chat)──▶ conversational ─▶ END
       └(analyze)▶ extract+geocode (Google) ─▶ fan-out paralelo:
                       ├─ fetch_pois (Google Places)        ┐
                       ├─ fetch_crime (CEAD comunal)        ┤
                       ├─ fetch_census (Censo 2024 manzana) ┤─▶ synthesizer ─▶ END
                       └─ query_planner ▶ tavily_researcher ┘
```

- **Rama estructurada** (POIs, delincuencia, censo): determinista, sin LLM.
- **Rama de investigación** (proyectos/plan regulador + noticias del sector): patrón planner →
  researcher con Tavily.


## Setup local 

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # luego edita .env
```

En `.env`:
- `LLM_PROVIDER=groq`, `LLM_MODEL=llama-3.3-70b-versatile` (Groq gratis)
- `GROQ_API_KEY=...`  (https://console.groq.com)
- `TAVILY_API_KEY=...`  (https://app.tavily.com — tier gratis)
- `GOOGLE_MAPS_API_KEY=...`  (Geocoding **v4** + Places **(New)**; la **Demo Key** los soporta sin billing)
- `INE_ARCGIS_LAYER_URL=`  (opcional; URL de la capa Manzana Censo 2024, ver `apis/08_censo_manzana.py`)

## Cómo probar

```bash
# CLI interactiva
python cli.py

# API
uvicorn api:api --reload
#   POST /chat     {"message": "hola"}
#   POST /analyze  {"direccion": "Av. Apoquindo 4000", "comuna": "Las Condes"}

# Tests (no requieren red ni LLM)
pytest -q
```

