# Tasación inmobiliaria automatizada — Macul, La Florida, Ñuñoa y San Miguel

Este repositorio contiene el proceso completo: la extracción de avisos desde Portal
Inmobiliario, la base de datos resultante, los dos modelos de machine learning que se
entrenaron con ella y la API que los expone.

El objetivo del proyecto es responder tres preguntas sobre una propiedad publicada:
cuánto debería valer, en cuánto se podría arrendar y, con esas dos cifras, si conviene
como inversión. Las dos primeras están resueltas y son las que documenta este archivo.

## Contenido

```
api/                  servicio HTTP que expone los modelos
modelos/              los dos modelos entrenados y sus fichas de métricas
data/                 la base de avisos y la caché de Google Places
scraper/              extracción masiva del portal
extractor/            extracción de un aviso a partir de su link
tests/                pruebas del extractor, con HTML real guardado
qa/                   auditoría de extremo a extremo de los modelos
*.ipynb               diagnóstico del dataset y entrenamiento de los modelos
resumen_dataset.py    reporte del estado de la base del scraper
Dockerfile, .do/      despliegue
```

## Puesta en marcha

Requiere Python 3.14. Las versiones del `requirements.txt` están ancladas a esa versión
porque los modelos serializados solo garantizan cargar con la misma versión de
scikit-learn con la que se guardaron.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn api.main:app --reload
```

En Linux o macOS son `.venv/bin/pip` y `.venv/bin/python`. El servicio queda en
`http://127.0.0.1:8000` y la documentación interactiva en `/docs`.

Si solo se va a consumir la API y no a reentrenar ni a scrapear, basta con
`pip install -r api/requirements.txt`, que trae nueve librerías en vez de todas.

Para comprobar que quedó bien:

```bash
curl -s localhost:8000/salud
```

---

# 1. Los datos

## De dónde salen

Todos los avisos vienen de Portal Inmobiliario. Se recolectaron 16 búsquedas: cuatro
comunas por dos operaciones (venta y arriendo) por dos tipos (casa y departamento). El
resultado es `data/ofertas_unificado.sqlite`, con 15.808 filas y 31 columnas, más su
espejo en CSV para abrirlo con pandas o Excel.

La base es una fotografía del stock publicado en tres fechas de captura repartidas en
quince días. Eso condiciona lo que se puede y no se puede modelar, y está detallado en la
sección de límites.

## Dos convenciones de la base

Hay dos cosas que conviene saber antes de consultarla, porque saltárselas produce errores
silenciosos.

La primera es que las celdas vacías contienen el texto `SIN_DATO`, no `NULL`. La segunda
es que todas las columnas están tipadas como `TEXT`, incluidos los números. El orden para
limpiarla importa: primero se reemplaza el centinela por nulo y después se castea. Al
revés no hay forma de distinguir un faltante legítimo de un valor que no parsea.

```python
df = crudo.replace("SIN_DATO", pd.NA)
for c in NUMERICAS:
    df[c] = pd.to_numeric(df[c], errors="coerce")
```

Por lo mismo, nunca hay que hacer `CAST(columna AS REAL)` en SQL sin filtrar antes:
SQLite devuelve `0.0` para `SIN_DATO` y eso contamina cualquier mediana sin avisar.

## Las columnas

| Grupo | Columnas |
|---|---|
| Identificación | `sitio`, `id_aviso`, `url`, `titulo`, `fecha_scrape` |
| Clasificación | `operacion`, `tipo` |
| Ubicación | `comuna`, `barrio`, `direccion`, `lat`, `lon` |
| Precio | `precio_valor`, `precio_moneda`, `precio_clp`, `precio_uf` |
| Superficie | `m2_util`, `m2_total` |
| Características | `dormitorios`, `banos`, `estacionamientos`, `bodegas` |
| Antigüedad | `antiguedad_anos`, `ano_construccion` |
| Costos | `gastos_comunes_clp` |
| Aviso | `antiguedad_aviso_dias`, `fecha_publicacion`, `publica`, `descripcion` |
| Entorno | `servicios_cercanos` |
| Control | `detalle_ok` |

## La columna de servicios cercanos

Es un JSON por fila, construido con la API de Google Places, con siete categorías. Cada
una trae la distancia al más cercano y cuántos hay en un kilómetro.

```json
{
  "metro":        {"mas_cercano_m": 552, "nombre": "Francisco Bilbao", "n_1km": 2},
  "supermercado": {"mas_cercano_m": 126, "nombre": "...", "n_1km": 4},
  "_truncado": true
}
```

Tres advertencias sobre esta columna.

La distancia es exacta, porque la API devuelve los lugares ordenados por cercanía y el
más próximo nunca queda fuera del corte. El conteo `n_1km`, en cambio, está censurado en
zonas densas: la API tope en 20 resultados y el 95,6 por ciento de los puntos lo alcanzó.
Por eso existe la bandera `_truncado`, que entra al modelo como variable para que sepa
cuándo el conteo es un piso y no el total.

Los nombres de las categorías describen lo que el dato mide de verdad, no lo que promete
el tipo de Google. Los tipos los aportan los usuarios y son muy laxos: una barbería
aparece como `shopping_mall` y un veterinario como `hospital`. Se filtró por número de
reseñas y aun así pasan negocios medianos, así que las categorías se llaman comercio,
salud y educación en vez de mall, hospital y colegio. La única fiable es metro: las 125
estaciones del catálogo son todas reales.

## Cómo se consultó Google Places

El proceso está en `servicios_cercanos.ipynb` y trabaja en dos niveles según si el
servicio es escaso o denso.

Los escasos tienen ubicación fija y son pocos, así que se enumeran una sola vez para toda
la ciudad con una grilla de 6 por 6 puntos y radio de 4.500 metros. Quedan guardados en la
tabla `catalogo` de `data/poi_cache.sqlite`: 125 estaciones de metro, 153 comercios, 117
centros de salud y 67 universidades. Para estas cuatro categorías la distancia se calcula
en local, sin volver a llamar a Google. Cada categoría se consulta con los dos
ordenamientos que ofrece la API, por distancia y por popularidad, porque uno trae lo
cercano aunque sea modesto y el otro lo importante aunque quede algo más lejos.

Los densos son educación, parques y supermercados. Hay demasiados para catalogarlos, así
que se consulta uno por punto con radio de 1.200 metros. Deduplicando las coordenadas en
una grilla de tres decimales, unos 110 metros, los 15.808 avisos colapsan a 3.453 puntos
únicos, que es un ahorro del 76 por ciento. Esas respuestas quedan cacheadas en la tabla
`puntos` del mismo archivo, así que el costo total fue de cero dólares y no hace falta
volver a consultar la API.

---

# 2. Extracción de avisos

Hay dos módulos y hacen cosas distintas. El primero recorre el portal completo para
construir el dataset; el segundo lee un aviso concreto que aporta el usuario.

## scraper — extracción masiva

Está pensado alrededor de una idea: separar lo barato de lo caro. Una página de listado
entrega 48 avisos por petición; una ficha de detalle entrega uno. Por eso el proceso son
dos pasadas independientes.

La pasada de listados recorre las páginas de resultados de las 16 búsquedas y tarda unos
40 minutos. Extrae de cada tarjeta el identificador, el título, el precio, los atributos
básicos y la ubicación. Las tarjetas sin link de MercadoLibre son publicidad y se
descartan. La pasada de detalle visita la ficha de cada aviso y tarda alrededor de nueve
horas; de ahí salen la tabla de especificaciones, las coordenadas, la fecha de
publicación y la descripción.

Cuatro decisiones sostienen el diseño:

La base de datos es la cola de trabajo. La pasada de detalle consulta
`WHERE detalle_ok = 0`, así que el estado vive en disco y no en memoria. El proceso se
puede interrumpir con Ctrl+C y relanzar sin perder nada.

El guardado es idempotente. La tabla tiene clave primaria compuesta `(sitio, id_aviso)` y
el insert usa `ON CONFLICT ... DO UPDATE` sobre los campos de tarjeta solamente. Correr el
listado dos veces no duplica nada; de hecho repara datos y captura avisos nuevos sin tocar
lo que ya se extrajo del detalle.

Nunca se degrada un dato. Un valor solo reemplaza al anterior si parsea a número. No se
pisa un dato bueno con un vacío.

El commit va cada 25 fichas. Si el proceso muere se pierde como máximo un minuto de
trabajo.

El parseo usa httpx para descargar y BeautifulSoup con lxml para navegar el HTML. No hace
falta navegador automatizado porque el portal entrega el HTML ya renderizado desde el
servidor. Entre peticiones hay una pausa aleatoria de 1,5 a 2,5 segundos, y ante un 403 o
un 429 espera 5, 10 y 15 segundos antes de reintentar.

```bash
# proceso completo
python -m scraper.run --sitio pi

# solo listados, para refrescar precios y capturar avisos nuevos
python -m scraper.run --sitio pi --solo-listado

# solo fichas pendientes
python -m scraper.run --sitio pi --solo-detalle

# prueba acotada
python -m scraper.run --sitio pi --comuna nunoa --operacion venta --tipo casa --max-paginas 1

# exportar el CSV y ver conteos
python -m scraper.run --export
```

El scraper escribe en `data/ofertas.sqlite`, que es su propia base de trabajo y se genera
al ejecutarlo. La base que está versionada en este repositorio es
`data/ofertas_unificado.sqlite`, que es el resultado ya consolidado y enriquecido con los
servicios cercanos, y es la que usan los notebooks.

`resumen_dataset.py` imprime el estado de la base del scraper y se puede correr incluso
mientras el proceso está en marcha.

## extractor — un aviso desde su link

Este módulo es lo que necesita el producto: el usuario pega una URL y el backend obtiene
los atributos para pasárselos a la API de tasación. No rastrea nada, hace una petición por
URL que el propio usuario aporta.

```bash
python -m extractor.cli "https://portalinmobiliario.com/MLC-4228882382-arriendo-..."
```

Desde código, que es como lo usa el backend:

```python
from extractor.servicio import obtener

r = obtener(url)
if r.ok:
    atributos = r.registro       # listo para mandarlo a /estimar
    avisos = r.advertencias      # lo que no se pudo leer, con su motivo
else:
    mostrar_al_usuario(r.error)  # mensaje ya redactado
```

Cada campo se busca en tres orígenes independientes, en orden, hasta que uno responde. Si
los tres callan el campo queda vacío; ningún valor se adivina.

| Orden | Origen | Aporta |
|---|---|---|
| 1 | `__NORDIC_RENDERING_CTX__` | el modelo JSON que el servidor ya renderizó |
| 2 | JSON-LD de schema.org | precio, moneda, identificador y ruta de categorías |
| 3 | expresiones regulares sobre el HTML | coordenadas, tabla de specs, descripción, dirección |

Los tres hacen falta. El portal reconoce al cliente como automatizado y le sirve una
variante sin `appProps`, así que en la práctica la primera fuente suele venir vacía y las
otras dos cargan con todo. La columna `fuente` del registro deja constancia de cuál se
usó.

Hay dos trampas que costaron caro y conviene tener presentes. La primera es que `CLF` es
el código ISO de la UF: leerlo como pesos deja el análisis 40.000 veces mal. La segunda es
que la latitud que trae el HTML no es la de la propiedad, sino el centro geográfico de
Chile; la coordenada real solo está en el parámetro `center=` de la URL del mapa embebido,
y confundirlas son unos 250 kilómetros de error silencioso.

Los avisos de proyecto, que son edificios nuevos donde una ficha agrupa varias unidades,
publican rangos del tipo "1 a 3" dormitorios o "21.5 m² a 239.48 m²". Esos campos quedan
nulos y la fila se marca con `es_proyecto = 1`. Nunca se toma el mínimo del rango: eso es
lo que produjo los `m2_util = 21` con `m2_total = 85` que contaminan 422 filas de la base
histórica. El precio y la ubicación sí se conservan porque son de la ficha y no de una
unidad.

El fallo es tipado y no un `None` genérico, porque el scraper anterior devolvía lo mismo
para un 403, un 404, un timeout y un fin de paginación, y por eso nunca se supo si el
portal estaba bloqueando o si simplemente no había más datos.

| Estado | Qué pasó |
|---|---|
| `ok` | |
| `url_invalida` | no es la ficha de un aviso |
| `challenge` | HTTP 200 pero llegó la página de verificación humana |
| `bloqueado` | 403 o 429 tras agotar los reintentos |
| `no_existe` | 404 o 410, el aviso se dio de baja |
| `red` | timeout o conexión caída |

El estado `challenge` se detecta sobre un HTTP 200: una ficha real pesa cientos de
kilobytes y trae el bloque de datos, mientras que una verificación es corta y no lo trae.

El cliente se identifica con User-Agent propio y URL de contacto, sin imitar a un
navegador. Hay caché en disco por aviso con vencimiento de 24 horas, así que reanalizar el
mismo link no vuelve a pedirle la página al portal. Los resultados se guardan en
`data/consultas_usuario.sqlite`, aparte de la base de entrenamiento: los avisos que trae
un usuario no deben mezclarse en silencio con el dataset con el que se entrenaron los
modelos.

```bash
python -m pytest tests/test_extractor.py -v
```

Son 36 casos sobre HTML real guardado y comprimido en `tests/fixtures/`. Corren offline,
no le piden nada al portal, pero prueban contra lo que el portal entrega de verdad. Los
tres fixtures son una casa en venta de MercadoLibre, un departamento en arriendo de Portal
Inmobiliario y un proyecto con rangos.

---

# 3. Los modelos

## Qué estiman

Son dos modelos independientes. El de venta estima el precio en UF y el de arriendo el
precio mensual en pesos. Van separados porque los objetivos tienen escalas incomparables,
miles de UF contra cientos de miles de pesos, y porque ninguna propiedad está publicada a
la vez en venta y en arriendo.

## Antes de modelar: ¿sirve la base?

`clustering.ipynb` responde esa pregunta antes de entrenar nada. El método es agrupar las
propiedades usando once atributos sin dejar que el algoritmo vea el precio, y después
medir si los grupos resultantes tienen precios distintos.

El estadístico de Hopkins dio 0,979 en venta y 0,985 en arriendo, valores que sugerirían
un agrupamiento clarísimo. Pero al repetirlo con las columnas barajadas por separado, que
destruye toda relación entre variables y conserva solo sus distribuciones, dio 0,958 y
0,973. La diferencia es de dos y una centésima, así que Hopkins no estaba midiendo
estructura sino la asimetría de las distribuciones, y se descartó. Queda documentado como
resultado negativo.

El PCA mostró que hacen falta 6 de 11 componentes en venta y 7 de 11 en arriendo para
llegar al 80 por ciento de la varianza, o sea que los atributos aportan información
independiente y hay poca redundancia.

La silueta se queda entre 0,20 y 0,37 en venta y entre 0,22 y 0,64 en arriendo, pero en
ambos casos cae a 0,22 en cuanto los grupos pasan de dos. No hay segmentos discretos, hay
un continuo. Eso favorece un modelo de regresión único por conjunto en vez de uno por
segmento.

La prueba que decide es el eta cuadrado: la pertenencia a un grupo formado sin ver el
precio explica el 43,5 por ciento de la varianza del logaritmo del precio en venta y el
48,9 por ciento en arriendo. Cohen considera 0,14 un efecto grande, así que ambos están
tres veces por encima. Agrupando al azar se obtiene 0,0004. La comuna por sí sola explica
0,209 y 0,181, lo que confirma que la ubicación tiene señal propia y que las coordenadas
crudas bastan para capturarla.

La conclusión es que los dos conjuntos sirven, y que el arriendo es más predecible que la
venta: predecir con la mediana global ya da 20 por ciento de error en arriendo contra 36
por ciento en venta, porque los arriendos están más estandarizados.

## Marco teórico

Se sigue el marco hedónico que revisa Owusu-Ansah (2011). La idea de Rosen (1974) es que
una vivienda no se transa como un objeto único sino como un paquete de atributos, y que el
precio observado revela los precios implícitos de cada uno. Como esos atributos no se
transan por separado, se estiman por regresión.

El artículo agrupa los atributos en tres bloques, y el dataset tiene los tres:

| Bloque | Variables |
|---|---|
| Estructural | superficie útil y total, dormitorios, baños, estacionamientos, bodegas, antigüedad, gastos comunes |
| Ubicación | latitud, longitud, comuna |
| Vecindario | las siete categorías de servicios cercanos |

El objetivo va en logaritmo, que es la forma semilogarítmica que el artículo describe como
la más empleada. Citando a Follain y Malpezzi (1980), tiene tres ventajas: los
coeficientes se leen como cambio porcentual, permite que el valor de cada atributo varíe
con el nivel de precio y reduce la heterocedasticidad. Todo el pipeline va envuelto en un
`TransformedTargetRegressor`, de modo que `predict()` devuelve siempre la unidad original
y es estructuralmente imposible evaluar en escala logarítmica por descuido.

No se aplica corrección de smearing de Duan. La exponencial de la media de logaritmos
estima la mediana condicional, que es exactamente lo que miden las métricas que se usan.

## Cómo se entrenaron

La división es 80/20 agrupada por edificio, no aleatoria por filas. El 62 por ciento de
los avisos comparte coordenada exacta con otro porque son departamentos de la misma torre,
y con una división aleatoria casi toda torre grande quedaría partida entre entrenamiento y
prueba: el modelo podría acertar por haber memorizado esa torre en vez de haber entendido
el mercado. El agrupador es la coordenada redondeada a cuatro decimales, unos 11 metros,
con cascada a dirección normalizada para las filas sin geo.

Se midieron las dos divisiones para saber cuánto infla la aleatoria. En venta la
diferencia quedó dentro del ruido, contra lo que se esperaba; en arriendo sí infla 0,56
puntos. En ambos casos se reporta la agrupada.

Se compararon cinco algoritmos con la misma envoltura: una regresión Ridge log-lineal, que
es el modelo del artículo y sirve de piso, random forest, y tres variantes de gradient
boosting. La imputación vive dentro del pipeline, nunca antes de dividir, para que la
mediana del conjunto de prueba no se filtre al de entrenamiento, y el `ColumnTransformer`
usa `remainder="drop"` para que ninguna columna no declarada llegue al estimador por
descuido.

Los modelos de árbol reciben los valores faltantes sin imputar porque los manejan de forma
nativa y aprenden hacia qué lado mandarlos. Eso es lo que hace viable entrenar el modelo
de arriendo con sus dos fuentes juntas, y es también la razón de que Ridge parta en
desventaja en ese conjunto: al imputarle la mediana al 23 por ciento sin coordenadas se le
está inventando una ubicación.

Ninguna forma del precio puede entrar como predictor. Tampoco `antiguedad_aviso_dias` ni
`fecha_publicacion`, porque un aviso lleva 300 días publicado a causa de estar caro: son
consecuencia del precio, no causa. Tampoco `sitio`, que sería predictiva pero la API no
puede saber de qué portal vendría un aviso nuevo. Los notebooks llevan un `assert` que lo
verifica.

## Resultados

Medidos sobre el 20 por ciento de prueba, con edificios que el modelo nunca vio. Las
referencias son las del estándar IAAO de tasación masiva.

| | Venta | Arriendo | Referencia |
|---|---|---|---|
| MdAPE | 8,78 % | 7,75 % | menos de 10 % es excelente |
| PPE10 | 55,4 % | 59,9 % | sobre 50 % |
| COD | 12,2 | 11,6 | entre 5 y 15 |
| PRD | 1,029 | 1,032 | entre 0,98 y 1,03 |
| Cobertura del rango | 78,7 % | 81,2 % | 80 % |
| Algoritmo ganador | hist_gradient | xgboost | |
| Avisos usados | 9.812 | 5.662 | |

El MdAPE es el error porcentual absoluto mediano: la mitad de las estimaciones se equivoca
menos que esa cifra. El PPE10 es el porcentaje que cae dentro de un más menos 10 por
ciento. El COD mide uniformidad, es decir si el modelo acierta parejo o solo en promedio
compensando errores en direcciones opuestas. El PRD mide equidad vertical: por encima de
1,03 el modelo es regresivo, sobrevalora lo barato y subvalora lo caro.

Se usa la mediana y no el promedio porque unas pocas propiedades atípicas distorsionan
cualquier media, y todas las métricas se calculan en UF o en pesos, nunca en logaritmos.

El único criterio fuera de rango es el PRD del modelo de arriendo, con 1,032 contra un
máximo de 1,03. No es un descuido: se probaron cinco variantes de algoritmo y de forma
funcional y ninguna bajó de 1,031. La regresividad es del dataset y no del algoritmo,
porque el tramo caro es delgado y heterogéneo y ahí cualquier modelo contrae hacia la
media. Está declarado en la ficha del modelo.

## Qué variables pesan

La importancia se mide por permutación sobre el conjunto de prueba: se desordena una
columna a la vez y se mide cuánto empeora el error mediano. A diferencia de la importancia
interna del árbol, no premia a las variables con muchos valores distintos.

En venta el reparto por bloque queda en 71 por ciento estructural, 24 por ciento ubicación
y 5 por ciento vecindario. Las dos superficies dominan con distancia, y la latitud vale
siete veces más que la longitud, lo que refleja que Santiago se estratifica de norte a sur
mucho más que de este a oeste. La comuna aporta poco, no porque no importe sino porque las
coordenadas ya contienen esa información con más resolución.

En arriendo el bloque de vecindario sube al 10 por ciento, que es coherente con que quien
arrienda usa el barrio a diario y no compra plusvalía futura. Aun así sigue siendo el
bloque menor de los tres.

## El rango, no solo un número

Decir que una propiedad vale 3.450 UF es falsa precisión cuando el modelo se equivoca un
8,8 por ciento de forma habitual. Por eso cada estimación viene con un intervalo.

Se entrenan dos modelos adicionales con regresión cuantílica, percentiles 10 y 90. La
regresión cuantílica cambia el error cuadrático por una función de pérdida asimétrica que
penaliza nueve veces más pasarse que quedarse corto, de modo que el óptimo es una curva
que deja el 10 por ciento de los puntos por debajo. El método viene de Koenker y Bassett
(1978) y la implementación es la misma clase de scikit-learn con `loss="quantile"`.

Sola no basta. El intervalo prometía cubrir el 80 por ciento de los casos y cubría el 66,1
por ciento en venta y el 65,1 por ciento en arriendo, que es el problema conocido de la
regresión cuantílica fuera de muestra. Por eso se aplica encima una calibración conforme
siguiendo a Romano, Patterson y Candès (2019): se aparta un trozo del entrenamiento que
los modelos cuantílicos no ven, se mide en él cuánto se queda corto el intervalo y se
ensancha esa cantidad a cada lado. La cobertura sube a 78,7 y 81,2 por ciento, y el ancho
pasa del 28 al 39 por ciento del precio. Ese ensanchamiento es el precio de que la
cobertura sea real.

## Reentrenar

Solo hace falta si cambian los datos. La base viene en el repositorio y la semilla está
fijada, así que las métricas salen idénticas.

```
clustering.ipynb           diagnóstico previo, no produce artefactos
servicios_cercanos.ipynb   construye la columna de servicios cercanos
modelo_venta.ipynb         entrena y guarda modelos/venta.joblib y venta.json
modelo_arriendo.ipynb      entrena y guarda modelos/arriendo.joblib y arriendo.json
```

Los dos notebooks de modelo terminan con una celda para pegar los datos de un aviso y
obtener la estimación sin levantar la API.

---

# 4. La API

Es un solo servicio que expone los dos modelos. Un aviso tiene los mismos atributos para
ambos, así que separarlos obligaría a mandar dos veces el mismo JSON y a levantar dos
procesos para nada.

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/salud` | Carga los dos modelos y devuelve sus métricas. Sirve de health check. |
| GET | `/modelos/venta` y `/modelos/arriendo` | La ficha completa: métricas, variables y sesgos declarados. |
| POST | `/estimar` | Las dos estimaciones para una propiedad. |

## POST /estimar

De todos los atributos solo `m2_util` es obligatorio. Lo que falte se trata como faltante,
que no es lo mismo que cero, y baja el nivel de confianza que devuelve la respuesta.

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

`precio_pedido_uf` es opcional. Si se envía aparece `juicio_de_precio`; si no, la respuesta
trae solo las dos estimaciones.

## Los campos de entrada

| Campo | Notas |
|---|---|
| `m2_util` | Obligatorio. Superficie interior, sin terraza. |
| `tipo` | `departamento` por defecto, o `casa`. |
| `comuna` | `nunoa`, `macul`, `la-florida`, `san-miguel`. Se normaliza sola, así que "Ñuñoa" también funciona. |
| `m2_total`, `dormitorios`, `banos` | Opcionales. |
| `estacionamientos`, `bodegas` | Opcionales. Omitir no es lo mismo que enviar cero. |
| `ano_construccion` | El año, no la antigüedad. |
| `gastos_comunes_clp` | Solo departamentos. |
| `lat`, `lon` | Opcionales pero recomendados. |
| `servicios_cercanos` | Opcional. El JSON de Places. Sin él se pierde el bloque de vecindario. |

## Cómo leer la respuesta

`valor` es la estimación puntual y `rango` contiene el valor real cerca del 80 por ciento
de las veces, calibrado sobre propiedades que el modelo nunca vio.

`error_tipico_pct` es el error del segmento al que pertenece la propiedad, no el global.
Sube a 11,8 por ciento en casas y a 9,9 por ciento en avisos sin coordenadas.

`confianza` vale alta, media o baja, y `motivos_menor_confianza` explica por qué bajó. Se
degrada si es casa, si faltan coordenadas, si el barrio no aparece en el entrenamiento o
si la comuna está fuera de cobertura.

`errores_tipicos` es el campo que manda dentro de `juicio_de_precio`: la brecha medida en
errores típicos del modelo. Si el modelo falla un 8,8 por ciento de forma habitual, una
diferencia del 5 por ciento no significa nada. Los cortes son de uno y dos errores
típicos, no números redondos.

## Consumirla desde otro backend

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

La primera petición paga la carga de los modelos, un par de segundos. Después quedan
cacheados en el proceso y cada estimación es de milisegundos.

## Cómo está construida por dentro

Son tres archivos y un orden de dependencia claro.

`api/features.py` construye las variables a partir de los atributos crudos. Es la pieza
delicada: define exactamente lo que esperan los modelos ya entrenados, incluida la
expansión del JSON de servicios cercanos en sus columnas numéricas y las transformaciones
logarítmicas de las distancias. Cambiarla invalida los modelos guardados, porque el
pipeline serializado empieza después de este paso. El QA la compara contra los notebooks
columna a columna en cada corrida.

`api/modelos.py` carga los paquetes `.joblib` y produce la estimación. Cada paquete trae
el estimador puntual, los dos cuantílicos, la corrección conforme, la lista de variables
en su orden exacto, los errores por segmento y la UF de referencia. Aquí se corrigen dos
cosas que la auditoría encontró en los artefactos crudos: que el rango contenga siempre a
su propia estimación puntual, que en los notebooks no está garantizado porque los modelos
cuantílicos se entrenan aparte, y que la comuna se normalice al formato que vio el modelo,
porque si llega "Ñuñoa" sin normalizar el codificador la trata como categoría desconocida
y la estimación pierde el bloque de ubicación sin avisar.

`api/main.py` define los tres endpoints y los esquemas de entrada con Pydantic.

## Despliegue

```bash
docker build -t tasacion-api .
docker run -p 8080:8080 tasacion-api
```

El contenedor expone el puerto 8080. El Dockerfile instala `libgomp1` a propósito, porque
XGBoost lo necesita para OpenMP y sin él el import falla en tiempo de ejecución y no en el
build. Para DigitalOcean App Platform el spec está en `.do/app.yaml`, apuntando a esta
rama; una instancia `basic-xxs` de 512 MB alcanza, porque los modelos ocupan unos 10 MB en
disco y el proceso se estabiliza bajo 400 MB.

Docker es también la vía recomendada para quien no tenga Python 3.14, porque fija el
entorno completo.

## Verificación antes de desplegar

```bash
python qa/qa_modelos.py
```

No es un test unitario. Reproduce la preparación de datos de ambos notebooks desde cero,
recarga los modelos guardados y comprueba que devuelven las mismas métricas que declara su
ficha. Además verifica que la base y su espejo en CSV coinciden, que la UF empírica sigue
siendo la misma, que ninguna columna prohibida entró como variable, que colar una columna
con el precio no altera la predicción, que el precio sube con la superficie, que el
módulo de features produce lo mismo que los notebooks y que la API responde. Devuelve
código de salida distinto de cero si algo falla.

---

# 5. Límites y sesgos

Estos son los que hay que declarar aguas arriba, en cualquier informe que use estas
cifras.

Las estimaciones son de precio pedido, no de cierre. En Chile el cierre suele quedar entre
un 5 y un 15 por ciento por debajo. El modelo estima precio pedido esperado.

Hay un sesgo de selección invertido. El dataset es una fotografía del stock publicado: lo
bien valorado se transa rápido y desaparece, lo sobrevalorado se acumula.

La cobertura geográfica son cuatro comunas. Fuera de ellas la estimación es extrapolación
y la API lo marca bajando la confianza.

El conjunto de arriendo tiene dos poblaciones. El 77 por ciento viene de Portal
Inmobiliario con datos completos y el 23 por ciento de otra fuente que solo aporta comuna,
tipo, superficie útil, dormitorios y baños, sin coordenadas ni antigüedad ni gastos
comunes. Se decidió entrenar con todo y declarar la ausencia mediante dos variables
indicadoras en vez de descartar un cuarto del conjunto. Medido después, el error en esa
fuente es de 9,9 por ciento contra 7,3 por ciento en la otra: peor, pero no lo suficiente
para excluirla.

Casi no hay casas en arriendo, 200 contra 5.462 departamentos, y en venta las casas se
estiman un 42 por ciento peor que los departamentos. Sus estimaciones salen marcadas de
confianza baja.

No hay dispersión temporal. Son tres fechas de captura en quince días, durante los cuales
la UF varió un 0,16 por ciento. No procede ajuste temporal, y deflactar por fecha de
publicación sería un error metodológico porque confundiría antigüedad del aviso con época
del precio.

Los modelos no estiman plusvalía. Con una fotografía de quince días no se puede, y las
tres secciones que traen los informes comerciales de tasación (evolución histórica, tiempo
esperado de colocación y transacciones efectivas del Conservador) exigen series de varios
años o registros de cierre que este dataset no tiene.

Las búsquedas con más de 2.016 resultados quedaron truncadas en ese tope, que es el límite
de paginación del portal. Afecta a departamentos en venta de Ñuñoa y San Miguel.

Puede existir la misma propiedad publicada por dos corredoras con identificadores
distintos. La deduplicación es por identificador de aviso, así que esos casos se detectan
en la limpieza comparando dirección, superficie y precio.

---

# Referencias

Rosen, S. (1974). Hedonic Prices and Implicit Markets. Journal of Political Economy 82(1).

Owusu-Ansah, A. (2011). A Review of Hedonic Pricing Models in Housing Research. Journal of
International Real Estate and Construction Studies 1(1).

IAAO. Standard on Ratio Studies (2013). Define MdAPE, COD, PRD y sus rangos aceptables.

Friedman, J. (2001). Greedy Function Approximation: A Gradient Boosting Machine. Annals of
Statistics 29(5).

Ke, G. et al. (2017). LightGBM: A Highly Efficient Gradient Boosting Decision Tree. NeurIPS.
Es la idea de histogramas que implementa HistGradientBoostingRegressor.

Breiman, L. (2001). Random Forests. Machine Learning 45(1). Origen de la importancia por
permutación.

Koenker, R. y Bassett, G. (1978). Regression Quantiles. Econometrica 46(1).

Romano, Y., Patterson, E. y Candès, E. (2019). Conformalized Quantile Regression. NeurIPS.
