# Proyecto 2a Evaluación: base de datos asíncrona vs síncrona (MongoDB + Python)

Reporte del proyecto. Administra la colección `movies` de la base `sample_mflix`
con dos aplicaciones equivalentes, una con PyMongo síncrono y otra con PyMongo
Async, y compara su desempeño sobre un MongoDB local.

## 1. Resumen

- **Qué es:** dos apps con las mismas funciones (carga masiva, CRUD y consultas)
  sobre `sample_mflix.movies`, más un script que las compara.
- **Qué ganó async:** la carga masiva (alrededor de 2 veces más rápida) y las
  consultas de una sola petición (unas 2.3 veces).
- **Dónde no ganó:** en el CRUD (cada paso depende del anterior) y cuando llegan
  muchas peticiones al mismo tiempo (10, 50 o 100): ahí las dos apps empatan.
- **Regla práctica:** async ayuda cuando hay tiempo de espera que se puede
  aprovechar para hacer otras cosas, y deja de ayudar cuando el cuello de botella es
  el servidor.
- **Entorno:** MongoDB local en Docker con los datos de `sample_mflix`. No se necesita
  cuenta ni credenciales (sección 4).

## 2. Conceptos clave

### Síncrono vs asíncrono

Cuando la app manda una operación a MongoDB, casi todo el tiempo lo pasa
**esperando la respuesta**. Async no hace que MongoDB trabaje más rápido:
aprovecha ese tiempo de espera para enviar otras operaciones.

```text
SÍNCRONO: un lote después de otro (el programa se queda esperando)

lote 1  [envío ··· espera ··· listo]
lote 2                              [envío ··· espera ··· listo]
lote 3                                                          [envío ··· espera ··· listo]

ASÍNCRONO: varios lotes en vuelo a la vez (hasta 10 con el Semaphore)

lote 1  [envío ··· espera ··· listo]
lote 2  [envío ··· espera ··· listo]
lote 3  [envío ··· espera ··· listo]
```

### Herramientas que usa el proyecto

| Herramienta | Para qué sirve | Dónde |
|---|---|---|
| `AsyncMongoClient` | Cliente de PyMongo para código asíncrono; sus operaciones se esperan con `await` | `async_app.py` |
| `bulk_write` con `InsertOne` | Manda muchos inserts en una sola petición (un lote). Con `ordered=False`, si un documento falla (por ejemplo `_id` duplicado) los demás se siguen insertando | las dos apps |
| `asyncio.TaskGroup` | Lanza varias tareas y espera a todas; si una falla, cancela las demás (Python 3.11 o superior) | `async_app.py` |
| `asyncio.gather` | Lanza varias operaciones a la vez y devuelve sus resultados en orden | `async_app.py` |
| `asyncio.Semaphore` | Limita cuántas tareas ejecutan una parte del código al mismo tiempo; aquí, 10 lotes escribiendo a la vez | `async_app.py` |
| `ThreadPoolExecutor` | Solo en `comparacion.py`: simula varias peticiones simultáneas en la app síncrona usando hilos | `comparacion.py` |

`gather` y `TaskGroup` hacen lo mismo en este proyecto (las consultas tardaron igual
con ambos). La diferencia está en los errores: si una tarea falla, `TaskGroup`
cancela las demás y `gather` no.

## 3. Cómo funciona el proyecto

### Archivos

```text
sync_app.py      App síncrona: carga masiva, CRUD, consultas
async_app.py     App asíncrona: las mismas funciones con async/await
comparacion.py   Comparación de tiempos entre ambas
requirements.txt Dependencias (solo pymongo)
```

Las dos apps tienen las mismas funciones con los mismos nombres, para poder
compararlas lado a lado:

| Funcionalidad | Función |
|---|---|
| Carga masiva | `load_movies_bulk` |
| Crear / Leer / Actualizar / Eliminar | `create_movie`, `get_movie`, `update_movie`, `delete_movie` |
| Filtro + proyección + orden (año y género) | `find_movies_by_year_and_genre` |
| Agregación (top 5 de géneros) | `aggregate_movies_by_genre` |
| Búsqueda por texto en el título (regex) | `search_movies_by_regex` |
| Las tres consultas juntas | `run_queries` (sync), `run_queries_gather` y `run_queries_taskgroup` (async) |

### Por qué las apps trabajan en copias de `sample_mflix.movies`

Las dos apps administran los datos de `sample_mflix.movies`, pero cada una trabaja
sobre **su propia copia** de esa colección (`mflix_sync` y `mflix_async`) y no sobre
la colección original. Es una decisión de diseño para poder medir y comparar el
rendimiento de las dos apps de forma justa:

- **Independencia:** cada app escribe en su propia base, así que una no interfiere con
  la otra. Pueden ejecutarse al mismo tiempo, o una después de otra, sin que los
  datos o los tiempos de una afecten a la otra.
- **Mismas condiciones de partida:** las dos copias salen de los mismos documentos de
  `sample_mflix.movies`, por lo que la comparación de `comparacion.py` mide la
  diferencia entre sync y async y no diferencias en los datos.
- **Repetibilidad:** cada ejecución borra y recrea la copia, de modo que las pruebas
  (carga masiva, CRUD y consultas) siempre empiezan desde el mismo estado.
- **Datos originales intactos:** `sample_mflix` solo se lee, así que se puede volver a
  usar sin tener que restaurarla.

Las operaciones que pide la actividad (carga masiva, CRUD y consultas) son las mismas
sobre la copia que serían sobre la colección original; solo cambia el nombre de la
base en la que se ejecutan.

### Qué hace cada demostración (`sync_app.py` y `async_app.py`)

1. Se conecta a MongoDB (si el servidor no responde en 5 segundos, falla con un error).
2. Lee todas las películas de `sample_mflix.movies`. Esa base **solo se lee, nunca se modifica**.
3. Borra y vuelve a crear su propia copia (`mflix_sync` o `mflix_async`) con carga masiva y mide el tiempo.
4. Hace un ciclo CRUD con una película de prueba: crear, leer, actualizar el año y eliminar.
5. Corre las tres consultas y muestra resultados y tiempo (la sync en secuencia; la async con `gather()` y con `TaskGroup()`).

### Qué hace la comparación (`comparacion.py`)

- Lee 2000 películas de `sample_mflix` y comprueba que las dos apps devuelven los
  mismos resultados (imprime `sí`).
- Mide tres escenarios: **carga masiva** (2000 documentos en 20 lotes de 100; la async
  con 10 lotes a la vez), **CRUD** (las cuatro operaciones seguidas) y **consultas**
  con 1, 10, 50 y 100 peticiones simultáneas (cada petición ejecuta las 3 consultas).
- Cada escenario se corre una vez de calentamiento (se descarta) y tres veces
  medidas; se muestra una tabla con la media y la desviación estándar, y un resumen
  con cuántas veces más rápida o más lenta fue async.
- Escribe en una base temporal (`mflix_bench`) que borra al terminar. Las consultas
  leen `sample_mflix`, sin modificarla.
- En la app síncrona, las peticiones simultáneas se simulan con hilos; en la
  asíncrona, con `gather`.

### Código clave

Carga masiva asíncrona (`async_app.py`): un `TaskGroup` lanza un lote por tarea y el
`Semaphore` deja escribir solo a 10 a la vez.

```python
semaphore = asyncio.Semaphore(concurrency)

async def load_batch(batch):
    async with semaphore:
        try:
            result = await db.movies.bulk_write(
                [InsertOne(m) for m in batch], ordered=False
            )
            return result.inserted_count, 0
        except BulkWriteError as error:
            return error.details["nInserted"], len(error.details["writeErrors"])

async with asyncio.TaskGroup() as group:
    tasks = [
        group.create_task(load_batch(movies[i:i + batch_size]))
        for i in range(0, len(movies), batch_size)
    ]
```

Carga masiva síncrona (`sync_app.py`, simplificada): los lotes van uno tras otro.

```python
for i in range(0, len(movies), batch_size):
    batch = movies[i:i + batch_size]
    result = db.movies.bulk_write([InsertOne(m) for m in batch], ordered=False)
```

Las tres consultas independientes a la vez (`async_app.py`):

```python
return await asyncio.gather(
    find_movies_by_year_and_genre(db, 1999, "Action"),
    aggregate_movies_by_genre(db),
    search_movies_by_regex(db, "Matrix"),
)
```

Detalles de PyMongo Async tomados del [tutorial de PyMongo 4.14.1](https://pymongo.readthedocs.io/en/4.14.1/async-tutorial.html)
y de la [guía de async-concurrency](https://www.async-concurrency.com/network-io-protocol-handling/async-database-drivers/using-mongodb-with-pymongo-async/):

- `find()` devuelve un cursor sin `await`; se lee con `await cursor.to_list()`.
- `aggregate()` sí se espera con `await` y devuelve el cursor.
- Se crea **un solo cliente** y se reutiliza; al terminar, `await client.close()`.
- El `Semaphore` evita lanzar más operaciones simultáneas que conexiones disponibles.

## 4. Instalación y ejecución

### Requisitos

- Python 3.11 o superior (`asyncio.TaskGroup` no existe antes).
- Docker, para tener un MongoDB local con la base `sample_mflix` (ver abajo).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Datos de `sample_mflix` en un MongoDB local (Docker)

Las apps se conectan a `mongodb://localhost:27017`, que es el contenedor de Docker de
esta sección. No requiere instalar nada más que Docker. Primero se descarga el archivo
`sampledata.archive` (conjunto de datos de ejemplo oficial de MongoDB, unos 380 MB)
desde la guía oficial indicada al final de esta sección y se deja en una carpeta fuera
del repositorio. Después, desde esa carpeta:

```bash
docker run -d --name mongo-mflix -p 27017:27017 mongo:7
docker cp sampledata.archive mongo-mflix:/sampledata.archive
docker exec mongo-mflix mongorestore --archive=/sampledata.archive --nsInclude="sample_mflix.movies"
```

`mongorestore` muestra una advertencia porque el archivo viene de MongoDB 8
y el contenedor usa la versión 7; la restauración funciona y termina con
`21349 document(s) restored successfully`. Para verificar y limpiar:

```bash
docker exec mongo-mflix mongosh --quiet --eval 'db.getSiblingDB("sample_mflix").movies.countDocuments()'   # 21349
rm sampledata.archive
docker exec mongo-mflix rm /sampledata.archive
```

Guía oficial: [Load sample data (local)](https://www.mongodb.com/docs/manual/sample-data/load-sample-data-local/).

### Ejecución

```bash
python sync_app.py       # demostración de la app síncrona
python async_app.py      # demostración de la app asíncrona
python comparacion.py    # comparación entre las dos
```

Las dos apps devuelven los mismos resultados. Solo el orden de los títulos de la
búsqueda "Matrix" puede variar entre una y otra, porque esa consulta no ordena y
cada app trabaja en su propia copia de la colección.

## 5. Dónde está lo que pide la actividad

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
| Administrar `sample_mflix` (movies) | Las dos apps leen `sample_mflix.movies` y operan sobre su propia copia (`mflix_sync`, `mflix_async`); ver sección 3, "Por qué las apps trabajan en copias" |
| Comparación entre las dos apps | `comparacion.py` y las secciones 6 y 7 de este documento |

## 6. Resultados

Todas las mediciones se hicieron en un MongoDB local en Docker, con los datos de
`sample_mflix.movies`.

**Cómo leer las tablas:** "concurrencia" es cuántos lotes (en la carga) o cuántas
peticiones (en las consultas) se envían a la vez; en la app sync la carga va de uno
en uno. Una desviación de 0.0000 significa menos de 0.00005 s.

### 6.1 Demostraciones

Una ejecución de cada demostración con la colección completa (21349 documentos,
lotes de 1000, hasta 10 lotes a la vez en async). Sin repeticiones, por lo que son
cifras orientativas.

| app | carga masiva | fallidos | consultas (3 en total) |
|---|---:|---:|---:|
| sync | 0.48 s | 0 | 0.049 s (en secuencia) |
| async | 0.33 s | 0 | 0.021 s con `gather()`, 0.021 s con `TaskGroup()` |

### 6.2 Comparación (`comparacion.py`)

2000 películas en lotes de 100, media de 3 repeticiones tras una de calentamiento.

| app | escenario | concurrencia | media (s) | desviación (s) |
|---|---|---:|---:|---:|
| sync | carga masiva | 1 | 0.0510 | 0.0005 |
| async | carga masiva | 10 | 0.0259 | 0.0020 |
| sync | CRUD | 1 | 0.0013 | 0.0000 |
| async | CRUD | 1 | 0.0018 | 0.0000 |
| sync | consultas | 1 | 0.0472 | 0.0002 |
| async | consultas | 1 | 0.0205 | 0.0002 |
| sync | consultas | 10 | 0.0629 | 0.0031 |
| async | consultas | 10 | 0.0658 | 0.0058 |
| sync | consultas | 50 | 0.2894 | 0.0184 |
| async | consultas | 50 | 0.2938 | 0.0158 |
| sync | consultas | 100 | 0.5781 | 0.0281 |
| async | consultas | 100 | 0.5690 | 0.0152 |

### 6.3 Resumen: cuántas veces más rápido fue async

| Escenario | Resultado |
|---|---:|
| Carga masiva, 2000 documentos (lotes de 100) | 2.0 veces más rápido |
| Carga masiva, colección completa (lotes de 1000) | 1.5 veces más rápido |
| Consultas, 1 petición | 2.3 veces más rápido |
| Consultas, 10, 50 y 100 peticiones | empate |
| CRUD | sync algo más rápida (1.3 ms contra 1.8 ms) |

## 7. Análisis comparativo

**Carga masiva.** Async fue entre 1.5 y 2 veces más rápido. La app async envía hasta
10 lotes a la vez con `Semaphore(10)`; la sync los envía uno por uno y espera la
respuesta de cada uno. Lo que async aprovecha es ese tiempo de espera, y con un
servidor local hay poco, por eso la ventaja es moderada. Los lotes pequeños (100
documentos) dan más viajes al servidor que solapar, por eso la ventaja es mayor que
con lotes de 1000 (2.0 contra 1.5 veces).

**Consultas con una petición.** Async fue unas 2.3 veces más rápido, y `TaskGroup()`
tardó lo mismo que `gather()`. Esta comparación favorece a async por diseño: la sync
ejecuta las tres consultas una tras otra y la async las lanza a la vez. La ventaja es
de la concurrencia dentro de la petición, no del driver.

**Consultas con muchas peticiones simultáneas.** Con 10, 50 y 100 peticiones las dos
apps empatan (por ejemplo 0.578 s contra 0.569 s con 100), y las desviaciones se
solapan. Ambas se estancan en el mismo ritmo, unas 520 consultas por segundo. Como la
sync (con hilos) y la async llegan al mismo valor, el cuello de botella parece estar
en el servidor, donde cada petición ejecuta una agregación (`$unwind` y `$group`) que
recorre toda la colección, y no en el driver.

**CRUD.** Las cuatro operaciones dependen una de la otra (crear, leer, actualizar,
eliminar), así que no hay nada que solapar y no se espera ventaja de async. Async fue
incluso un poco más lenta (1.8 ms contra 1.3 ms), probablemente por el costo extra de
manejar el ciclo de eventos.

## 8. Por qué se usa un MongoDB local

Las fuentes de la actividad (el tutorial de PyMongo Async y la guía de
async-concurrency) solo requieren un servidor MongoDB con los datos de ejemplo, por
lo que el proyecto usa un MongoDB local en Docker con `sample_mflix.movies` restaurada
desde el archivo oficial de datos de ejemplo.

- **Reproducible:** cualquier persona con Docker repite el proyecto igual, sin cuenta
  ni credenciales.
- **Estable:** las mediciones casi no varían entre ejecuciones (desviaciones de hasta
  0.03 s).
- **Rápido para trabajar:** la carga completa tarda menos de 1 s.
- **Sin secretos en el repositorio:** no hay contraseñas ni URIs privadas.

## 9. Conclusiones

- Async conviene cuando hay muchas operaciones de E/S independientes que se pueden
  solapar: cargas por lotes y varias consultas a la vez.
- Cuando el servidor es el cuello de botella (muchas peticiones pesadas a la vez),
  las dos apps rinden prácticamente igual.
- En operaciones que dependen una de otra, como el CRUD, async no aporta.
- Sync es más simple y suficiente para scripts pequeños o secuenciales.
- Una app async solo ayuda si realmente lanza trabajo en paralelo (`gather`,
  `TaskGroup`, lotes con `Semaphore`); usar `await` en serie no acelera nada.

## 10. Preguntas frecuentes

**¿Por qué async ganó con una sola petición si el servidor hace el mismo trabajo?**
Porque la app sync ejecuta las tres consultas una tras otra y la async las lanza a la
vez con `gather()`. Es una ventaja del diseño, no del driver.

**¿Por qué con 10, 50 y 100 peticiones empatan?** La app sync usa hilos, que también
aprovechan el tiempo de espera, y el servidor atiende el mismo número de consultas por
segundo en ambos casos. El límite está en el servidor.

**¿Para qué sirve `ordered=False`?** Si un documento falla (por ejemplo, un `_id`
duplicado), MongoDB sigue con los demás en lugar de detenerse. Al probarlo con un
documento repetido se insertaron los demás y se reportó 1 fallido.

**Si ya hay `TaskGroup`, ¿para qué el `Semaphore`?** El `TaskGroup` lanza una tarea
por lote (22 en la carga completa). El `Semaphore` deja que solo 10 escriban al mismo
tiempo, para no saturar el servidor ni las conexiones del cliente.

**¿Por qué el CRUD no mejora con async?** Cada operación necesita el resultado de la
anterior, así que no hay nada que hacer mientras se espera.

**¿Se modifica `sample_mflix`?** No. Solo se lee; las apps escriben en sus propias
copias (`mflix_sync`, `mflix_async`) y la comparación en una base temporal que borra
al terminar.

## 11. Limitaciones

- Las demostraciones son una sola ejecución; la comparación usa 3 repeticiones con
  una de calentamiento.
- El servidor y la app comparten el procesador y la memoria de la misma computadora,
  y casi no hay latencia de red.
- La comparación con una sola petición favorece a async por diseño.
- Al restaurar los datos aparece una advertencia de versiones (archivo de MongoDB 8,
  servidor 7); la restauración se verificó contando los 21349 documentos.

## 12. Fuentes

- [Tutorial de PyMongo Async 4.14.1](https://pymongo.readthedocs.io/en/4.14.1/async-tutorial.html)
- [Using MongoDB with PyMongo Async (async-concurrency.com)](https://www.async-concurrency.com/network-io-protocol-handling/async-database-drivers/using-mongodb-with-pymongo-async/)
- [Load sample data (local), MongoDB](https://www.mongodb.com/docs/manual/sample-data/load-sample-data-local/)