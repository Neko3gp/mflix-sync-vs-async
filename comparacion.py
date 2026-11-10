"""Compara sync_app y async_app: carga masiva, CRUD y consultas concurrentes.

Lee de sample_mflix (solo lectura) y escribe en una base temporal que borra al terminar.
"""
import asyncio
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import async_app
import sync_app

BENCH_DB = "mflix_bench"           # base temporal de la prueba
SAMPLE = 2000                      # películas para la carga masiva
BATCH_SIZE = 100                   # tamaño de lote -> 20 lotes
ASYNC_CONCURRENCY = 10             # lotes simultáneos en la carga async
RUNS = 3                           # repeticiones medidas por escenario
QUERY_CONCURRENCY = [1, 10, 50, 100] # niveles de concurrencia para las consultas


def stats(times):
    # Se resume cada escenario con media y desviación estándar para mostrar
    # tanto el tiempo típico como la variación entre repeticiones.
    return statistics.mean(times), statistics.stdev(times)


def measure_sync(operation, before=None):  # definimos un protocolo de medición para la app síncrona
    # Se reserva una posición adicional para una ejecución de calentamiento.
    times = []
    for i in range(RUNS + 1):  # la primera vuelta es de calentamiento y se descarta
        # before restablece el estado necesario antes de cada medición, por ejemplo
        # vaciando la colección para que todas las vueltas partan de la misma base.
        if before:
            before()
        # perf_counter es adecuado para medir intervalos cortos y no una hora del día.
        start = time.perf_counter()
        # La operación puede ser una carga, un flujo CRUD o varias consultas.
        operation()
        # La primera vuelta solo prepara conexiones/caches y no entra en las estadísticas.
        if i:
            times.append(time.perf_counter() - start)
    # RUNS debe ser mayor que uno para que stdev pueda calcularse.
    return stats(times)


async def measure_async(operation, before=None):  # definimos un protocolo de medición para la app asíncrona
    # Esta versión conserva el mismo protocolo de medición, pero espera cada corrutina.
    times = []
    for i in range(RUNS + 1):
        # La limpieza async se ejecuta antes de iniciar el cronómetro.
        if before:
            await before()
        start = time.perf_counter()
        # La operación permanece dentro del event loop y puede crear sus propias tareas.
        await operation()
        # Se descarta solo la primera vuelta para comparar ejecuciones ya calentadas.
        if i:
            times.append(time.perf_counter() - start)
    # Se devuelve el mismo par (media, desviación) que en la ruta síncrona.
    return stats(times)


def sync_crud(db):  # Las cuatro operaciones usan el mismo documento para medir el flujo CRUD completo.
    # Las cuatro operaciones usan el mismo documento para medir el flujo CRUD completo.
    # create devuelve el identificador que se reutiliza en las operaciones siguientes.
    movie_id = sync_app.create_movie(db, {"title": "Benchmark"})
    # get comprueba la lectura del documento recién creado.
    sync_app.get_movie(db, movie_id)
    # update cambia un campo para medir una modificación real.
    sync_app.update_movie(db, movie_id, {"year": 2024})
    # delete elimina el documento y completa el ciclo CRUD.
    sync_app.delete_movie(db, movie_id)


async def async_crud(db):  # La secuencia async replica exactamente el flujo sync, usando await en cada llamada.
    # La secuencia async replica exactamente el flujo sync, usando await en cada llamada.
    # La creación async devuelve el _id después de completar la escritura.
    movie_id = await async_app.create_movie(db, {"title": "Benchmark"})
    # La lectura espera la respuesta del cursor/documento antes de continuar.
    await async_app.get_movie(db, movie_id)
    # La actualización espera a que MongoDB confirme el cambio.
    await async_app.update_movie(db, movie_id, {"year": 2024})
    # La eliminación espera a que termine para no dejar datos del benchmark.
    await async_app.delete_movie(db, movie_id)


def sync_queries_concurrently(db, concurrency):  # Ejecuta N consultas simultáneamente con hilos.
    """N peticiones a la vez con hilos; cada una ejecuta las 3 consultas en secuencia."""
    # Cada hilo representa una petición independiente del cliente síncrono.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        # map espera a que todas las peticiones terminen; sus resultados no se necesitan.
        list(pool.map(lambda _: sync_app.run_queries(db), range(concurrency)))



async def async_queries_concurrently(db, concurrency):  # Ejecuta N consultas simultáneamente con asyncio.gather.
    """N peticiones a la vez con gather; cada una ejecuta las 3 consultas con gather."""
    # Se crean N flujos de consultas y gather espera a todos en paralelo.
    await asyncio.gather(*(async_app.run_queries_gather(db) for _ in range(concurrency)))


# ---------- Presentación de resultados ----------
def print_table(headers, rows, right=()):  # Imprime una tabla con columnas alineadas que además es válida en Markdown.
    """Imprime una tabla con columnas alineadas que además es válida en Markdown.

    `right` son los índices de las columnas que se alinean a la derecha (números).
    """
    # zip agrupa el encabezado con las celdas de cada columna para calcular su ancho.
    # max garantiza que ninguna fila desborde el formato de la tabla.
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows)]

    def format_row(cells):  # Formatea una fila con celdas alineadas según los anchos calculados.
        # Las columnas numéricas se alinean a la derecha y el resto a la izquierda.
        return "| " + " | ".join(
            # rjust alinea números a la derecha; ljust mantiene texto a la izquierda.
            str(cell).rjust(width) if i in right else str(cell).ljust(width)
            for i, (cell, width) in enumerate(zip(cells, widths))
        ) + " |"

    # Se imprime la primera fila usando los nombres de columnas recibidos.
    print(format_row(headers))
    # La raya separadora repite el ancho de cada columna y añade : a las numéricas.
    print("|" + "|".join(
        "-" * (width + 1) + ":" if i in right else "-" * (width + 2)
        for i, width in enumerate(widths)
    ) + "|")
    # Se imprimen las filas de datos en el mismo orden en que fueron medidas.
    for row in rows:
        # Cada fila usa los mismos anchos para mantener la tabla alineada.
        print(format_row(row))



def print_results(rows):  # Imprime los resultados de la comparación en una tabla.
    """rows: (app, escenario, concurrencia, media, desviación); sync y async van por pares."""
    # Se imprime primero el detalle de todas las mediciones ya formateadas.
    print(f"\nRESULTADOS (media de {RUNS} repeticiones)\n")
    print_table(
        ["app", "escenario", "concurrencia", "media (s)", "desviación (s)"],
        # Los tiempos se redondean a cuatro decimales solo para presentación.
        [(app, scenario, concurrency, f"{mean:.4f}", f"{std:.4f}")
         for app, scenario, concurrency, mean, std in rows],
        right=(2, 3, 4),
    )

    # summary contiene una fila comparativa por escenario y nivel de concurrencia.
    summary = []
    # rows está construido como pares sync/async para cada escenario.
    for sync_row, async_row in zip(rows[0::2], rows[1::2]):
        scenario, sync_mean, async_mean = sync_row[1], sync_row[3], async_row[3]
        # El cociente usa async como denominador: >1 favorece a async.
        ratio = sync_mean / async_mean
        if 0.9 <= ratio <= 1.1:
            # Una diferencia de hasta diez por ciento se considera equivalente.
            verdict = "similar"
        elif ratio > 1:
            # Si sync tarda más, async es ratio veces más rápida.
            verdict = f"{ratio:.2f} veces más rápida"
        else:
            # Si ratio es menor que uno, async tarda más que sync.
            verdict = f"{1 / ratio:.2f} veces más lenta"
        # Solo las consultas necesitan indicar cuántas peticiones se lanzaron.
        label = f"consultas ({sync_row[2]} a la vez)" if scenario == "consultas" else scenario
        # Se guardan los promedios formateados y el veredicto calculado.
        summary.append((label, f"{sync_mean:.4f}", f"{async_mean:.4f}", verdict))

    # El resumen facilita comparar cada pareja sin repetir la desviación estándar.
    print("\nRESUMEN: async frente a sync (similar = diferencia menor al 10 %)\n")
    print_table(["escenario", "sync (s)", "async (s)", "async es"], summary, right=(1, 2))


async def main():
    # Se mantienen ambos clientes abiertos durante toda la comparación para evitar
    # incluir repetidamente el coste de conexión en cada escenario.
    # Se crean los clientes antes del try para que estén disponibles en finally.
    sync_client = sync_app.get_client()
    async_client = async_app.get_client()
    try:
        # La muestra se limita a SAMPLE para que la prueba sea reproducible y manejable.
        movies = list(sync_client[sync_app.SOURCE_DB].movies.find().limit(SAMPLE))
        # Sin documentos de origen no existe una carga ni una comparación válida.
        if not movies:
            # return evita ejecutar el benchmark si la colección fuente está vacía.
            print(f"{sync_app.SOURCE_DB}.movies está vacía o no existe.")
            return
        # Se informa el tamaño real porque puede ser menor que SAMPLE.
        print(f"Películas para la carga: {len(movies)} (base temporal: {BENCH_DB})")

        # Las bases de lectura son la fuente original; las bases bench son temporales.
        read_sync = sync_client[sync_app.SOURCE_DB]
        read_async = async_client[async_app.SOURCE_DB]
        bench_sync = sync_client[BENCH_DB]
        bench_async = async_client[BENCH_DB]

        # Se comprueba primero que ambas implementaciones produzcan los mismos datos
        # antes de comparar sus tiempos.
        # La lista async se convierte al mismo tipo de resultado que devuelve sync.
        same = sync_app.run_queries(read_sync) == list(await async_app.run_queries_gather(read_async))
        # El resultado se muestra, pero el benchmark continúa aunque no coincida.
        print(f"Las dos apps devuelven los mismos resultados: {'sí' if same else 'NO'}\n")

        rows = []

        def add(app, scenario, concurrency, result):
            # Se normaliza cada medición al formato que esperan print_results.
            # El asterisco separa media y desviación para formar una sola tupla.
            rows.append((app, scenario, concurrency, *result))

        # La carga sync usa una secuencia; la async limita sus lotes con un semáforo.
        print("Midiendo carga masiva...", flush=True)
        add("sync", "carga masiva", 1, measure_sync(
            # delete_many deja la colección sync vacía antes de cada vuelta.
            lambda: sync_app.load_movies_bulk(bench_sync, movies, BATCH_SIZE),
            before=lambda: bench_sync.movies.delete_many({})))
        add("async", "carga masiva", ASYNC_CONCURRENCY, await measure_async(
            # La limpieza async se ejecuta antes de iniciar cada medición async.
            lambda: async_app.load_movies_bulk(bench_async, movies, BATCH_SIZE, ASYNC_CONCURRENCY),
            before=lambda: bench_async.movies.delete_many({})))

        # CRUD se mide con una petición por vuelta para aislar el flujo básico.
        print("Midiendo CRUD...", flush=True)
        add("sync", "CRUD", 1, measure_sync(
            # Se limpia la colección para que cada ciclo CRUD comience sin residuos.
            lambda: sync_crud(bench_sync),
            before=lambda: bench_sync.movies.delete_many({})))
        add("async", "CRUD", 1, await measure_async(
            # El backend async usa su propia colección temporal independiente.
            lambda: async_crud(bench_async),
            before=lambda: bench_async.movies.delete_many({})))

        for concurrency in QUERY_CONCURRENCY:
            # Cada valor muestra cómo escala el backend cuando crece la demanda.
            print(f"Midiendo consultas ({concurrency} a la vez)...", flush=True)
            add("sync", "consultas", concurrency, measure_sync(
                # Cada repetición crea tantos hilos como indica concurrency.
                lambda: sync_queries_concurrently(read_sync, concurrency)))
            add("async", "consultas", concurrency, await measure_async(
                # Cada repetición crea la misma cantidad de flujos async equivalentes.
                lambda: async_queries_concurrently(read_async, concurrency)))

        # Solo se presentan resultados cuando todos los escenarios terminaron.
        print_results(rows)
    finally:
        # La base temporal se elimina incluso si una medición lanza una excepción.
        # Se usa el cliente sync porque drop_database es una operación síncrona.
        sync_client.drop_database(BENCH_DB)
        # Ambos clientes se cierran explícitamente para liberar sockets y recursos.
        sync_client.close()
        await async_client.close()


if __name__ == "__main__":
    # El módulo se ejecuta dentro de un único ciclo de eventos async.
    asyncio.run(main())