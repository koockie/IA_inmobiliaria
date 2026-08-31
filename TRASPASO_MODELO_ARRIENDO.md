# Traspaso — Modelo ML de estimación de arriendo

> **Instrucción para el agente que recibe esto:** lee el documento completo antes de escribir código.
> Tu única tarea ahora es **construir el modelo de arriendo** en un notebook nuevo llamado
> `modelo_arriendo.ipynb`. No toques los notebooks existentes ni la base de datos.
> Al final del documento está la especificación exacta de lo que hay que hacer.

---

## 1. El proyecto

Se está construyendo el MVP de una plataforma que **recomienda inversión inmobiliaria** a personas
sin conocimiento técnico, en 4 comunas de Santiago de Chile: **Macul, La Florida, Ñuñoa y San
Miguel**.

El caso de uso final: un usuario pega el enlace de un aviso. El backend extrae sus características
(ubicación, superficie, dormitorios, baños…), consulta los servicios cercanos por la API de Google
Places, y con eso responde tres cosas:

1. **¿Está caro o barato?** → modelo de precio de venta. **Ya construido.**
2. **¿En cuánto se podría arrendar?** → modelo de arriendo. **Es tu tarea.**
3. **¿Conviene como inversión?** → con lo anterior se calcula el yield: si el arriendo cubre el
   dividendo hipotecario. Viene después.

Más adelante se quiere estimar el potencial de plusvalía del sector, pero eso exige datos que hoy no
existen en el dataset (permisos de edificación, series históricas). **No lo prometas.**

Todo se desplegará en **DigitalOcean como API**. Por ahora solo se trabaja en notebooks.

---

## 2. Entorno

```
Repositorio : C:\Users\marce\Desktop\inmobiliaria   (rama git: modeloML)
Interprete  : .venv\Scripts\python.exe              (Python 3.14.5)
Kernel      : "Python (inmobiliaria)"
```

**Ejecuta siempre con `./.venv/Scripts/python.exe`.** El `python` a secas no existe en esta máquina
(es un alias de la Microsoft Store).

Instalado: pandas 3.0.5, numpy 2.5.2, scikit-learn 1.9.0, scipy, xgboost 3.4.1, lightgbm 4.7.0,
statsmodels 0.14.6, matplotlib 3.11.1, jupyterlab, joblib, httpx, python-dotenv, pypdf.

**`shap` NO está instalado y no se puede**: no tiene wheel para Python 3.14 (solo hasta cp313). Si
más adelante hace falta TreeSHAP, se obtiene del booster nativo de LightGBM (`pred_contrib=True`) o
XGBoost (`pred_contribs=True`), que es la misma implementación en C++.

### Gotchas del entorno

- **`load_dotenv()` necesita `override=True`** y ruta explícita: `load_dotenv(".env", override=True)`.
  Sin `override` no reemplaza una variable ya cargada en el kernel, y se usa una clave vieja sin
  darse cuenta. Ya pasó una vez y costó una hora de diagnóstico.
- **`permutation_importance` con `n_jobs=-1` revienta en Windows** con un `KeyError` de joblib
  memmapping. Usa `n_jobs=1`.
- **pandas 3.0** es major nuevo: copy-on-write y string dtype por defecto. Nada de asignación
  encadenada; usa `.loc` o `.assign()`.
- Los heredocs de bash a veces fallan con contenido largo. Para archivos grandes usa la herramienta
  Write.

---

## 3. Los datos

### Ubicación y formato

```
data/ofertas_unificado.sqlite   tabla: ofertas   <- FUENTE DE VERDAD
data/ofertas_unificado.csv      espejo exacto
data/poi_cache.sqlite           respuestas cacheadas de Google Places
```

**15.808 filas × 31 columnas.** Ábrela siempre en solo lectura:

```python
sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=15)
```

### Dos convenciones que hay que deshacer SIEMPRE

1. **Las celdas vacías contienen el texto `"SIN_DATO"`, no NULL.**
2. **Todas las columnas están tipadas `TEXT`** (salvo `detalle_ok`), incluidos los números.

El orden importa: primero el centinela a `NaN`, después el casteo. Al revés no se distingue un
faltante legítimo de un valor que no parsea.

```python
df = crudo.replace("SIN_DATO", pd.NA)
for c in NUMERICAS:
    df[c] = pd.to_numeric(df[c], errors="coerce")
```

⚠️ **Nunca hagas `CAST(columna AS REAL)` en SQL sin filtrar**: SQLite devuelve `0.0` para
`"SIN_DATO"` y contamina las medianas en silencio.

### La columna `servicios_cercanos`

Se construyó con la API de Google Places. Es un JSON por fila con siete categorías:

```json
{
  "metro":        {"mas_cercano_m": 552, "nombre": "Francisco Bilbao", "n_1km": 2},
  "salud":        {"mas_cercano_m": 667, "nombre": "...", "n_1km": 1},
  "comercio":     {"mas_cercano_m": 1489, "nombre": "...", "n_1km": 0},
  "universidad":  {"mas_cercano_m": 1673, "nombre": "...", "n_1km": 0},
  "educacion":    {"mas_cercano_m": 102, "nombre": "...", "n_1km": 12},
  "parque":       {"mas_cercano_m": 288, "nombre": "...", "n_1km": 4},
  "supermercado": {"mas_cercano_m": 126, "nombre": "...", "n_1km": 4},
  "_truncado": true
}
```

**Cosas que hay que saber sobre esta columna:**

- **`mas_cercano_m` es exacto.** La API devuelve los lugares ordenados por distancia, así que el más
  próximo nunca queda fuera.
- **`n_1km` está CENSURADO** en zonas densas: la API tope en 20 resultados y el 95,6 % de los puntos
  lo alcanzó. Por eso existe `_truncado`: cuando es `true`, el conteo es un **piso**, no el total.
  Inclúyelo como variable para que el modelo lo sepa.
- **Los nombres `comercio`, `salud` y `educacion` NO son mall, hospital ni colegio.** Los tipos de
  Google los aportan usuarios y son laxísimos: una barbería figura como `shopping_mall` y un
  veterinario como `hospital`. Se filtró por número de reseñas y aun así pasan negocios medianos.
  Se renombraron a propósito para no prometer lo que el dato no cumple. **`metro` sí es fiable**: las
  125 estaciones del catálogo son todas reales.

---

## 4. Problemas del dataset ya diagnosticados y resueltos

**No los re-investigues. Aplica las mismas correcciones.**

| Problema | Detalle | Corrección |
|---|---|---|
| **Precios sin convertir** | El 27/07 falló la API de la UF. El fallo fue **bidireccional**: 3.102 filas en CLP perdieron `precio_uf` y 3.747 en UF perdieron `precio_clp` | Reconstruir en ambos sentidos con `UF = 40.844,79`, que es la mediana empírica de `precio_clp/precio_uf` sobre las filas que tienen ambos. **No consultes mindicador.cl**: daría la UF de hoy, no la del scrape |
| **Campos de antigüedad intercambiados** | En 185 avisos el año quedó en `antiguedad_anos` y la antigüedad en `ano_construccion` (ej: `ano_construccion=4`, `antiguedad_anos=2022`) | Detectar (uno en rango de antigüedad, el otro en rango de año) e intercambiar. **Recupera el dato en vez de descartarlo** |
| **Conteos del edificio** | `estacionamientos` hasta 540 y `bodegas` hasta 350: es el conteo del edificio entero, no de la unidad | Anular fuera de [0, 10] |
| **`m2_util > m2_total`** | 410 filas | Anular `m2_total`, conservar la fila |
| **`gastos_comunes = 0`** | Ambiguo: en casa es cero real (53,6 %), en departamento es «no informado» (6,2 %) | Anular **solo en departamentos** |
| **Coordenadas rotas** | Un aviso dice «San Miguel» pero cae a 58 km, cerca de la costa | Ya está en `SIN_DATO` en la base |
| **`publica` 100 % vacía** | Columna muerta | Dropear |

**Principio general que se ha seguido: anular el campo, no descartar la fila.** Los modelos de
árboles manejan NaN nativamente y perder una fila entera por un campo secundario es caro.

---

## 5. Lo que ya se hizo (y qué aprendimos)

### `clustering.ipynb` — diagnóstico del dataset

Se agruparon las propiedades **solo por atributos, sin ver el precio**, y luego se midió si los
grupos tenían precios distintos. Resultado:

| | η² | Interpretación |
|---|---|---|
| Venta | 0,435 | efecto grande |
| **Arriendo** | **0,489** | **efecto grande** |

Cohen considera 0,14 un efecto grande. **Ambos datasets tienen señal fuerte.**

Otros hallazgos relevantes para ti:

- **El arriendo es MÁS predecible que la venta.** η² más alto y dispersión de partida mucho menor:
  predecir con la mediana global da 20 % de error en arriendo contra 36 % en venta. Los arriendos
  están más estandarizados. **Espera mejores métricas que las de venta.**
- **No hay segmentos discretos**, hay un continuo (silueta 0,22–0,64 pero cae a ~0,22 en cuanto
  *k* > 2). Eso favorece una regresión continua, no un modelo por segmento.
- **Hopkins resultó NO informativo** (0,985 real contra 0,973 con las columnas barajadas). Se dejó
  documentado como resultado negativo. No lo uses.

### `servicios_cercanos.ipynb` — extracción de POIs

3.453 puntos únicos consultados (deduplicando por grilla de 3 decimales ≈ 110 m, un 76 % de ahorro).
Costo: **0 USD**, dentro del cupo gratuito. Ya está todo cacheado; **no necesitas llamar a la API**.

### `modelo_venta.ipynb` — el modelo de venta (tu referencia)

**Cópialo como plantilla.** Resultados sobre el 20 % de prueba:

| Modelo | MdAPE | PPE10 | COD | PRD | R² |
|---|---|---|---|---|---|
| **hist_gradient** | **8,78 %** | 55,4 % | 12,2 | 1,029 | 0,870 |
| xgboost | 8,93 % | 55,1 % | 12,2 | 1,030 | 0,866 |
| lightgbm | 9,08 % | 54,8 % | 12,3 | 1,030 | 0,868 |
| random_forest | 9,60 % | 52,2 % | 13,1 | 1,055 | 0,842 |
| ridge (log-lineal) | 12,03 % | 42,1 % | 15,6 | 1,043 | 0,835 |

Tres cosas que se aprendieron ahí y que **debes replicar**:

1. **La división aleatoria NO infló** (8,75 % contra 8,78 %). Se esperaba que sí, porque el 62 % de
   los avisos comparte edificio. Se midió y resultó estar dentro del ruido. Aun así se usa la
   agrupada por rigor. **Mide las dos y reporta lo que salga, no lo que esperas.**
2. **El intervalo cuantílico cubría 66 % cuando prometía 80 %.** Se corrigió con **calibración
   conforme**: subió a 78,7 % ensanchando de 28 % a 39 %. **Aplica lo mismo.**
3. **Los servicios cercanos aportan poco**: 71 % estructural, 24 % ubicación, **5 % vecindario**. De
   los POI solo `log_dist_metro` entra entre las 10 variables más influyentes. Probablemente
   `lat`/`lon` ya capturan casi toda la ubicación. **Verifica si en arriendo pasa lo mismo** — puede
   que no, porque los arrendatarios valoran el metro más que los compradores.

---

## 6. ⚠️ El problema específico del modelo de arriendo

**Este es el punto más importante del documento.**

El conjunto de arriendo son **5.662 avisos** tras los filtros (5.462 departamentos + 200 casas), y
viene de **dos fuentes con calidad radicalmente distinta**:

| Variable | portalinmobiliario (`pi`) | chilepropiedades (`cp`) |
|---|---|---|
| filas | 4.359 | **1.303 (23 %)** |
| `m2_util` | 100 % | 100 % |
| `dormitorios` | 73,8 % | 98,8 % |
| `banos` | 93,3 % | 99,5 % |
| `estacionamientos` | 43,3 % | 50,7 % |
| **`m2_total`** | 98,3 % | **0 %** |
| **`bodegas`** | 96,0 % | **0 %** |
| **`ano_construccion`** | 73,5 % | **0 %** |
| **`gastos_comunes_clp`** | 92,4 % | **0 %** |
| **`lat` / `lon`** | 98,8 % | **0 %** |
| **`servicios_cercanos`** | 98,8 % | **0 %** |

**Un 23 % del conjunto de arriendo no tiene coordenadas, ni antigüedad, ni servicios cercanos, ni
gastos comunes.** No son faltantes al azar: es una fuente entera sin esos campos. Solo aporta
comuna, tipo, superficie útil, dormitorios y baños.

En venta esto no ocurre (las 9.812 filas vienen todas de portalinmobiliario).

### Qué hacer con eso — decisión ya tomada

**Entrenar con todo, añadir indicadores de faltante, y medir el error por fuente.** Concretamente:

1. Añade una variable `sin_geo` (1 si no tiene coordenadas) y `sin_servicios`. La ausencia es
   información: identifica la fuente y probablemente correlaciona con el tipo de aviso.
2. **NO uses `sitio` como variable del modelo**: la API no puede saber de qué portal vendría un aviso
   nuevo. Úsala solo para diagnosticar.
3. Al evaluar, **reporta el MdAPE por separado para `pi` y `cp`**. Si el error en `cp` es mucho peor,
   hay que decidir si se excluyen o se marcan de baja confianza en el producto. Esa decisión la toma
   el usuario del proyecto con el número a la vista, no tú por tu cuenta.

### El otro problema: casi no hay casas

**200 casas contra 5.462 departamentos.** El modelo va a saber muy poco de casas en arriendo.
Reporta el error por tipo y **marca las predicciones de casa como de baja confianza**. No entrenes
un modelo separado para casas: con 200 filas no alcanza.

---

## 7. Metodología obligatoria

Estas decisiones ya están validadas. **No las reabras sin evidencia que las contradiga.**

### Marco hedónico

Se sigue Owusu-Ansah (2011), *A Review of Hedonic Pricing Models in Housing Research*. Los atributos
van en los **tres bloques de Rosen (1974)**:

- **Estructurales**: superficie, dormitorios, baños, estacionamientos, bodegas, antigüedad
- **Ubicación**: lat, lon, comuna
- **Vecindario**: las siete categorías de `servicios_cercanos`

### Target en logaritmo

`ln(Y) = β₀ + β₁X + β₂Z + u`, la forma semi-logarítmica. Follain y Malpezzi (1980), citados por el
artículo, dan tres razones: los coeficientes se leen como cambio porcentual, permite que el valor de
cada atributo varíe con el nivel de precio, y **reduce la heterocedasticidad**.

Implementación: envuelve todo en `TransformedTargetRegressor(func=np.log, inverse_func=np.exp)`. Eso
hace **estructuralmente imposible** el error de evaluar en escala logarítmica: `predict()` devuelve
siempre CLP.

**No apliques corrección de smearing de Duan.** `exp(media de logs)` estima la mediana condicional,
que es exactamente lo que miden MdAPE y PPE10.

### Métricas

Las del estándar IAAO de tasación masiva, **siempre en CLP, nunca en logaritmos**:

| Métrica | Referencia |
|---|---|
| **MdAPE** — error porcentual absoluto mediano | < 15 % bueno, < 10 % excelente |
| **PPE10** — % dentro de ±10 % | > 50 % |
| **COD** — uniformidad | 5 – 15 |
| **PRD** — sesgo vertical | 0,98 – 1,03 |

Se usa la **mediana** y no el promedio porque unos pocos outliers distorsionan cualquier media.

**Verifica tus métricas con un caso de valor conocido** antes de confiar en ellas:
`y=[100,200,300,400]`, `p=[110,180,330,360]` → MdAPE = 10, PPE10 = 100, COD = 10, PRD = 1/0,98.

### División 80/20 agrupada por edificio

El usuario pidió 80/20 explícitamente. Hazlo con `GroupShuffleSplit` agrupando por **coordenada
redondeada a 4 decimales (~11 m)**, con cascada a dirección normalizada y luego a identificador único
para las filas sin geo.

En arriendo esto importa **más** que en venta, porque las 1.303 filas de `cp` no tienen coordenadas y
todas caerían en el fallback.

Mide también la división aleatoria y reporta la diferencia. Puede salir despreciable como en venta.

### Antileakage

- **`precio_uf` y `precio_clp` no pueden entrar como predictores** bajo ninguna forma. En arriendo el
  target es `precio_clp`, así que `precio_uf` es literalmente el target dividido por la UF.
- **`antiguedad_aviso_dias` y `fecha_publicacion` tampoco.** Un aviso lleva 300 días publicado
  *porque* está caro: es consecuencia del precio, no causa. Y son biyectivas entre sí dado
  `fecha_scrape` (que tiene 3 valores).
- Toda imputación debe vivir **dentro** del `Pipeline`, nunca antes del split.
- Usa `remainder="drop"` en el `ColumnTransformer`: si una columna prohibida sobrevive por descuido,
  nunca llega al estimador.
- Añade un `assert` que verifique que ninguna columna prohibida está entre las features.

### Chequeos de sanidad

- **Si el MdAPE sale bajo 5 %, sospecha leakage** y audita antes de celebrar.
- El error debe ser parejo entre comunas. Si una duplica al resto, revisa.
- Revisa el sesgo vertical: si el ratio estimado/real baja al subir el precio, el modelo es regresivo.

---

## 8. TU TAREA — especificación del modelo de arriendo

Crea **`modelo_arriendo.ipynb`**, tomando `modelo_venta.ipynb` como plantilla.

### Diferencias respecto al de venta

| | Venta | **Arriendo** |
|---|---|---|
| Filtro | `operacion='venta'` | **`operacion='arriendo'`** |
| Target | `precio_uf` | **`precio_clp`** |
| Rango válido | 500 – 60.000 UF | **150.000 – 4.000.000 CLP** |
| Rango `m2_util` | 20 – 800 | **15 – 600** |
| n tras filtros | 9.812 | **≈ 5.662** |
| Reparación UF | CLP → UF | **UF → CLP** (55 filas) |
| Problema propio | ninguno | **23 % sin geo ni servicios** |

### Pasos

1. **Carga y limpieza** — idéntica a venta, con los rangos de arriendo. Aplica todas las
   correcciones de la sección 4.
2. **Features** — los tres bloques de Rosen, más `sin_geo` y `sin_servicios` como indicadores.
3. **División 80/20** agrupada por edificio. Mide también la aleatoria y compara.
4. **Compara al menos 5 modelos**: ridge (la log-lineal del artículo, como piso), random_forest,
   hist_gradient, xgboost, lightgbm. Misma envoltura de tres capas.
5. **Métricas IAAO** sobre el 20 % de prueba.
6. **Diagnóstico**: error por comuna, por tipo (casa vs departamento) y **por fuente (`pi` vs `cp`)**.
   Este último es el que decide qué hacer con chilepropiedades.
7. **Importancia por permutación** con `n_jobs=1`, agrupada por bloque hedónico. Compara el aporte
   del bloque vecindario contra el 5 % que dio en venta.
8. **Intervalo calibrado**: cuantiles 10/90 más calibración conforme, con el corte de calibración
   respetando los grupos de edificio. Verifica que la cobertura quede cerca del 80 %.
9. **Función del producto**: `estimar_arriendo(atributos)` que devuelva el arriendo estimado, el
   rango esperado y un nivel de confianza (baja si es casa, si no tiene geo, o si el barrio es
   inédito).
10. **Guardar** `modelos/arriendo.joblib` con el mismo formato que `modelos/venta.joblib`, más su
    ficha `modelos/arriendo.json` con métricas y sesgos declarados.

### Criterios de aceptación

- **MdAPE < 15 %** en el 20 % de prueba. Dado que el arriendo es más predecible que la venta
  (η² 0,489 contra 0,435 y dispersión de partida de 20 % contra 36 %), **debería quedar bajo 10 %**.
  Si sale peor que el de venta, algo está mal.
- **PPE10 > 50 %**
- **COD < 15** y **PRD entre 0,98 y 1,03**
- Cobertura del intervalo cerca del 80 %
- Ninguna columna prohibida entre las features (con `assert`)
- El paquete guardado recarga y predice idéntico

### Lo que NO debes hacer todavía

- No construyas la API ni el endpoint. Solo el notebook.
- No calcules el yield ni el dividendo. Eso viene después, cuando existan los dos modelos.
- No toques `data/ofertas_unificado.sqlite` ni los notebooks existentes.
- No prometas estimar plusvalía: el dataset es una foto de 15 días.

---

## 9. Sesgos que hay que declarar en la ficha del modelo

1. **Precios de publicación, no de cierre.** En Chile el sesgo típico es 5–15 % sobre el valor final.
   El modelo estima «arriendo pedido esperado».
2. **Sesgo de selección invertido.** El dataset es una foto del stock publicado: lo bien valorado se
   arrienda rápido y desaparece, lo sobrevalorado se acumula.
3. **Dos poblaciones distintas** en arriendo: 77 % con datos completos, 23 % con solo cinco campos.
4. **Casi no hay casas**: 200 contra 5.462 departamentos.
5. **Sin dispersión temporal**: 3 fechas de scrape en 15 días, la UF varió 0,16 %. No procede ajuste
   temporal, y deflactar por `fecha_publicacion` sería un error metodológico (confundiría antigüedad
   del aviso con época del precio).
6. **`comercio`, `salud` y `educacion` son proxies de densidad**, no malls, hospitales ni colegios.

---

## 10. Estilo de trabajo esperado

- **Verifica empíricamente antes de afirmar.** En este proyecto varias suposiciones razonables
  resultaron falsas al medirlas: que el split aleatorio inflaría, que Hopkins sería informativo, que
  filtrar por `primaryType` limpiaría los POI. Todas se descartaron con datos.
- **Reporta los resultados negativos.** Si el bloque de vecindario aporta poco, dilo. Si el error en
  chilepropiedades es malo, dilo con el número.
- **Comenta el porqué, no el qué.** El código debe explicar las decisiones no obvias, no narrar lo
  que ya se ve.
- **Ejecuta el notebook antes de darlo por bueno**, con:
  ```
  ./.venv/Scripts/python.exe -m jupyter nbconvert --to notebook --execute --inplace modelo_arriendo.ipynb
  ```
  y verifica que ninguna celda quedó con error ni sin salida.
- Los textos van **en español**, sin tildes dentro del código (comentarios y `print`) para evitar
  problemas de codificación en Windows, pero **con tildes en las celdas markdown**.

---

## 11. Estado del repositorio

```
inmobiliaria/
├── data/
│   ├── ofertas_unificado.sqlite     15.808 x 31, con servicios_cercanos
│   ├── ofertas_unificado.csv        espejo exacto
│   ├── poi_cache.sqlite             3.453 respuestas de Places, ya pagadas
│   └── *.bak-*.sqlite               respaldos, ignorados por git
├── modelos/
│   ├── venta.joblib                 modelo de venta entrenado
│   └── venta.json                   su ficha de métricas
├── clustering.ipynb                 diagnóstico del dataset — NO TOCAR
├── servicios_cercanos.ipynb         extracción de POIs — NO TOCAR
├── modelo_venta.ipynb               modelo de venta — TU PLANTILLA
├── modelo_arriendo.ipynb            <- LO QUE DEBES CREAR
├── PLAN_MODELO_ML.md                plan original del proyecto
└── .env                             claves, fuera de git
```

Rama `modeloML`. Todo commiteado. Haz commits descriptivos al terminar.

---

**Empieza leyendo `modelo_venta.ipynb` completo.** Es tu plantilla y contiene resueltos casi todos
los problemas que te vas a encontrar.
