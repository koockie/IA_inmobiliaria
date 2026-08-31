# API de análisis de inversión inmobiliaria

Servicio HTTP que envuelve los dos modelos entrenados (`modelos/venta.joblib` y
`modelos/arriendo.joblib`) y añade la capa de decisión de inversión.

## Correr en local

```bash
./.venv/Scripts/python.exe -m uvicorn api.main:app --reload
```

Documentación interactiva en `http://127.0.0.1:8000/docs`.

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/salud` | Carga los dos modelos y devuelve sus métricas. Es el health check. |
| `GET` | `/modelos/{venta\|arriendo}` | La ficha completa: métricas, variables y sesgos declarados. |
| `POST` | `/estimar` | Precio de venta y arriendo esperados, con rango y confianza. |
| `POST` | `/analizar` | El informe completo, incluido el análisis de inversión. |

```bash
curl -s localhost:8000/analizar -H 'content-type: application/json' -d '{
  "propiedad": {"m2_util": 82, "m2_total": 91, "tipo": "departamento",
                "comuna": "nunoa", "dormitorios": 2, "banos": 2,
                "estacionamientos": 1, "ano_construccion": 2009,
                "lat": -33.4569, "lon": -70.6011},
  "precio_pedido_uf": 6402}'
```

## Estructura

```
api/features.py    construccion de variables — UNICA definicion, compartida con los notebooks
api/modelos.py     carga de los .joblib, estimacion con rango coherente y confianza
api/inversion.py   dividendo, flujo, VAN/TIR, plusvalia requerida y simulacion
api/informe.py     render del analisis a HTML
api/main.py        endpoints
```

`features.py` es la pieza delicada: define las variables que esperan los modelos
ya entrenados. **Cambiarla invalida los `.joblib`.** Si se toca, hay que
reentrenar y volver a correr el QA, que compara este módulo contra los notebooks
celda a celda.

## Desplegar en DigitalOcean

### Opción A — App Platform desde el repositorio

```bash
doctl apps create --spec .do/app.yaml
```

**Antes hay que resolver los artefactos.** `modelos/*.joblib` está en
`.gitignore`, así que un build desde GitHub no los tendría. Dos caminos:

- Sacar esa línea del `.gitignore` y commitear los dos archivos. Pesan ~10 MB
  entre ambos, muy por debajo del límite de GitHub, y mantiene el artefacto
  versionado junto al código que lo produjo. **Es lo recomendado.**
- Subirlos a un Space y bajarlos en el build, añadiendo el paso al `Dockerfile`.
  Solo compensa cuando los modelos crezcan.

### Opción B — contenedor

```bash
docker build -t inmobiliaria-api .
docker run -p 8080:8080 inmobiliaria-api
```

El `Dockerfile` instala `libgomp1` a propósito: XGBoost lo necesita para OpenMP
y sin él el `import` falla en tiempo de ejecución, no en el build.

### Tamaño de instancia

`basic-xxs` (512 MB) alcanza: los modelos ocupan ~10 MB en disco y el proceso se
estabiliza bajo 400 MB con pandas y xgboost cargados. La primera petición paga
la carga de los `.joblib`; el health check con `initial_delay_seconds: 40` está
puesto para eso.

### Versiones ancladas

`requirements.txt` fija las versiones exactas. Un `.joblib` de scikit-learn solo
garantiza cargar con la versión con la que se serializó: subir `scikit-learn` o
`xgboost` sin reentrenar puede romper la carga o, peor, cargarla y predecir
distinto.

## Antes de cada despliegue

```bash
./.venv/Scripts/python.exe qa/qa_modelos.py
./.venv/Scripts/python.exe qa/qa_inversion.py
```

El primero reproduce ambos notebooks, comprueba que los `.joblib` devuelven las
métricas de su ficha, verifica que no hay fugas y prueba la API de punta a
punta. El segundo verifica la aritmética financiera contra valores conocidos.
Los dos devuelven código de salida distinto de cero si algo falla.
