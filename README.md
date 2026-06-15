# Inmobiliaria POC — Flujo de agentes (LangGraph)

POC del MVP de recomendación de inversión inmobiliaria. Dos capacidades:

1. **Agente conversacional**: saluda y explica para qué sirve.
2. **Agente cualitativo**: dada una dirección, enriquece el análisis con el entorno
   (colegios, locomoción, supermercados, áreas verdes, salud), desarrollo urbano futuro
   (búsqueda web) y contexto de seguridad comunal — con disclaimers.

## Arquitectura

```
router ─(chat)──▶ conversational ─▶ END
       └(analyze)▶ extract+geocode ─▶ fan-out paralelo:
                       ├─ fetch_pois (Overpass/OSM)        ┐
                       ├─ fetch_crime (CEAD, dataset)      ┤─▶ synthesizer ─▶ END
                       └─ query_planner ▶ tavily_researcher┘
```

- **Rama estructurada** (POIs, delincuencia): determinista, sin LLM.
- **Rama de investigación** (proyectos/plan regulador): patrón planner → researcher con Tavily.

## Setup local (gratis)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # luego edita .env
```

En `.env` (todo de tiers gratis):
- `LLM_PROVIDER=groq`, `LLM_MODEL=llama-3.3-70b-versatile`
- `GROQ_API_KEY=...`  (https://console.groq.com)
- `TAVILY_API_KEY=...`  (https://app.tavily.com)
- `NOMINATIM_USER_AGENT=inmobiliaria-poc/0.1 (tu-correo)`

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

## Despliegue en DigitalOcean

`docker build` con el `Dockerfile` incluido. En App Platform define las variables de
entorno con `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`, `OPENAI_API_KEY`,
`TAVILY_API_KEY`, `NOMINATIM_USER_AGENT`. Cambiar de Groq a GPT es solo cambiar variables.

## Notas

- `app/data/crime_by_comuna.csv` es **dataset de ejemplo**. Reemplazar por la descarga
  oficial de [CEAD](https://cead.spd.gov.cl).
- Nominatim/Overpass son gratis pero con rate limits; para producción conviene cachear o
  migrar a un geocoder de pago.
- Ideas de variables **cuantitativas** (cap rate, plusvalía, sobreoferta, UF) y sus fuentes
  chilenas están documentadas en el plan del proyecto para coordinar con el equipo.
```
