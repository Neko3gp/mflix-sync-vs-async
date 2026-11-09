# Proyecto 2a Evaluación: base de datos asíncrona vs síncrona (MongoDB + Python)

## Objetivo

Administrar la colección `movies` de la base `sample_mflix` con dos aplicaciones
equivalentes y compararlas:

- **App asíncrona** (`async_app.py`): PyMongo Async con `AsyncMongoClient`.
- **App síncrona** (`sync_app.py`): PyMongo con `MongoClient`.

Cada app ofrece carga masiva, CRUD y consultas. `comparacion.py` mide las dos.

## Requisitos e instalación

- Python 3.11 o superior (`asyncio.TaskGroup` no existe antes).
- Un MongoDB que tenga la base `sample_mflix` (ver abajo).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Conexión

Por defecto se conecta a `mongodb://localhost:27017`. Para usar otro servidor
(por ejemplo Atlas), define la variable de entorno antes de ejecutar:

```bash
export MONGO_URI="mongodb+srv://USUARIO:CONTRASENA@CLUSTER.mongodb.net/"
```

### Datos de `sample_mflix`

- **Atlas:** en el clúster, *Load Sample Dataset*.
- **MongoDB local:** descargar el archivo oficial de datos de ejemplo y restaurar
  solo esa base ([guía](https://www.mongodb.com/docs/manual/sample-data/load-sample-data-local/)):

```bash
curl https://atlas-education.s3.amazonaws.com/sampledata.archive -o sampledata.archive
mongorestore --archive=sampledata.archive --nsInclude="sample_mflix.*"
```

## Ejecución

```bash
python sync_app.py       # demostración de la app síncrona
python async_app.py      # demostración de la app asíncrona
python comparacion.py    # comparación entre las dos (tarda varios minutos)
```

Cada demostración lee las películas de `sample_mflix.movies`, las copia a su propia
base (`mflix_sync` o `mflix_async`) con carga masiva, ejecuta un ciclo CRUD y corre
las consultas. **`sample_mflix` nunca se modifica**: solo se lee.

## Estructura

```text
sync_app.py      App síncrona: carga masiva, CRUD, consultas
async_app.py     App asíncrona: las mismas funciones con async/await
comparacion.py   Comparación de tiempos entre ambas
requirements.txt Dependencias (solo pymongo)
```

Las dos apps tienen las mismas funciones con los mismos nombres:

| Funcionalidad | Función |
|---|---|
| Carga masiva | `load_movies_bulk` |
| Crear / Leer / Actualizar / Eliminar | `create_movie`, `get_movie`, `update_movie`, `delete_movie` |
| Filtro + proyección + orden (año y género) | `find_movies_by_year_and_genre` |
| Agregación (top 5 de géneros) | `aggregate_movies_by_genre` |
| Búsqueda por texto en el título (regex) | `search_movies_by_regex` |
| Las tres consultas juntas | `run_queries` (sync), `run_queries_gather` y `run_queries_taskgroup` (async) |

## Dónde está lo que pide la actividad

| Requisito | Ubicación |
|---|---|
| `AsyncMongoClient` | `async_app.py`, `get_client()` |
| `bulk_write()` | `load_movies_bulk` en `async_app.py` y en `sync_app.py` (`ordered=False`: un `_id` duplicado no detiene el lote) |
| `asyncio.Semaphore` | `load_movies_bulk` en `async_app.py`: limita a 10 los lotes que escriben a la vez |
| `asyncio.TaskGroup()` | `load_movies_bulk` (lanza todos los lotes) y `run_queries_taskgroup` en `async_app.py` |
| `asyncio.gather()` | `run_queries_gather` en `async_app.py`: las tres consultas independientes al mismo tiempo |
| CRUD asíncrono | `create_movie`, `get_movie`, `update_movie`, `delete_movie` en `async_app.py` |
| Consultas asíncronas | `find_movies_by_year_and_genre`, `aggregate_movies_by_genre`, `search_movies_by_regex` en `async_app.py` |
| App síncrona con PyMongo | `sync_app.py` |
| Comparación | `comparacion.py` y la sección de resultados de este documento |

### Detalles de PyMongo Async

Según el [tutorial de PyMongo 4.14.1](https://pymongo.readthedocs.io/en/4.14.1/async-tutorial.html)
y la [guía de async-concurrency](https://www.async-concurrency.com/network-io-protocol-handling/async-database-drivers/using-mongodb-with-pymongo-async/):

- `find()` devuelve un cursor sin `await`; se lee con `await cursor.to_list()`.
- `aggregate()` sí se espera con `await` y devuelve el cursor.
- Se crea **un solo cliente** y se reutiliza; al terminar, `await client.close()`.
- El `Semaphore` evita lanzar más operaciones simultáneas que conexiones disponibles.
- `bulk_write(..., ordered=False)` sigue insertando aunque un documento falle.

## Resultados

Mediciones con los parámetros de `comparacion.py` (2000 películas en 20 lotes de
100, media de 3 repeticiones tras una de calentamiento), contra un clúster Atlas
M0, por lo que incluyen latencia de red y varían entre ejecuciones.

| app | escenario | concurrencia | media (s) | desviación (s) |
|---|---|---:|---:|---:|
| sync | carga masiva | 1 | 21.2401 | 0.5714 |
| async | carga masiva | 10 | 5.1759 | 1.4341 |
| sync | CRUD | 1 | 1.0092 | 1.2096 |
| async | CRUD | 1 | 0.3021 | 0.0182 |
| sync | consultas | 1 | 0.3414 | 0.0616 |
| async | consultas | 1 | 0.1354 | 0.0190 |
| sync | consultas | 10 | 1.1100 | 0.3315 |
| async | consultas | 10 | 1.0208 | 0.0791 |
| sync | consultas | 50 | 3.0187 | 0.0854 |
| async | consultas | 50 | 2.8637 | 0.1400 |
| sync | consultas | 100 | 5.2551 | 0.2653 |
| async | consultas | 100 | 5.1011 | 0.2023 |

Carga de la colección completa (21349 documentos, lotes de 1000, 10 lotes a la
vez en async), con las demostraciones de cada app:

| app | documentos insertados | fallidos | tiempo |
|---|---:|---:|---:|
| sync | 21349 | 0 | 29.13 s |
| async | 21349 | 0 | 11.10 s |

## Análisis comparativo

**Carga masiva.** Async fue entre 2.6 y 4.1 veces más rápido (11.10 s contra
29.13 s con toda la colección; 5.18 s contra 21.24 s con 2000 documentos). La app
async envía hasta 10 lotes a la vez con `Semaphore(10)`; la sync los envía uno por
uno y espera la respuesta de la red en cada uno. Con lotes pequeños hay más viajes
de red que solapar, por eso la ventaja es mayor.

**Consultas.** Con una sola petición, async fue 2.5 veces más rápido (0.14 s
contra 0.34 s) porque `gather()` ejecuta las tres consultas a la vez, mientras que
sync las ejecuta en secuencia; esta comparación favorece a async por diseño. Con 10,
50 y 100 peticiones simultáneas los tiempos son casi iguales (por ejemplo 5.26 s
contra 5.10 s con 100) y las desviaciones se solapan. En ambas apps se resuelven
unas 58 consultas por segundo: el límite lo ponen el clúster compartido y la
agregación (`$unwind` y `$group` recorren toda la colección), no el driver.

**CRUD.** Las cuatro operaciones se hacen una tras otra en ambas apps, así que no
hay ventaja estructural para async. La desviación de sync (1.21 s) es mayor que su
media (1.01 s), señal de una medición atípica; esta comparación no es concluyente.

## Conclusiones

- Async conviene cuando hay muchas operaciones de E/S independientes que pueden
  solaparse: cargas por lotes y varias consultas a la vez.
- Cuando el servidor es el cuello de botella (muchas peticiones pesadas al mismo
  tiempo), las dos apps rinden prácticamente igual.
- Sync es más simple y suficiente para scripts pequeños o secuenciales.
- Una app async solo ayuda si realmente lanza trabajo en paralelo (`gather`,
  `TaskGroup`, lotes con `Semaphore`); usar `await` en serie no acelera nada.

## Fuentes

- [Tutorial de PyMongo Async 4.14.1](https://pymongo.readthedocs.io/en/4.14.1/async-tutorial.html)
- [Using MongoDB with PyMongo Async (async-concurrency.com)](https://www.async-concurrency.com/network-io-protocol-handling/async-database-drivers/using-mongodb-with-pymongo-async/)
