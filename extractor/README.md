# `extractor/` — datos de un aviso desde su URL

Entra un link de Portal Inmobiliario o MercadoLibre, sale un registro validado y
guardado. Es lo que el MVP necesita: el usuario pega la URL en la web y el
backend obtiene los atributos para pasárselos al análisis.

```bash
./.venv/Scripts/python.exe -m extractor.cli "https://portalinmobiliario.com/MLC-4228882382-arriendo-amplio-departamento-nuevo-2d2b-macul-_JM"
```

Desde código, que es como lo usará la API:

```python
from extractor.servicio import obtener

r = obtener(url)
if r.ok:
    atributos = r.registro          # listo para /estimar
    avisos = r.advertencias         # lo que no se pudo leer, con su motivo
else:
    mostrar_al_usuario(r.error)     # mensaje ya redactado
```

## Por qué no es el scraper de al lado

`scraper/` recorre el portal completo: 16 combinaciones de comuna × operación ×
tipo, paginadas, más 15.258 fichas de detalle en unas nueve horas. Ese volumen es
lo que terminó provocando bloqueos. **Este módulo no rastrea nada**: hace una
petición por URL que el propio usuario aporta. Es otro perfil de tráfico y por eso
no incluye paginación.

`scraper/` queda intacto como referencia. Aquí no se toca.

## Las tres fuentes

Cada campo se busca en tres orígenes independientes, en orden, hasta que uno
responde. Si los tres callan, el campo queda vacío: **ningún valor se adivina.**

| | Origen | Aporta |
|---|---|---|
| 1 | `__NORDIC_RENDERING_CTX__` | el modelo JSON que el servidor ya renderizó |
| 2 | JSON-LD (`schema.org`) | precio, moneda, id y la ruta de categorías |
| 3 | regex sobre el HTML | coordenadas, tabla de specs, descripción, dirección |

Los tres hacen falta de verdad. El portal reconoce al cliente como automatizado
(`"isBot": true`) y le sirve una variante **sin `appProps`**, así que en la
práctica la fuente 1 suele estar vacía y las otras dos cargan con todo. La columna
`fuente` del registro deja constancia de cuál se usó.

## Dos trampas que cuestan caro

**`CLF` es la UF.** El portal publica la moneda con su código ISO. Leerlo como
pesos deja el análisis 40.000 veces mal.

**La latitud del HTML no es la de la propiedad.** La página trae un
`"latitude": -35.675148` que es el centro geográfico de Chile. La coordenada real
solo está en el `center=` de la URL del mapa: confundirlas son ~250 km de error
silencioso.

## Proyectos

Un aviso de proyecto publica rangos: `"1 a 3"` dormitorios, `"21.5 m² a 239.48 m²"`.
Esos campos quedan **nulos** y la fila se marca `es_proyecto = 1`. Nunca se toma el
mínimo del rango — eso es lo que produjo el `m2_util = 21` con `m2_total = 85` que
hoy contamina 422 filas de la base histórica.

El precio y la ubicación sí se conservan: son de la ficha, no de una unidad.

## Cuando algo falla

El fallo es tipado, no `None`. El scraper anterior devolvía `None` para 403, 404,
timeout y fin de paginación por igual, y por eso sus logs no tienen un solo código
HTTP: nunca se supo si el portal bloqueaba o si no había más datos.

| Estado | Qué pasó |
|---|---|
| `ok` | |
| `url_invalida` | no es la ficha de un aviso |
| `challenge` | HTTP 200 pero es la página de verificación humana |
| `bloqueado` | 403/429 tras agotar los reintentos |
| `no_existe` | 404/410, el aviso se dio de baja |
| `red` | timeout o conexión caída |

`challenge` se detecta **sobre HTTP 200**: una ficha real pesa cientos de KB y trae
el bloque de datos; una verificación es corta y no lo trae.

## Trato con el portal

El cliente se identifica con User-Agent propio y URL de contacto. **No imita a un
navegador.** El `robots.txt` de mercadolibre.cl bloquea agentes de IA declarados
(`ClaudeBot`, `GPTBot` y otros), pero su grupo `User-agent: *` no prohíbe las
fichas; el de portalinmobiliario.com solo excluye `/propiedades/`, que no es donde
viven. Si algún día bloquean este User-Agent, se respeta y se migra a la API
oficial de MercadoLibre (`api.mercadolibre.com/items/{id}`, hoy 403 sin
autenticar, requiere registrar una aplicación).

Hay caché en disco por aviso con TTL de 24 h: reanalizar el mismo link no vuelve a
pedirle la página al portal.

## Dónde se guarda

`data/consultas_usuario.sqlite`, **aparte** de la base de entrenamiento. Los avisos
que trae un usuario no deben mezclarse en silencio con el dataset con el que se
entrenaron los modelos; si algún día se reentrena con ellos, que sea una decisión
explícita.

## Verificación

```bash
./.venv/Scripts/python.exe -m pytest tests/test_extractor.py -v
```

36 casos sobre HTML real guardado y comprimido en `tests/fixtures/`. Corren
offline: no le piden nada al portal, pero prueban contra lo que el portal entrega
de verdad. Los tres fixtures son una casa en venta de MercadoLibre, un
departamento en arriendo de Portal Inmobiliario y un proyecto con rangos.
