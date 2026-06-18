# Inmobiliaria POC — Flujo de agentes (LangGraph)

POC del MVP de recomendación de inversión inmobiliaria. Dos capacidades:

1. **Agente conversacional**: saluda y explica para qué sirve.
2. **Agente cualitativo**: dada una dirección, enriquece el análisis con el entorno
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

> Ver `Arquitectura_deseada.md` para la arquitectura objetivo (backend cuantitativo separado del
> agente IA) y `evaluacion_agente_ia.md` para el marco de métricas de evaluación.

## Setup local (gratis)

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

## Despliegue en DigitalOcean

`docker build` con el `Dockerfile` incluido. En App Platform define las variables de
entorno con `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`, `OPENAI_API_KEY`,
`TAVILY_API_KEY`, `GOOGLE_MAPS_API_KEY` (y opcional `INE_ARCGIS_LAYER_URL`). Cambiar de Groq
a GPT es solo cambiar variables.

## Notas

- `app/data/crime_by_comuna.csv` es **dataset de ejemplo**. Reemplazar por la descarga
  oficial de CEAD (bajar el Excel y procesarlo con `app/tools/parse_cead_excel.py`).
- **Google Maps**: el código usa Geocoding **v4** y Places **(New)**, que la Demo Key soporta
  sin billing. Para producción/alto volumen conviene key con billing y restricciones. La caché
  (`lru_cache`) reduce llamadas repetidas en pruebas.
- **Censo manzana**: confirmar la URL del FeatureServer en geoine-ine-chile.opendata.arcgis.com
  y ponerla en `INE_ARCGIS_LAYER_URL`. Sin ella, el contexto de manzana queda "no disponible"
  sin romper el flujo.
- Ideas de variables **cuantitativas** (cap rate, plusvalía, sobreoferta, UF) y sus fuentes
  chilenas están en `variables_cuantitativas_mvp.docx` y en el plan del proyecto.
```
