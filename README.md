# Proyecto 2a Evaluación: base de datos asíncrona vs síncrona (MongoDB + Python)

Reporte del proyecto. Administra la colección `movies` de la base `sample_mflix`
con dos aplicaciones equivalentes, una con PyMongo síncrono y otra con PyMongo
Async, y compara su desempeño.

## 1. Resumen

- **Qué es:** dos apps con las mismas funciones (carga masiva, CRUD y consultas)
  sobre `sample_mflix.movies`, más un script que las compara.
- **Qué ganó async:** la carga masiva (alrededor de 2 veces más rápida en un MongoDB
  local y de 2.6 a 4.1 veces en Atlas) y las consultas de una sola petición (unas
  2.3 a 2.5 veces).
- **Dónde no ganó:** en el CRUD (cada paso depende del anterior) y cuando llegan
  muchas peticiones al mismo tiempo (10, 50 o 100): ahí las dos apps empatan.
- **Regla práctica:** async ayuda cuando hay tiempo de espera de red que se puede
  aprovechar para hacer otras cosas. Su ventaja crece con la latencia (mayor en Atlas
  que en local) y desaparece cuando el cuello de botella es el servidor.
- **Atlas o Docker:** se probó en los dos. Docker local da resultados estables y
  reproducibles sin credenciales; Atlas es más realista porque tiene latencia de
  red. Detalles en la sección 8.

## 2. Conceptos clave

### Síncrono vs asíncrono

Cuando la app manda una operación a MongoDB, casi todo el tiempo lo pasa
**esperando la respuesta de la red**. Async no hace que MongoDB trabaje más rápido:
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

### Qué hace cada demostración (`sync_app.py` y `async_app.py`)

1. Se conecta a MongoDB (si el servidor no responde en 5 segundos, falla con un error).
2. Lee todas las películas de `sample_mflix.movies`. Esa base **solo se lee, nunca se modifica**.
3. Borra y vuelve a crear su propia copia (`mflix_sync` o `mflix_async`) con carga masiva y mide el tiempo.
4. Hace un ciclo CRUD con una película de prueba: crear, leer, actualizar el año y eliminar.
5. Corre las tres consultas y muestra resultados y tiempo (la sync en secuencia; la async con `gather()` y con `TaskGroup()`).

### Qué hace la comparación (`comparacion.py`)

- Lee 2000 películas de `sample_mflix` y comprueba que las dos apps devuelven los
  mismos resultados (imprime `True`).
- Mide tres escenarios: **carga masiva** (2000 documentos en 20 lotes de 100; la async
  con 10 lotes a la vez), **CRUD** (las cuatro operaciones seguidas) y **consultas**
  con 1, 10, 50 y 100 peticiones simultáneas (cada petición ejecuta las 3 consultas).
- Cada escenario se corre una vez de calentamiento (se descarta) y tres veces
  medidas; la tabla muestra la media y la desviación estándar.
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
- Un MongoDB que tenga la base `sample_mflix` (ver abajo).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Conexión

Por defecto se conecta a `mongodb://localhost:27017`. Para usar otro servidor
(por ejemplo Atlas), define la variable de entorno antes de ejecutar. La URI lleva
contraseña: no la escribas en ningún archivo del repositorio.

```bash
export MONGO_URI="mongodb+srv://USUARIO:CONTRASENA@CLUSTER.mongodb.net/"
```

### Datos de `sample_mflix`

- **Atlas:** en el clúster, *Load Sample Dataset*. Además hay que crear un usuario de
  base de datos y permitir la IP desde la que se ejecuta el proyecto.
- **MongoDB local con Docker** (no requiere instalar nada más). Ejecutar desde una
  carpeta fuera del repositorio, porque el archivo de datos pesa unos 380 MB:

```bash
docker run -d --name mongo-mflix -p 27017:27017 mongo:7
curl https://atlas-education.s3.amazonaws.com/sampledata.archive -o sampledata.archive
docker cp sampledata.archive mongo-mflix:/sampledata.archive
docker exec mongo-mflix mongorestore --archive=/sampledata.archive --nsInclude="sample_mflix.movies"
```

`mongorestore` muestra una advertencia porque el archivo viene de MongoDB 8 y el
contenedor usa la versión 7; la restauración funciona y termina con
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
python comparacion.py    # comparación entre las dos (tarda varios minutos con Atlas)
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
| Comparación entre las dos apps | `comparacion.py` y las secciones 6 y 7 de este documento |

## 6. Resultados

La velocidad depende mucho de la red, así que se midió en dos entornos: un MongoDB
local en Docker y un clúster Atlas M0 (en la nube, con latencia de red).

**Cómo leer las tablas:** "concurrencia" es cuántos lotes (en la carga) o cuántas
peticiones (en las consultas) se envían a la vez; en la app sync la carga va de uno
en uno. Una desviación de 0.0000 significa menos de 0.00005 s.

### 6.1 MongoDB local (Docker): demostraciones

Una ejecución de cada demostración con la colección completa (21349 documentos,
lotes de 1000, hasta 10 lotes a la vez en async). Sin repeticiones, por lo que son
cifras orientativas.

| app | carga masiva | fallidos | consultas (3 en total) |
|---|---:|---:|---:|
| sync | 0.48 s | 0 | 0.049 s (en secuencia) |
| async | 0.33 s | 0 | 0.021 s con `gather()`, 0.021 s con `TaskGroup()` |

### 6.2 MongoDB local (Docker): `comparacion.py`

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

### 6.3 Clúster Atlas M0

Carga de la colección completa (21349 documentos, lotes de 1000, 10 lotes a la vez
en async), con las demostraciones de cada app:

| app | documentos insertados | fallidos | tiempo |
|---|---:|---:|---:|
| sync | 21349 | 0 | 29.13 s |
| async | 21349 | 0 | 11.10 s |

Benchmark con los mismos escenarios y parámetros que `comparacion.py` (2000
películas en 20 lotes de 100, media de 3 repeticiones tras una de calentamiento):

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

### 6.4 Resumen: cuántas veces más rápido fue async

| Escenario | MongoDB local | Atlas M0 |
|---|---:|---:|
| Carga masiva, 2000 documentos (lotes de 100) | 2.0 veces | 4.1 veces |
| Carga masiva, colección completa (lotes de 1000) | 1.5 veces | 2.6 veces |
| Consultas, 1 petición | 2.3 veces | 2.5 veces |
| Consultas, 10, 50 y 100 peticiones | empate | empate |
| CRUD | sync algo más rápida (1.3 ms contra 1.8 ms) | no concluyente |

## 7. Análisis comparativo

**Carga masiva.** Async fue más rápido en los dos entornos, pero la ventaja depende
de la red. Con Atlas, donde cada lote paga latencia, fue de 2.6 a 4.1 veces más
rápido; con MongoDB local bajó a entre 1.5 y 2 veces. La app async envía hasta 10
lotes a la vez con `Semaphore(10)`; la sync los envía uno por uno y espera la
respuesta de cada uno. Lo que async aprovecha es ese tiempo de espera, y con un
servidor local casi no lo hay. Los lotes pequeños (100 documentos) dan más
viajes de red que solapar, por eso la ventaja es mayor que con lotes de 1000.

**Consultas con una petición.** Async fue unas 2.3 veces más rápido en local y 2.5 en
Atlas, y `TaskGroup()` tardó lo mismo que `gather()`. Esta comparación favorece a
async por diseño: la sync ejecuta las tres consultas una tras otra y la async las
lanza a la vez. La ventaja es de la concurrencia dentro de la petición, no del
driver.

**Consultas con muchas peticiones simultáneas.** Con 10, 50 y 100 peticiones las
dos apps empatan en los dos entornos (por ejemplo 0.578 s contra 0.569 s en local con
100, y 5.26 s contra 5.10 s en Atlas), y las desviaciones se solapan. Ambas se
estancan en el mismo ritmo: unas 520 consultas por segundo en local y unas 58 en
Atlas. Como la sync (con hilos) y la async llegan al mismo valor, el cuello de
botella parece estar en el servidor, donde cada petición ejecuta una agregación
(`$unwind` y `$group`) que recorre toda la colección, y no en el driver.

**CRUD.** Las cuatro operaciones dependen una de la otra (crear, leer, actualizar,
eliminar), así que no hay nada que solapar y no se espera ventaja de async. En local,
async fue incluso un poco más lenta (1.8 ms contra 1.3 ms), probablemente por el
costo extra de manejar el ciclo de eventos. En Atlas la medición de sync tuvo una
desviación mayor que su media (1.21 s contra 1.01 s): un valor atípico, por lo que
esa diferencia no es concluyente.

## 8. Atlas o Docker: qué se usó y por qué

| Criterio | Atlas (nube) | Docker (local) |
|---|---|---|
| Preparación | Cuenta, clúster M0, usuario de base de datos, IP permitida y URI | Tener Docker y ejecutar 4 comandos (descarga única de unos 380 MB) |
| Datos de ejemplo | Un clic (*Load Sample Dataset*) | Restaurar solo `sample_mflix.movies` del archivo oficial |
| Costo y conexión | Gratis (M0), pero requiere cuenta e internet | Gratis, sin cuenta; funciona sin internet tras la descarga |
| Credenciales | URI con contraseña: no se debe subir al repositorio | Ninguna |
| Reproducirlo en otra computadora (por ejemplo, el profesor) | Necesita su propio clúster o acceso al nuestro | Cualquiera con Docker lo repite igual |
| Datos compartidos por el equipo | Sí: un solo clúster al que todos se conectan | No: cada quien tiene su copia |
| Estabilidad de las mediciones | Variable (red y clúster compartido): desviaciones de hasta 1.4 s; una corrida anterior de la carga sync tardó 63.96 s contra los 29.13 s de la otra | Muy estable: desviaciones de hasta 0.03 s |
| Realismo | Alto: hay latencia de red como en una base en la nube; aquí async mostró su mayor ventaja | Bajo: servidor en la misma máquina, casi sin espera de red |
| Velocidad para trabajar | Carga completa en 11 a 29 s | Carga completa en menos de 1 s |

**Qué se usó.** La app se conecta por defecto a un MongoDB local, porque así
cualquier persona puede ejecutarla y obtener resultados estables sin credenciales.
Atlas sigue soportado cambiando solo `MONGO_URI`, y se usó para medir con red real.
Las dos mediciones se complementan: Docker da cifras repetibles y Atlas muestra
cuánto más pesa la ventaja de async cuando hay latencia.

**Cuál conviene según el objetivo.**
- Para desarrollar, probar y que otra persona reproduzca el proyecto: Docker local.
- Para evidenciar el beneficio real de async: un servidor remoto como Atlas.
- Para compartir los mismos datos entre varios integrantes: Atlas.

**Versión original y versión actual.** La versión original estaba pensada solo para
Atlas (con archivo `.env`) e incluía una interfaz gráfica, pruebas con pytest,
scripts para exportar y cargar datos con un JSON intermedio, creación de índices y
varios módulos dentro de una carpeta `src/`. Esta versión conserva únicamente lo que
pide la actividad:

- Son 3 archivos con las mismas funciones lado a lado, más fáciles de explicar y revisar.
- Solo depende de `pymongo`.
- Lee los datos directo de `sample_mflix`, sin archivos intermedios.
- No lleva secretos en el repositorio.
- Funciona con Atlas o con Docker cambiando una variable.

Lo que se dejó fuera (interfaz, pruebas automáticas, índices) no lo pide la
actividad. Que las dos apps devuelven lo mismo se comprueba en `comparacion.py`.

## 9. Conclusiones

- Async conviene cuando hay muchas operaciones de E/S independientes que se pueden
  solapar: cargas por lotes y varias consultas a la vez.
- Su ventaja crece con la latencia de red: fue mucho mayor contra Atlas que contra
  un MongoDB local.
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

- Las demostraciones locales son una sola ejecución; la comparación usa 3
  repeticiones con una de calentamiento.
- Las mediciones de Atlas y las locales se hicieron en momentos y condiciones
  distintos, y las de Atlas con una versión anterior del proyecto (misma lógica,
  mismos escenarios y parámetros) antes de simplificarlo. Conviene comparar las
  proporciones (cuántas veces más rápido), no los tiempos absolutos.
- En Docker, el servidor y la app comparten el procesador y la memoria de la misma
  computadora.
- La comparación con una sola petición favorece a async por diseño.
- Al restaurar los datos aparece una advertencia de versiones (archivo de MongoDB 8,
  servidor 7); la restauración se verificó contando los 21349 documentos.

## 12. Fuentes

- [Tutorial de PyMongo Async 4.14.1](https://pymongo.readthedocs.io/en/4.14.1/async-tutorial.html)
- [Using MongoDB with PyMongo Async (async-concurrency.com)](https://www.async-concurrency.com/network-io-protocol-handling/async-database-drivers/using-mongodb-with-pymongo-async/)
- [Load sample data (local), MongoDB](https://www.mongodb.com/docs/manual/sample-data/load-sample-data-local/)