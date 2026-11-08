# Administración de `sample_mflix.movies`

## Descripción y requisitos

Este proyecto administra la colección `movies` de MongoDB Atlas con dos
implementaciones equivalentes: PyMongo síncrono y PyMongo Async. La base fuente
`sample_mflix` se usa solo para exportar datos; la aplicación trabaja en
`mflix_demo`. Se requiere Python 3.11 o superior porque se usa
`asyncio.TaskGroup`.

## Configuración de MongoDB Atlas

1. Crea un clúster gratuito M0 en [MongoDB Atlas](https://www.mongodb.com/atlas).
2. En **Database Access**, crea un usuario con permisos `readWriteAnyDatabase`
   (o `readWrite` sobre las bases del proyecto).
3. En **Network Access**, agrega la IP desde la que ejecutarás el proyecto.
4. En el clúster, selecciona **Load Sample Dataset** y verifica
   `sample_mflix.movies`.
5. En **Connect > Drivers > Python**, copia la URI de conexión.
6. Al pegarla en `.env`, quita los símbolos `< >`, no dupliques el prefijo
   `mongodb+srv://` y usa una contraseña sin caracteres especiales o
   codificada con URL.

## Instalación y configuración

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` con la URI real. Nunca publiques ese archivo:

```env
MONGO_URI=mongodb+srv://USUARIO:CONTRASENA@CLUSTER.mongodb.net/
DB_NAME=mflix_demo
SOURCE_DB=sample_mflix
TEST_DB_NAME=mflix_test
```

`sample_mflix` es una fuente de solo lectura para `export_data.py`. Las
operaciones de la aplicación, la interfaz y la carga del proyecto ocurren en
`mflix_demo`.

## Flujo de ejecución

Ejecuta desde la raíz del repositorio, un comando a la vez:

```bash
python test.py
python -m scripts.export_data
python -m scripts.load_data --file data/movies.json
python -m data.setup_indexes
python interfaz.py
python -m pytest -q
python -m benchmarks.runner --sample 2000 --runs 3 --batch-size 100
```

`export_data` copia los 21349 documentos de `SOURCE_DB.movies` a
`data/movies.json`. `load_data` elimina `DB_NAME.movies` (colección e índices)
antes de cargar con Sync y luego con Async; nunca modifica `sample_mflix`. Por
eso `setup_indexes` se ejecuta después de la carga. Para pruebas rápidas puedes
limitar los documentos con `--limit 500` en `export_data` y `load_data`.

El benchmark usa siempre la base aislada `mflix_bench`, la elimina al terminar
y solo lee `DB_NAME` durante las consultas. La carga desde la interfaz usa
`mflix_demo_sync.movies` y `mflix_demo_async.movies`, previa confirmación, para
que las cargas Sync y Async no choquen por `_id`.

## Estructura

```text
src/common/config.py       Variables de entorno
src/sync_app/              MongoClient, CRUD, consultas y bulk síncronos
src/async_app/             AsyncMongoClient, CRUD, consultas y bulk asíncronos
scripts/export_data.py     Exportación de SOURCE_DB.movies
scripts/load_data.py       Carga masiva Sync y Async
data/setup_indexes.py      Índices y explain
tests/test_equivalence.py  Pruebas equivalentes
benchmarks/runner.py       Benchmark y resultados
interfaz.py                Interfaz CustomTkinter
```

## Concurrencia y carga masiva

- `asyncio.gather()` está en `src/async_app/queries.py`, función
  `run_independent_queries`, para ejecutar tres consultas independientes.
- `asyncio.TaskGroup()` está en el mismo archivo, función
  `run_queries_taskgroup`, y en `src/async_app/bulk.py` para lanzar los lotes.
- `asyncio.Semaphore` está en `src/async_app/bulk.py`, función
  `load_movies_bulk`, para limitar lotes concurrentes.
- `bulk_write(ordered=False)` está en
  `src/async_app/bulk.py` y `src/sync_app/bulk.py`, para insertar lotes y
  continuar ante IDs duplicados.

Ambas funciones bulk clonan los documentos, capturan `BulkWriteError` y
errores generales, y devuelven `inserted`, `failed` y `errors`.

## Uso de la interfaz

Ejecuta:

```bash
python interfaz.py
```

- **SYNC · PyMongo:** botones para crear, buscar por ID, actualizar, eliminar,
  buscar por título, filtrar por año/género, top de géneros y carga bulk.
- **ASYNC · AsyncMongoClient:** las mismas operaciones, además de botones para
  `gather()`, `TaskGroup()` y carga bulk con `Semaphore`.
- **COMPARACIÓN:** ejecuta las mismas consultas Sync secuenciales y Async con
  `gather()`, mostrando tiempo y cantidad de resultados.

La etiqueta **Base activa** muestra `DB_NAME`. Las cargas de la interfaz
trabajan en bases auxiliares para no borrar ni modificar la base principal.

## Resultados

Todas las mediciones se hicieron contra un clúster M0 de Atlas, por lo que
incluyen latencia de red y pueden variar entre ejecuciones.

### Carga masiva real (21349 documentos, lotes de 1000, concurrencia 10)

| implementación | documentos | fallidos | tiempo |
|---|---:|---:|---:|
| Sync | 21349 | 0 | 29.13 s |
| Async | 21349 | 0 | 11.10 s |

Una corrida anterior dio 63.96 s (Sync) y 14.08 s (Async); la diferencia entre
corridas depende de la red.

### Índices (colección completa, 21349 documentos)

| consulta | estado | examinados | devueltos | tiempo (ms) | plan |
|---|---|---:|---:|---:|---|
| año + género + título | antes | 21349 | 58 | 49 | COLLSCAN |
| año + género + título | después | 0 | 58 | 1 | IXSCAN |
| regex con `i` | antes | 21349 | 4 | 30 | COLLSCAN |
| regex con `i` | después | 21349 | 4 | 26 | COLLSCAN |
| agregación | antes | 21349 | 21349 | 62 | COLLSCAN |
| agregación | después | 21349 | 21349 | 48 | COLLSCAN |

### Benchmark

Generado con `python -m benchmarks.runner --sample 2000 --runs 3 --batch-size 100`
(carga de 2000 documentos en 20 lotes; consultas sobre `mflix_demo` completa):

| app | escenario | concurrencia | media (s) | desviación (s) |
|---|---|---:|---:|---:|
| sync | carga masiva | 1 | 21.3044 | 0.5579 |
| async | carga masiva | 10 | 4.8349 | 0.4218 |
| sync | CRUD | 1 | 0.9699 | 1.1428 |
| async | CRUD | 1 | 0.3067 | 0.0146 |
| sync | consultas | 1 | 0.3592 | 0.0497 |
| async | consultas | 1 | 0.1578 | 0.0224 |
| sync | consultas | 10 | 0.8943 | 0.1053 |
| async | consultas | 10 | 0.8680 | 0.0736 |
| sync | consultas | 50 | 3.3644 | 0.5614 |
| async | consultas | 50 | 2.7962 | 0.2194 |
| sync | consultas | 100 | 5.0660 | 0.1815 |
| async | consultas | 100 | 5.0760 | 0.1927 |

## Análisis comparativo y conclusiones

**Carga masiva.** Async fue entre 2.6 y 4.4 veces más rápido: 11.10 s contra
29.13 s con los 21349 documentos y lotes de 1000, y 4.83 s contra 21.30 s en el
benchmark con lotes de 100. Async envía hasta 10 lotes a la vez con
`Semaphore(10)`, mientras que Sync los envía uno por uno y paga la latencia de
red de Atlas en cada uno. La ventaja es mayor con lotes pequeños, porque hay más
viajes de red que solapar, y desaparece cuando solo hay un lote.

**Consultas.** Con una sola petición, Async fue 2.3 veces más rápido (0.16 s
contra 0.36 s) porque `asyncio.gather()` ejecuta las tres consultas a la vez,
mientras que Sync las ejecuta en secuencia; esta comparación favorece a Async
por diseño. Con 10 y 100 peticiones concurrentes los tiempos son prácticamente
iguales, y con 50 la diferencia es pequeña (2.80 s contra 3.36 s, con
desviaciones que se solapan). Ambas apps procesan unas 60 consultas por
segundo en alta concurrencia: el límite lo ponen el clúster M0 compartido y la
agregación sin índice que recorre toda la colección, no el driver.

**CRUD.** Las cuatro operaciones son secuenciales en ambas apps, por lo que no
se espera una ventaja estructural de Async. La desviación estándar de Sync
(1.14 s) es mayor que su media, lo que indica una medición atípica, así que esta
diferencia no es concluyente.

**Índices.** El índice compuesto (año, géneros, título) redujo la consulta de
21349 documentos examinados a 0, porque el índice contiene todo lo que pide la
consulta (consulta cubierta), y el tiempo bajó de 49 ms a 1 ms. El regex con
`$options: "i"` no puede usar índices y la agregación con `$unwind` y `$group`
recorre toda la colección; ambos siguen en COLLSCAN.

**Conclusión.** Async conviene cuando hay muchas operaciones de E/S
independientes (cargas por lotes, varias consultas a la vez). Sync sigue siendo
más simple y suficiente para scripts pequeños. Con el clúster saturado, ambas
convergen.

## Limitaciones y reproducción

El benchmark depende de la latencia, carga y límites del clúster M0. Las
pruebas usan documentos pequeños en `TEST_DB_NAME` y nunca importan las
21349 películas. `load_data` reemplaza `DB_NAME.movies` y sus índices, por lo
que debe ejecutarse solo cuando se desea repetir la carga. Los errores de
conexión se limitan a cinco segundos mediante `serverSelectionTimeoutMS=5000`.