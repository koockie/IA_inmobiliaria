# Plan de desarrollo — Modelos ML de valoración inmobiliaria

> **Documento de traspaso.** Contiene todo el contexto necesario para desarrollar los modelos
> sin haber participado de las fases anteriores. Léelo completo antes de escribir código.
> Rol esperado: ingeniero de software / ML engineer.

---

## 1. Contexto del proyecto

Se está construyendo el MVP de una **plataforma que recomienda inversión inmobiliaria** a
personas sin conocimiento técnico, en 4 comunas de Santiago de Chile (Macul, La Florida, Ñuñoa,
San Miguel).

El sistema completo tiene tres capas. **Tu trabajo es la capa 1**:

| Capa | Qué hace | Estado |
|---|---|---|
| **1. ML (tu tarea)** | Estima precio de venta y arriendo de mercado a partir de los atributos | **A construir** |
| 2. Backend financiero | Dividendo, flujo de caja, TIR a 10 años, escenarios | Diseñado, no construido |
| 3. Agente LangGraph | Contexto cualitativo (seguridad, proyectos futuros) y redacción del informe | Existe en la rama `main` |

**Enfoque teórico: modelo hedónico ajustado con ML.** El precio de una vivienda se descompone en
la contribución de sus atributos (superficie, dormitorios, ubicación…). La regresión hedónica
clásica lo hace con coeficientes lineales; aquí se usa ML para capturar no linealidades e
interacciones, y SHAP para recuperar la interpretabilidad.

### Qué debe y qué NO debe hacer el modelo

Esto ya se analizó y es una decisión cerrada:

- ✅ **Estima el precio de mercado esperado** dadas las características.
- ❌ **NO predice "qué tan buena inversión es"**: esa etiqueta no existe en los datos (no hay
  retornos realizados ni precios de cierre). Cualquier intento sería inventar la variable objetivo.
- ❌ **NO predice plusvalía futura.** El dataset es una foto, no una serie temporal.

La salida del modelo alimenta tres indicadores que consume el resto del sistema:

1. **Brecha de precio** = precio pedido vs precio estimado (¿está caro o barato?)
2. **Renta esperada** = arriendo estimado → yield bruto
3. **Calidad de ubicación** = cuánto del precio explica la ubicación (vía SHAP)

---

## 2. Los datos

### Ubicación

```
Repositorio : C:\Users\marce\Desktop\inmobiliaria   (rama git: scrapping_PI_v0)
Dataset     : data/ofertas_unificado.sqlite   (tabla: ofertas)   ← USAR ESTE
Espejo CSV  : data/ofertas_unificado.csv
Entorno     : .venv\Scripts\python.exe   (Python 3.14)
```

Otros archivos en `data/` son versiones anteriores del pipeline de limpieza (respaldos). **No
los uses**: el vigente es `ofertas_unificado`.

### Volumen: 15.808 filas, 30 columnas

Origen: `pi` = PortalInmobiliario (14.462) · `cp` = ChilePropiedades (1.346), ambos scrapeados
por el equipo entre julio y agosto de 2026.

### Segmentos (define qué modelos son viables)

| Operación | Tipo | Filas | **Utilizables** (con target + m²) |
|---|---|---|---|
| venta | departamento | 6.849 | **6.355** |
| venta | casa | 3.124 | **2.393** |
| arriendo | departamento | 5.611 | **5.492** |
| arriendo | casa | 224 | **211** ⚠️ insuficiente |

### Esquema completo con unidades

| Columna | Unidad / formato | Notas |
|---|---|---|
| `sitio` | `pi` \| `cp` | Fuente del aviso |
| `id_aviso` | texto | PK junto con `sitio` |
| `url` | texto | |
| `operacion` | `venta` \| `arriendo` | **Segmenta los modelos** |
| `tipo` | `casa` \| `departamento` | |
| `comuna` | `macul`\|`la-florida`\|`nunoa`\|`san-miguel` | slug, sin tildes |
| `barrio` | texto | **377 valores distintos** → alta cardinalidad |
| `direccion` | texto | Nivel edificio/calle, no exacta |
| `titulo` | texto | |
| `precio_valor` | número | Precio original, **NO USAR** (mezcla monedas) |
| `precio_moneda` | `UF` \| `CLP` | |
| `precio_clp` | pesos chilenos | **TARGET del modelo de arriendo** |
| `precio_uf` | UF | **TARGET del modelo de venta** |
| `m2_util` | m² | Superficie interior habitable |
| `m2_total` | m² | útil + terrazas; en casas suele ser terreno |
| `dormitorios` | entero | 0 = monoambiente |
| `banos` | entero | |
| `estacionamientos` | entero | |
| `bodegas` | entero | |
| `antiguedad_anos` | años | |
| `ano_construccion` | AAAA | |
| `gastos_comunes_clp` | CLP/mes | |
| `antiguedad_aviso_dias` | días | ⚠️ **NO usar como predictor** (ver §5) |
| `fecha_publicacion` | AAAA-MM-DD | |
| `lat`, `lon` | grados decimales WGS84 | Para features espaciales |
| `descripcion` | texto (máx 2000) | Sin explotar todavía |
| `publica` | — | **Columna vacía, ignorar** |
| `detalle_ok` | 0/1 | Control interno del scraper |
| `fecha_scrape` | AAAA-MM-DD | |

### ⚠️ Convención crítica: `SIN_DATO`

**Todas las celdas vacías contienen el texto `"SIN_DATO"`, no NULL.** Y **todas las columnas
están tipadas como TEXT en SQLite**, incluidos los números.

```python
import pandas as pd
df = pd.read_csv("data/ofertas_unificado.csv", na_values=["SIN_DATO"])
# columnas numéricas necesitan cast explícito:
for c in ["precio_uf","precio_clp","m2_util","m2_total","dormitorios","banos",
          "estacionamientos","bodegas","ano_construccion","gastos_comunes_clp","lat","lon"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")
```

Si omites `na_values`, pandas leerá todo como texto y los modelos fallarán en silencio.

### Cobertura de variables (% con dato, sobre las 15.808 filas)

```
m2_util             99.2%      ano_construccion    77.3%
banos               90.4%      precio_clp          76.3%
lat / lon           90.8%      gastos_comunes      74.3%
barrio              91.2%      dormitorios         74.4%  ⚠️
m2_total            89.2%      estacionamientos    52.7%  ⚠️
precio_uf           80.4%
```

---

## 3. Problemas conocidos del dataset

Estos ya están diagnosticados. No los re-investigues; trátalos.

| # | Problema | Detalle | Acción |
|---|---|---|---|
| 1 | **`precio_uf` vacío en ~3.300 filas** | Todas en CLP capturadas el 27/07: la API de la UF falló ese día. `precio_valor` sí está | **Recalcular**: `precio_uf = precio_clp / valor_UF`. UF de referencia ≈ **40.845 CLP** (o consultar `https://mindicador.cl/api/uf`) |
| 2 | **`dormitorios` solo 74%** | Bug de scraping ya corregido, pero la reparación quedó a medias | Imputar por mediana del segmento (comuna+tipo+rango m²) |
| 3 | **`estacionamientos` 53%** | Muchos avisos no lo informan | El faltante puede ser informativo: probar flag `tiene_estacionamiento` |
| 4 | **`gastos_comunes = 0` en ~2.600 filas** | Ambiguo: ¿cero real (casas) o no informado? | Tratar 0 como faltante en departamentos |
| 5 | **Las 1.346 filas de `cp` no tienen lat/lon** | La fuente no las entrega | Quedan fuera de las features espaciales, o geocodificar |
| 6 | **`m2_util > m2_total`** en ~420 filas | Inconsistencia del publicador | Descartar o intercambiar |
| 7 | **Proyectos inmobiliarios** | Ya se eliminaron 89 (rangos en vez de valores) | Puede quedar algún residuo: vigilar outliers |

### Sesgos estructurales (declararlos, no se pueden eliminar)

- **Precios de publicación, no de cierre.** El modelo estima "precio pedido esperado". El sesgo
  típico en Chile es 5-15% sobre el cierre real.
- **Sesgo de selección invertido.** El dataset es una foto de lo publicado: las propiedades bien
  valoradas se venden rápido y desaparecen; las sobrevaloradas se acumulan. Hay 174 avisos con
  más de 365 días publicados.

---

## 4. Decisiones de diseño ya tomadas

No las reabras sin evidencia que las contradiga.

### 4.1 Dos modelos separados (no uno con "operación" como variable)

```
MODELO-VENTA     target: log(precio_uf)     n ≈ 8.700
MODELO-ARRIENDO  target: log(precio_clp)    n ≈ 5.700
```

Razones: los targets tienen escalas incomparables (miles de UF vs cientos de miles de CLP); son
propiedades distintas (ninguna está simultáneamente en venta y arriendo); y las variables pesan
distinto en cada mercado (el año de construcción importa mucho en venta, poco en arriendo; el
metro pesa más en arriendo).

**A evaluar empíricamente:** si conviene además separar casa/departamento (serían 4 modelos).
Criterio: quedarse con la configuración de menor MdAPE. Para *arriendo-casa* (211 filas) **no**
entrenar modelo propio: usar el de arriendo general con `tipo` como variable, y marcar esas
predicciones como de baja confianza.

### 4.2 Target en logaritmo

Entrenar sobre `log(precio)` y exponenciar al predecir. Los precios inmobiliarios tienen
distribución sesgada a la derecha; el log la normaliza y hace que el error se interprete como
porcentual, que es lo que importa en tasación.

### 4.3 Métricas de evaluación (estándar de la industria AVM)

| Métrica | Qué mide | Meta |
|---|---|---|
| **MdAPE** | Error porcentual absoluto **mediano** | < 15% (excelente < 10%) |
| **PPE10** | % de predicciones dentro de ±10% del real | > 50% (institucional > 70%) |
| **COD** | Uniformidad (dispersión de los ratios estimado/real) | < 15 |
| **PRD** | Sesgo vertical: ¿sobrevalora las baratas? | 0,98 – 1,03 |
| MAE / RMSE / R² | Complementarias | reportar |

MdAPE y PPE10 son las principales: en tasación se usa la **mediana** porque unos pocos outliers
distorsionan la media.

### 4.4 Validación cruzada ESPACIAL (no aleatoria)

Un split aleatorio pone departamentos del mismo edificio en train y test, y el modelo "hace
trampa" memorizando ese edificio → métricas infladas.

**Usar `GroupKFold` agrupando por barrio** (o por coordenada redondeada a ~3 decimales). Reportar
ambos resultados (aleatorio vs espacial): la diferencia entre ambos es un resultado interesante
para documentar.

---

## 5. Errores a evitar (los más probables en este proyecto)

| Error | Por qué pasa | Cómo evitarlo |
|---|---|---|
| **Data leakage con `antiguedad_aviso_dias`** | Un aviso lleva 300 días publicado *porque* está caro. Es consecuencia del precio, no causa | **Excluir de los predictores.** Sirve para filtrar zombis, no para predecir |
| **Leakage con `precio_valor`** | Es el mismo precio en otra unidad | Excluir siempre |
| **Split aleatorio** | Vecinos en train y test | GroupKFold espacial |
| **Imputar antes de dividir** | La media del test se filtra al train | Imputar **dentro** de cada fold |
| **Evaluar en escala log** | Un R² de 0,9 en log puede ser malo en pesos | Convertir a escala original antes de medir |
| **Mezclar venta y arriendo** | Escalas distintas | Modelos separados |
| **Confiar en métricas demasiado buenas** | En ML los bugs no rompen el programa: dan métricas irreales | Si MdAPE < 5%, sospechar leakage |

---

## 6. Plan de trabajo por fases

### FASE 0 — Setup y exploración (½ día)

```bash
.venv\Scripts\python.exe -m pip install pandas numpy scikit-learn xgboost lightgbm shap matplotlib scipy
```

⚠️ **Python 3.14 es muy reciente.** Si `xgboost`, `lightgbm` o `shap` no tienen wheels
disponibles, crear un venv aparte con Python 3.12 solo para ML. Verificar antes de avanzar.

Entregable: notebook o script de exploración con distribuciones, correlaciones y outliers.

### FASE 1 — Preparación de datos

Módulo `ml/data.py`:

1. Carga desde SQLite con `na_values=["SIN_DATO"]` y cast numérico.
2. **Arreglar `precio_uf`** faltante (problema #1).
3. **Filtros de calidad** (documentar cuántas filas elimina cada uno):
   - `m2_util` entre 20 y 1.000
   - `precio_uf` entre 500 y 60.000 (venta) · `precio_clp` entre 100.000 y 5.000.000 (arriendo)
   - `ano_construccion` entre 1900 y 2030
   - descartar `m2_util > m2_total`
   - recortar por percentil 1 y 99 de **UF/m²** dentro de cada comuna+tipo
4. **Features derivadas**:
   ```
   uf_por_m2          = precio_uf / m2_util          (solo análisis, NO predictor)
   ratio_terraza      = (m2_total - m2_util) / m2_total
   antiguedad         = 2026 - ano_construccion
   tiene_estacionamiento, tiene_bodega   (flags binarios)
   densidad_banos     = banos / dormitorios
   ```
5. **Encoding**: `comuna` → one-hot (4 valores) · `barrio` → **target encoding** (377 valores;
   calcular dentro del fold para no filtrar) · `tipo`, `sitio` → one-hot.
6. **`lat`/`lon` como predictores directos**: los modelos de árboles capturan geografía
   sorprendentemente bien con las coordenadas crudas.

### FASE 2 — Baseline hedónico clásico

Módulo `ml/baseline.py`. Regresión lineal sobre `log(precio)` con las variables clásicas.

Sirve para: (a) tener un piso de comparación, (b) **validar signos teóricos** — más m² debe subir
el precio, más antigüedad bajarlo; si algún signo sale invertido, hay un problema en los datos,
(c) respaldar la tesis con el enfoque hedónico tradicional.

Reportar coeficientes, R² ajustado, VIF (multicolinealidad) y **I de Moran sobre los residuos**
(si queda autocorrelación espacial, falta modelar la ubicación).

### FASE 3 — Modelos ML y comparación

Módulo `ml/models.py`. **Estructura desde el inicio para probar varios modelos**, porque esto se
va a ampliar:

```python
MODELOS = {
    "ridge":          make_ridge(),
    "random_forest":  make_rf(),
    "xgboost":        make_xgb(),
    "lightgbm":       make_lgbm(),
    "hist_gradient":  make_hgb(),      # sklearn, sin dependencias extra
}
```

Todos deben compartir **la misma interfaz** (`fit`/`predict`), **el mismo split** y **las mismas
métricas**, para que la comparación sea justa. Ejecutar con una sola llamada:

```bash
python -m ml.train --target venta --modelos todos --cv espacial
```

Salida esperada: tabla comparativa ordenada por MdAPE.

| modelo | MdAPE | PPE10 | COD | PRD | tiempo |
|---|---|---|---|---|---|
| … | … | … | … | … | … |

Tuning: `RandomizedSearchCV` sobre el mejor candidato, no sobre todos.

### FASE 4 — Explicabilidad (SHAP)

Módulo `ml/explain.py`. Sobre el modelo ganador:

- **Importancia global** de variables (¿coincide con la teoría hedónica?)
- **Desglose local** por propiedad — es la salida que consume el producto:
  ```
  Base (promedio)          3.450 UF
  + superficie 62 m²        + 890
  + comuna Ñuñoa            + 640
  + metro a 340 m           + 180
  − antigüedad 11 años       − 95
  = PREDICCIÓN             5.100 UF
  ```
- **Agregado de ubicación** = suma de las contribuciones de comuna, barrio, lat/lon y POIs →
  ese es el **Indicador 3**.

### FASE 5 — Intervalos de predicción

El producto necesita rango mínimo/esperado/máximo, no un número solo.

Usar **regresión cuantílica** (`objective="quantile"` en LightGBM, o `GradientBoostingRegressor`
con `loss="quantile"`) entrenando percentiles 10, 50 y 90.

Validar la **calibración**: el intervalo 10-90 debe contener el precio real ~80% de las veces. Si
contiene el 95%, es demasiado ancho; si el 60%, demasiado optimista.

### FASE 6 — API de predicción

Módulo `ml/service.py` (FastAPI). El agente LangGraph lo consumirá por HTTP.

```
POST /predict/venta      → {precio_estimado_uf, intervalo_80, n_comparables, shap}
POST /predict/arriendo   → {arriendo_estimado_clp, intervalo_80}
POST /comparables        → k propiedades similares del dataset (para el informe)
```

Entrada: los atributos de la propiedad. Los modelos se cargan una vez al arrancar (no por request).

---

## 7. Flujo de re-evaluación (obligatorio en cada fase)

Después de programar cada fase, **antes de darla por buena**:

```
1. /verify        → ejecutar y comprobar que hace lo que dice
2. /code-review   → cazar bugs de correctitud (leakage, splits, escalas)
3. pytest         → tests de las funciones deterministas
4. /simplify      → limpieza si el código se repite
```

El paso 2 es especialmente importante aquí: **en ML los bugs no hacen fallar el programa**, dan
métricas demasiado buenas y pasan desapercibidos.

### Checklist de sanidad tras cada entrenamiento

- [ ] ¿MdAPE > 5%? Si es menor, sospechar leakage.
- [ ] ¿El modelo espacial da peor métrica que el aleatorio? Debe ser así; si no, hay fuga.
- [ ] ¿Los signos del baseline son teóricamente correctos?
- [ ] ¿PRD entre 0,98 y 1,03? Fuera de rango = sesgo sistemático por rango de precio.
- [ ] ¿El error por comuna es parecido? Si una comuna tiene el doble de error, revisar.
- [ ] ¿Las variables más importantes tienen sentido de negocio?

---

## 8. Pruebas (pytest)

```
tests/
  test_data.py       carga, cast numérico, SIN_DATO → NaN, filtros
  test_features.py   derivadas correctas con valores conocidos
  test_metrics.py    MdAPE/PPE10/COD/PRD contra ejemplos calculados a mano
  test_model.py      entrena con muestra pequeña, predice, forma correcta
  test_service.py    endpoints responden con el esquema esperado
```

Ejemplo de test con valor conocido (verificado contra un simulador comercial real):

```python
def test_dividendo_frances():
    # 800 UF a 3,99% en 25 años, UF=40.845 → $172.296
    # ComparaOnline muestra $172.300 para el mismo caso (dif. 0,00%)
    assert abs(dividendo(800*40845, 0.0399, 25) - 172296) < 50
```

---

## 9. Estructura de archivos propuesta

```
ml/
  __init__.py
  config.py        rutas, semillas, hiperparámetros, umbrales de filtros
  data.py          carga, limpieza, filtros
  features.py      derivadas y encoding
  baseline.py      hedónica lineal
  models.py        registro de modelos con interfaz común
  metrics.py       MdAPE, PPE10, COD, PRD
  validation.py    splits espacial y aleatorio
  train.py         CLI de entrenamiento y comparación
  explain.py       SHAP
  service.py       FastAPI
  artifacts/       modelos serializados + métricas en JSON
tests/
```

**Reproducibilidad:** semilla fija en todo (`random_state=42`), y guardar junto a cada modelo un
JSON con: fecha, filas usadas, features, hiperparámetros y métricas.

---

## 10. Criterios de aceptación

**Mínimo viable**
- [ ] Modelo de venta con **MdAPE < 20%** y **PPE10 > 40%** en validación espacial
- [ ] Modelo de arriendo con **MdAPE < 25%**
- [ ] Al menos 3 modelos comparados con la misma metodología
- [ ] Baseline hedónico con signos teóricamente correctos
- [ ] Tests pasando

**Objetivo**
- [ ] MdAPE < 15% y PPE10 > 50% en venta
- [ ] COD < 20 y PRD entre 0,97 y 1,04
- [ ] SHAP funcionando con desglose por propiedad
- [ ] Intervalos calibrados (cobertura ~80%)
- [ ] API respondiendo

Si el MdAPE queda muy por sobre 20%, **no es necesariamente un fallo del modelo**: puede ser el
límite de lo que estos datos permiten (precios de publicación, sin datos de estado interior).
Documentarlo con evidencia es un resultado válido para la tesis.

---

## 11. Contexto adicional útil

- El dataset se construyó con scrapers propios (`scraper/` y `scraper_v1/`). **No los modifiques.**
- PortalInmobiliario está bloqueando el scraping actualmente. Verificar con
  `python comprobar_acceso.py` si se necesitan más datos.
- **Faltan las features espaciales (POIs)**: distancia a metro, colegios, supermercados, áreas
  verdes desde `lat`/`lon`. Se planificó usar OSM Overpass (gratis, sin API key). **Es la mejora
  de mayor impacto pendiente** para el componente de ubicación. Si no están listas, entrenar sin
  ellas y dejar el pipeline preparado para incorporarlas.
- Documentos de referencia en el repo: `documentacion.md` (proceso de scraping),
  `Arquitectura_deseada.md` (arquitectura del sistema), `resumen_dataset.py` (reporte del dataset).
- Verificar el estado del dataset en cualquier momento:
  `.venv\Scripts\python.exe resumen_dataset.py --db data/ofertas_unificado.sqlite`

---

## 12. Primer paso sugerido

1. Verificar que las librerías instalan en Python 3.14 (si no, venv con 3.12).
2. Cargar el dataset y reproducir estos números: **15.808 filas**, venta-depto **6.355**
   utilizables, arriendo-depto **5.492**.
3. Recalcular `precio_uf` faltante (problema #1) — es la corrección de mayor impacto y no
   requiere red.
4. Recién entonces empezar con `ml/data.py`.
