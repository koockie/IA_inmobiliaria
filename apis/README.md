
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
