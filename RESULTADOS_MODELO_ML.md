# Resultados — Modelos ML de valoración inmobiliaria (FASES 0–3)

> Documento de resultados de la capa 1 descrita en `PLAN_MODELO_ML.md`.
> Todo lo de aquí es reproducible desde `ml/artifacts/*.json`.

## 1. Resumen

Se construyó el módulo `ml/` completo hasta la FASE 3: carga, reparación de precios, filtros de
calidad, features, métricas AVM, validación cruzada espacial, baseline hedónico y comparación de
cinco modelos. **193 tests pasan.**

Resultados en **validación espacial** (la cifra honesta, no la del split aleatorio):

| Segmento | n | Modelo ganador | MdAPE | PPE10 | COD | PRD | PRB | Δ espacial−aleatorio |
|---|---|---|---|---|---|---|---|---|
| venta · departamento | 6.471 | xgboost | **8,06 %** | 59,6 % | 10,03 | 1,015 | −0,036 | +0,40 |
| venta · casa | 3.000 | hist_gradient | **10,98 %** | 46,9 % | 15,23 | 1,040 | −0,044 | +0,34 |
| arriendo (ambos tipos) | 5.452 | random_forest | **7,66 %** | 61,7 % | 10,46 | 1,027 | −0,078 | +0,43 |

**Se cumplen todos los criterios de aceptación, incluidos los del objetivo**, no solo los del mínimo
viable. La meta era MdAPE < 15 % y PPE10 > 50 % en venta; se obtuvo 8,06 % y 59,6 %.

## 2. Criterios de aceptación (§10 del plan)

**Mínimo viable** — venta MdAPE < 20 % ✅ (8,06 / 10,98) · venta PPE10 > 40 % ✅ (59,6 / 46,9) ·
arriendo MdAPE < 25 % ✅ (7,66) · ≥ 3 modelos comparados ✅ (5) · baseline con signos correctos ✅ ·
tests pasando ✅ (193).

**Objetivo** — MdAPE < 15 % ✅ · PPE10 > 50 % ✅ · COD < 20 ✅ (10,03 / 15,23 / 10,46) ·
PRD 0,97–1,04 ✅ (1,015 / 1,040 / 1,027).

Pendientes de FASES 4–6, fuera del alcance acordado: SHAP, intervalos calibrados y API.

## 3. Holdout externo: ¿estaba la validación cruzada siendo optimista?

Las métricas de arriba salen de **validación cruzada de 5 folds con predicciones fuera de fold**:
cada fila la predijo un modelo que nunca la vio. No son métricas en muestra.

Pero esas mismas métricas se usaron para **elegir** el modelo ganador entre cinco candidatos, y
elegir sobre una medición la contamina como estimador de error futuro. Para acotarlo se apartó un
**20 % por grupos espaciales antes de mirar nada**, se hizo toda la selección sobre el 80 % restante
y se evaluó el holdout una sola vez al final, con el ganador reentrenado sobre todo el desarrollo.

| Segmento | n desarrollo | n holdout | MdAPE CV | MdAPE holdout | Brecha |
|---|---|---|---|---|---|
| venta · departamento | 5.224 | 1.247 | 8,09 % | **7,67 %** | −0,43 |
| venta · casa | 2.392 | 608 | 11,43 % | **11,63 %** | +0,19 |
| arriendo | 4.366 | 1.086 | 7,85 % | **7,88 %** | +0,03 |

**Las tres brechas son menores a medio punto, y en venta-departamento el holdout sale incluso mejor
que la CV.** La conclusión es que con cinco candidatos el sesgo de selección era despreciable: las
cifras reportadas se sostienen sobre propiedades de edificios completamente nuevos.

Esto cambia cuando se active el tuning. `RandomizedSearchCV` probaría 40 combinaciones de
hiperparámetros sobre la misma CV, y ahí el sesgo de selección deja de ser despreciable — **el
holdout pasa a ser obligatorio**, no opcional. La bandera ya está lista:

```bash
.venv/Scripts/python.exe -m ml.train --operacion venta --tipo departamento --modelos todos --cv espacial --holdout 0.2
```

El holdout se separa **por grupos espaciales**, no por filas: si un departamento de una torre queda
en desarrollo y otro en el holdout, el holdout deja de ser independiente y no mide nada. Está
verificado por test que ningún edificio aparece en ambos lados. El modelo que se serializa con
`--guardar-modelo` sí se reentrena con todas las filas: una vez que el holdout cumplió su función de
medir, retenerlo solo resta datos.

## 4. Chequeos de sanidad

Los seis del §7 del plan, verificados automáticamente en cada corrida:

- **¿MdAPE > 5 %?** Sí, entre 7,66 y 10,98. Por debajo de 5 % se asume leakage; no se activó.
- **¿El espacial da peor que el aleatorio?** Sí, en los tres segmentos (+0,34 a +0,43 puntos). Si
  diera mejor habría un bug en la clave de agrupación, y `train.py` lo alerta.
- **¿Los signos del baseline son correctos?** Sí, los cinco robustos en los tres segmentos.
- **¿PRD en rango?** Sí en los ganadores. Ridge y random_forest lo exceden en algunos segmentos y
  queda registrado en el artefacto.
- **¿Error homogéneo por comuna?** Sí. En venta-depto va de 6,57 % (Ñuñoa) a 9,44 % (La Florida):
  un factor 1,4, lejos del doble que obligaría a investigar.
- **¿Variables importantes con sentido de negocio?** Sí, vía el baseline: la superficie domina
  (coef. 0,81 en log-log) y Ñuñoa es la comuna con mayor premio (+0,39 en log ≈ +47 %), coherente
  con las medianas de UF/m² medidas sobre el dataset.

### Barreras antileakage, verificadas por test

- El target encoding se ajusta **solo** con el fold de entrenamiento (se comparan las codificaciones
  contra un ajuste solo-train y contra uno global).
- Añadir `precio_uf` a la matriz de entrada **no cambia ni un bit** las predicciones: `remainder="drop"`
  protege aunque nadie borre la columna.
- La imputación usa la mediana del train, no la global.
- Ningún grupo espacial aparece a la vez en train y test, comprobado en cada fold.

## 5. Hallazgos

### 5.1 La reparación bidireccional de la UF recupera 1.179 ventas

El documento de traspaso diagnostica solo la mitad del fallo del 27/07. Verificado: **3.102 filas en
CLP perdieron `precio_uf`** y **3.747 filas en UF perdieron `precio_clp`**. Reparar en ambos
sentidos lleva venta-casa de 2.393 a **3.114** filas utilizables (+30 %) y venta-depto de 6.355 a
**6.813** (+7 %). La UF usada (40.844,79) se deriva de la mediana de `precio_clp/precio_uf` sobre las
8.959 filas que tienen ambos precios, que es más defendible que consultar la UF de hoy.

### 5.2 Las filas con precio reconstruido son más difíciles de predecir

Diagnóstico por origen del precio en venta-departamento:

| Origen | n | MdAPE | Mediana del ratio |
|---|---|---|---|
| scraper (original) | 3.650 | 7,41 % | 1,004 |
| reconstruido UF→CLP | 2.400 | 8,60 % | 0,989 |
| reconstruido CLP→UF | 421 | **11,67 %** | **1,072** |

Las 421 filas reconstruidas de CLP a UF tienen un 57 % más de error y el modelo las **sobrevalora un
7 %**. No es un artefacto de la conversión (es una constante multiplicativa): son propiedades
publicadas en pesos, que en este mercado son un segmento distinto del publicado en UF. Conviene
declararlo y, si el producto lo requiere, marcarlas como de menor confianza.

### 5.3 El split espacial infla menos de lo esperado: +0,4 puntos

Con el 56–62 % de las filas compartiendo edificio, cabía esperar una brecha mayor. Que sea de solo
0,34–0,43 puntos sugiere que el modelo no depende tanto de memorizar torres como de los atributos y
de la ubicación gruesa. Es un resultado a favor de la validez del modelo, y solo se puede afirmar
porque se midieron los dos esquemas.

El tercer esquema (`espacial_estricto`, que excluye del test las 1.460 filas sin geo) da
prácticamente lo mismo que el espacial (8,03 vs 8,06 en venta-depto): esas filas no estaban
inflando nada.

### 5.4 Queda autocorrelación espacial en los residuos del baseline

I de Moran sobre los residuos del OLS, con pesos k-NN (k=8) y p-valor por permutación:

| Segmento | I de Moran | p |
|---|---|---|
| venta-departamento | +0,304 | 0,001 |
| venta-casa | +0,239 | 0,001 |
| arriendo-departamento | +0,266 | 0,001 |

Positiva y significativa en los tres. Es la **justificación empírica** para meter `lat/lon` en los
modelos de árboles, y el argumento para proponer GPBoost como trabajo futuro.

### 5.5 Un modelo vs dos: la respuesta a la pregunta abierta del §4.1

Medido **dentro de cada tipo** (el MdAPE agregado mezcla dos distribuciones y no sirve para decidir):

| | 2 modelos separados | 1 modelo con `tipo` | |
|---|---|---|---|
| venta-departamento | 8,06 % | 8,01 % | empate (−0,05) |
| venta-casa | **11,08 %** | 11,42 % | gana separado (+0,34) |
| arriendo-departamento | **7,49 %** | 7,55 % | empate (+0,05) |

**Decisión: dos modelos para venta** (casa gana 0,34 puntos y depto pierde 0,05, que es ruido) y
**uno para arriendo**, porque arriendo-casa tiene solo 194 filas tras los filtros y necesita apoyarse
en el modelo general. Sus predicciones deben marcarse de baja confianza.

### 5.6 El recorte estadístico no infla las métricas

El filtro p1–p99 de precio/m² usa el target, así que podría estar sacando los casos difíciles. Control
con `--sin-recorte-final`:

| Segmento | con recorte | sin recorte | Δ |
|---|---|---|---|
| venta-departamento | 8,06 % | 8,03 % | −0,03 |
| venta-casa | 10,98 % | 11,53 % | +0,55 |
| arriendo-departamento | 7,49 % | 7,65 % | +0,16 |

Todas por debajo del umbral de 1 punto. El filtro elimina ruido de captura, no dificultad genuina.

## 6. Desviaciones respecto del documento de traspaso

Todas verificadas contra la base antes de aplicarlas:

| # | El documento dice | Lo que muestran los datos |
|---|---|---|
| 1 | `precio_uf` vacío en ~3.300 filas, reparar CLP→UF | Son **3.102**, y el fallo fue **bidireccional**: otras 3.747 perdieron `precio_clp` |
| 2 | Agrupar por barrio o coordenada a 3 decimales | **4 decimales**. A 3 el 89,7 % de las filas queda encadenado y los folds colapsan. Agrupar por barrio dejaría todo barrio del test inédito, midiendo otra cosa |
| 3 | `barrio` → target encoding (377 valores) | La clave debe ser **(comuna, barrio)**: hay 366 nombres pero 377 pares, y 11 nombres se repiten entre comunas |
| 4 | Excluir `antiguedad_aviso_dias` | También **`fecha_publicacion`**: es biyección exacta con la anterior dado `fecha_scrape`, que solo tiene 3 valores |
| 5 | Métricas COD y PRD | Se añade **PRB**, la métrica de sesgo vertical del estándar IAAO, más robusta que PRD |
| 6 | Proyectos: «puede quedar algún residuo» | Los outliers son mucho peores: «arriendos» de 194 y 220 millones (ventas mal etiquetadas), `m2_util` de 1,0 y de 138.000, una coordenada a 70 km |
| 7 | `m2_util > m2_total` en ~420 filas | **410**. Además 3.175 (22,5 %) tienen `m2_total == m2_util` |
| 8 | Faltan lat/lon en las 1.346 de `cp` | **1.460**: las de `cp` más 114 de `pi` |
| 9 | — | **`publica` está 100 % vacía**: columna muerta |
| 10 | — | **`cp` es solo arriendo-departamento**: todo venta depende de una sola fuente |

## 7. Sesgos declarados

No se pueden corregir con estos datos; quedan serializados en cada artefacto:

1. **Precios de publicación, no de cierre.** En Chile el sesgo típico es 5–15 % sobre el precio final.
   El modelo estima «precio pedido esperado», no precio de transacción.
2. **Sesgo de selección invertido.** Lo bien valorado se vende y desaparece del stock; lo
   sobrevalorado se acumula.
3. **Truncamiento a 2.016 resultados por búsqueda** (`documentacion.md` §8), que afecta justo a
   departamentos en venta de Ñuñoa y San Miguel — el segmento más grande del modelo de venta.
4. **Fuente única en venta**: sin posibilidad de validación externa.
5. **Sin dispersión temporal**: 3 fechas de scrape en 15 días y la UF varió 0,16 %. No procede ajuste
   temporal; deflactar por `fecha_publicacion` confundiría antigüedad del aviso con época del precio.

Una nota de honestidad sobre el R² del baseline: el OLS usa solo casos completos (2.232 de 6.471
filas en venta-depto, por la cobertura del 53 % de `estacionamientos`), así que **no es directamente
comparable** con las métricas de los modelos de ML, que sí usan todas las filas.

## 8. Cómo reproducir

```bash
.venv/Scripts/python.exe -m pip install -r requirements-ml.txt
```
```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```
```bash
.venv/Scripts/python.exe -m ml.train --operacion venta --tipo departamento --modelos todos --cv todos
```
```bash
.venv/Scripts/python.exe -m ml.train --operacion arriendo --tipo todos --modelos todos --cv todos
```

Cada corrida escribe en `ml/artifacts/` un JSON con fecha, commit, versiones del entorno, hash de la
base, UF usada, reporte de los 12 filtros paso a paso, features, esquemas de validación, coeficientes
del baseline, métricas de todos los modelos, diagnóstico y sesgos. Semilla fija en 42.

## 9. Entorno

Todo corre en el `.venv` existente con **Python 3.14.5**. Se verificó en PyPI que pandas 3.0.5,
scikit-learn 1.9.0 y statsmodels 0.14.6 tienen wheel `cp314`, y que lightgbm y xgboost publican
wheels universales `py3-none-win_amd64`.

**`shap` no tiene wheel para Python 3.14** (solo hasta cp313). No hace falta: LightGBM
(`pred_contrib=True`) y XGBoost (`pred_contribs=True`) calculan **TreeSHAP exacto en C++** — la misma
implementación que la librería envuelve. Solo se pierden sus gráficos, reemplazables con matplotlib.
`ml/models.py` marca qué modelos tienen backend nativo.

## 10. Siguientes pasos

1. **FASE 4 — SHAP.** Backend nativo. Ojo: el modelo está en log y los φ son aditivos en log, así que
   la cascada en UF debe construirse secuencialmente (`exp(base+Σ_{j≤k}φ) − exp(base+Σ_{j<k}φ)`), no
   con `exp(φ)` suelto. El agregado de comuna + barrio + lat/lon es el Indicador 3 del producto.
2. **FASE 5 — Intervalos.** Regresión cuantílica envuelta en **Conformalized Quantile Regression**
   (Romano et al., NeurIPS 2019): la cuantílica sola suele quedar mal calibrada fuera de muestra. El
   split de calibración debe respetar los grupos espaciales o la garantía se rompe.
3. **FASE 6 — API.** FastAPI ya está en el venv. Marcar baja confianza en arriendo-casa, barrio
   inédito, sin geo, o `m2_util` fuera del rango de entrenamiento.
4. **POIs.** `ml/features.py` deja el punto de enganche. Entrenar sin ellos primero permite medir
   cuánto aportan realmente contra esta línea base.
5. **Tuning.** `RandomizedSearchCV` sobre el ganador, **siempre con `--holdout 0.2`**: con 40
   combinaciones de hiperparámetros el sesgo de selección deja de ser despreciable, a diferencia de
   lo medido con cinco candidatos.
