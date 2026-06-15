# Descubrimiento de APIs 🔍

Scripts simples y autocontenidos para **ver qué devuelve cada API** que usamos en el POC.
Cada uno: llama a la API con parámetros hardcodeados, imprime un resumen por consola y guarda
la respuesta **completa** en `apis/outputs/<api>.json`.

| # | Script | API | ¿Key? | Para qué sirve |
|---|--------|-----|-------|----------------|
| 1 | `01_nominatim_geocoding.py` | Nominatim (OSM) | No | Dirección → lat/lon + comuna |
| 2 | `02_overpass_pois.py` | Overpass (OSM) | No | POIs cercanos (colegios, metro, etc.) |
| 3 | `03_tavily_search.py` | Tavily | Sí (.env) | Búsqueda web para proyectos/plan regulador |
| 4 | `04_groq_llm.py` | Groq | Sí (.env) | LLM gratis (compatible con OpenAI) |
| 5 | `05_mindicador_uf.py` | mindicador.cl | No | UF/UTM/dólar (cuantitativo, bonus) |

## Cómo correrlos

```powershell
# desde la raíz del proyecto, con el venv:
.\.venv\Scripts\python.exe apis\01_nominatim_geocoding.py
.\.venv\Scripts\python.exe apis\02_overpass_pois.py
.\.venv\Scripts\python.exe apis\03_tavily_search.py
.\.venv\Scripts\python.exe apis\04_groq_llm.py
.\.venv\Scripts\python.exe apis\05_mindicador_uf.py
```

Las que necesitan key (Tavily, Groq) la leen desde `.env` — **no se hardcodea en el script**.
Las respuestas crudas quedan en `apis/outputs/` para revisarlas con calma.
