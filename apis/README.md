# Descubrimiento de APIs 🔍

Scripts simples y autocontenidos para **ver qué devuelve cada API** que usamos en el POC.
Cada uno: llama a la API con parámetros hardcodeados, imprime un resumen por consola y guarda
la respuesta **completa** en `apis/outputs/<api>.json`.

| # | Script | API | ¿Key? | Para qué sirve |
|---|--------|-----|-------|----------------|
| 3 | `03_tavily_search.py` | Tavily | Sí (.env) | Búsqueda web: proyectos, plan regulador, noticias del sector |
| 4 | `04_groq_llm.py` | Groq | Sí (.env) | LLM gratis (compatible con OpenAI) |
| 5 | `05_mindicador_uf.py` | mindicador.cl | No | UF/UTM/dólar (cuantitativo, bonus) |
| 6 | `06_cead_delincuencia.py` | CEAD (CSV) | No | Estado del dataset comunal de delincuencia |
| 7 | `07_google_places.py` | Google Maps | Sí (.env) | Geocoding + lugares cercanos (reemplaza a OSM) |
| 8 | `08_censo_manzana.py` | INE Censo 2024 | No | Contexto socioeconómico a nivel manzana (ArcGIS) |

> Los scripts `01_nominatim` y `02_overpass` (OpenStreetMap) se movieron a `apis/legacy/`
> porque se reemplazaron por Google Maps (#7).

## Cómo correrlos

```powershell
# desde la raíz del proyecto, con el venv:
.\.venv\Scripts\python.exe apis\07_google_places.py
.\.venv\Scripts\python.exe apis\08_censo_manzana.py
.\.venv\Scripts\python.exe apis\03_tavily_search.py
.\.venv\Scripts\python.exe apis\04_groq_llm.py
.\.venv\Scripts\python.exe apis\05_mindicador_uf.py
.\.venv\Scripts\python.exe apis\06_cead_delincuencia.py
```

Las que necesitan key (Google, Tavily, Groq) la leen desde `.env` — **no se hardcodea en el script**.
Las respuestas crudas quedan en `apis/outputs/` para revisarlas con calma.

## Requisitos de keys

- **Google Maps** (#7): usa Geocoding **v4** + Places **(New)**. La **Demo Key** de Google
  los soporta sin billing (sirve para el POC). Poner `GOOGLE_MAPS_API_KEY` en `.env`.
- **Censo manzana** (#8): confirmar la URL de la capa en geoine-ine-chile.opendata.arcgis.com
  y ponerla en `INE_ARCGIS_LAYER_URL` (.env).
