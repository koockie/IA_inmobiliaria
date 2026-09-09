# Modelos de tasación inmobiliaria — Macul, La Florida, Ñuñoa y San Miguel

Dos modelos entrenados que estiman, a partir de los atributos de una propiedad:

- **precio de venta** en UF
- **arriendo mensual** en CLP

Se consumen por HTTP. Clonar la rama y levantar el servicio son cuatro comandos:
los modelos ya entrenados vienen versionados en `modelos/`, así que **no hace
falta reentrenar nada**.

```bash
git clone -b modeloML <url-del-repo> inmobiliaria
cd inmobiliaria
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn api.main:app --reload
```

En Linux o macOS, `.venv/bin/pip` y `.venv/bin/python`. **Requiere Python 3.14**:
los `.joblib` se serializaron con scikit-learn 1.9 sobre esa versión, y cargarlos
con otra combinación puede fallar o, peor, predecir distinto sin avisar.

Queda en `http://127.0.0.1:8000`, con documentación interactiva en `/docs` desde
donde se puede probar sin escribir una sola línea de `curl`.

## Comprobar que quedó bien

```bash
curl -s localhost:8000/salud
```

```json
{
  "estado": "ok",
  "modelos": {
    "venta":    { "mdape_pct": 8.775, "n_features": 33 },
    "arriendo": { "mdape_pct": 7.75,  "n_features": 35 }
  },
  "uf_referencia": 40844.79,
  "comunas_cubiertas": ["la-florida", "macul", "nunoa", "san-miguel"]
}
```

Si responde 500 con un `FileNotFoundError`, faltan los `.joblib` en `modelos/`.

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/salud` | Carga los dos modelos y devuelve sus métricas. Sirve de health check. |
| `GET` | `/modelos/venta` · `/modelos/arriendo` | La ficha completa: métricas, variables y sesgos declarados. |
| `POST` | `/estimar` | Las dos estimaciones para una propiedad. |

### POST /estimar

De todos los atributos **solo `m2_util` es obligatorio**. Lo que falte se trata
como faltante —que no es lo mismo que cero— y baja el nivel de confianza que
devuelve la respuesta.

```bash
curl -s localhost:8000/estimar -H "content-type: application/json" -d "{
  \"propiedad\": {
    \"m2_util\": 60, \"m2_total\": 68,
    \"tipo\": \"departamento\", \"comuna\": \"nunoa\",
    \"dormitorios\": 2, \"banos\": 2,
    \"estacionamientos\": 1, \"bodegas\": 1,
    \"ano_construccion\": 2015, \"gastos_comunes_clp\": 120000,
    \"lat\": -33.4569, \"lon\": -70.6011
  },
  \"precio_pedido_uf\": 5200
}"
```

Respuesta real de esa petición:

```json
{
  "venta": {
    "valor": 5287.37,
    "unidad": "UF",
    "rango": [4368.91, 5834.64],
    "confianza": "alta",
    "motivos_menor_confianza": [],
    "error_tipico_pct": 8.8,
    "cobertura_rango_pct": 80.0
  },
  "arriendo": {
    "valor": 800708.44,
    "unidad": "CLP",
    "valor_uf": 19.6,
    "rango": [594928.47, 802383.54],
    "confianza": "media",
    "motivos_menor_confianza": [
      "barrio inédito: sin avisos de entrenamiento a menos de ~110 m"
    ],
    "error_tipico_pct": 7.8,
    "cobertura_rango_pct": 80.0
  },
  "juicio_de_precio": {
    "precio_pedido_uf": 5200.0,
    "brecha_pct": -1.7,
    "errores_tipicos": -0.19,
    "veredicto": "EN PRECIO",
    "detalle": "dentro del rango de mercado",
    "dentro_del_rango": true
  },
  "advertencias": ["..."]
}
```

`precio_pedido_uf` es opcional. Si se envía, aparece `juicio_de_precio`; si no, la
respuesta trae solo las dos estimaciones.

### Los campos de entrada

| Campo | Tipo | Notas |
|---|---|---|
| `m2_util` | número | **Obligatorio.** Superficie interior, sin terraza. |
| `tipo` | texto | `departamento` (por defecto) o `casa`. |
| `comuna` | texto | `nunoa`, `macul`, `la-florida`, `san-miguel`. Se normaliza sola: «Ñuñoa» también funciona. |
| `m2_total`, `dormitorios`, `banos` | número | Opcionales. |
| `estacionamientos`, `bodegas` | número | Opcionales. Omitir no es lo mismo que enviar `0`. |
| `ano_construccion` | número | El año, no la antigüedad. |
| `gastos_comunes_clp` | número | Solo departamentos. |
| `lat`, `lon` | número | Opcionales pero recomendados: la latitud es la tercera variable más influyente. |
| `servicios_cercanos` | objeto o texto | Opcional. El JSON de Google Places. Sin él se pierde el bloque de vecindario: un 5 % de la importancia en venta y un 10 % en arriendo. |

## Consumirlo desde otro backend

```python
import httpx

def tasar(propiedad: dict, precio_pedido_uf: float | None = None) -> dict:
    cuerpo = {"propiedad": propiedad}
    if precio_pedido_uf is not None:
        cuerpo["precio_pedido_uf"] = precio_pedido_uf
    r = httpx.post("http://127.0.0.1:8000/estimar", json=cuerpo, timeout=30)
    r.raise_for_status()
    return r.json()
```

La primera petición paga la carga de los `.joblib` (un par de segundos); después
quedan cacheados en el proceso y cada estimación es de milisegundos.

## Cómo leer la respuesta

**`valor`** es la estimación puntual. **`rango`** contiene el valor real cerca del
80 % de las veces: está calibrado sobre propiedades que el modelo nunca vio, no es
un ±10 % puesto a ojo.

**`error_tipico_pct`** es el error del *segmento* al que pertenece la propiedad, no
el global. Sube a 11,8 % en casas y a 9,9 % en avisos sin coordenadas.

**`confianza`** vale `alta`, `media` o `baja`, y `motivos_menor_confianza` explica
por qué bajó. Se degrada si es casa, si faltan coordenadas, si el barrio no aparece
en el entrenamiento o si la comuna está fuera de cobertura.

**`errores_tipicos`** es el campo que manda dentro de `juicio_de_precio`: la brecha
medida en errores típicos del modelo. Si el modelo falla un 8,8 % de forma
habitual, una diferencia del 5 % no significa nada. Los cortes son ±1 y ±2 errores
típicos, no números redondos.

## Qué tan bueno es cada modelo

Medido sobre el 20 % de prueba, con edificios que el modelo nunca vio. Las
referencias son las del estándar IAAO de tasación masiva.

| | Venta | Arriendo | Referencia |
|---|---|---|---|
| MdAPE | 8,78 % | 7,75 % | < 10 % excelente |
| PPE10 | 55,4 % | 59,9 % | > 50 % |
| COD | 12,2 | 11,6 | 5 – 15 |
| PRD | 1,029 | 1,032 | 0,98 – 1,03 |
| Cobertura del rango | 78,7 % | 81,2 % | 80 % |
| Algoritmo | hist_gradient | xgboost | |
| Avisos usados | 9.812 | 5.662 | |

La ficha completa de cada uno —con la comparación de los cinco algoritmos
candidatos y los sesgos declarados— está en `modelos/venta.json` y
`modelos/arriendo.json`, y se sirve en `GET /modelos/{nombre}`.

## Límites que conviene declarar aguas arriba

- **Son precios pedidos, no de cierre.** En Chile el cierre suele quedar entre un
  5 % y un 15 % por debajo. El modelo estima «precio pedido esperado».
- **Cobertura geográfica**: solo esas cuatro comunas.
- **Casi no hay casas en arriendo**: 200 contra 5.462 departamentos. Sus
  estimaciones salen marcadas de confianza baja.
- **No estima plusvalía.** El dataset es una foto de 15 días de avisos publicados.

## Docker

```bash
docker build -t inmobiliaria-api .
docker run -p 8080:8080 inmobiliaria-api
```

El `Dockerfile` instala `libgomp1` a propósito: XGBoost lo necesita para OpenMP y
sin él el `import` falla en ejecución, no en el build. Para DigitalOcean App
Platform el spec está en `.do/app.yaml`; `basic-xxs` alcanza.

## Reentrenar

Solo si cambian los datos. La base viene en el repositorio, así que basta ejecutar
los dos notebooks: cada uno reescribe su `.joblib` y su `.json`. La semilla está
fijada, así que las métricas salen idénticas.

```
clustering.ipynb           diagnostico previo: ¿sirve la base? (no produce artefactos)
servicios_cercanos.ipynb   construye la columna servicios_cercanos (la cache ya viene)
modelo_venta.ipynb         entrena y guarda modelos/venta.joblib + venta.json
modelo_arriendo.ipynb      entrena y guarda modelos/arriendo.joblib + arriendo.json
```

Los dos notebooks de modelo terminan con una celda **PROBAR UNA PROPIEDAD A MANO**
donde se pegan los datos de un aviso y se obtiene la estimación sin levantar la API.

Antes de desplegar:

```bash
.venv\Scripts\python qa\qa_modelos.py
```

Reproduce la preparación de datos de ambos notebooks, recarga los `.joblib` y
verifica que devuelven las métricas de su ficha, que no hay fugas y que la API
responde. Devuelve código de salida distinto de cero si algo falla.

## Estructura

```
api/features.py    construccion de variables — UNICA definicion, compartida con los notebooks
api/modelos.py     carga de los .joblib, estimacion con rango y confianza
api/main.py        los tres endpoints
modelos/           los dos modelos entrenados y sus fichas
data/              la base de avisos y la cache de Google Places
qa/qa_modelos.py   auditoria de extremo a extremo
```

`api/features.py` es la pieza delicada: define las variables que esperan los
modelos ya entrenados. **Cambiarla invalida los `.joblib`.** Si se toca hay que
reentrenar y volver a correr el QA, que la compara contra los notebooks celda a
celda.
