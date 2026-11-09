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
QUERY_CONCURRENCY = [1, 10, 50, 100]


def stats(times):
    return statistics.mean(times), statistics.stdev(times)


def measure_sync(operation, before=None):
    times = []
    for i in range(RUNS + 1):  # la primera vuelta es de calentamiento y se descarta
        if before:
            before()
        start = time.perf_counter()
        operation()
        if i:
            times.append(time.perf_counter() - start)
    return stats(times)


async def measure_async(operation, before=None):
    times = []
    for i in range(RUNS + 1):
        if before:
            await before()
        start = time.perf_counter()
        await operation()
        if i:
            times.append(time.perf_counter() - start)
    return stats(times)


def sync_crud(db):
    movie_id = sync_app.create_movie(db, {"title": "Benchmark"})
    sync_app.get_movie(db, movie_id)
    sync_app.update_movie(db, movie_id, {"year": 2024})
    sync_app.delete_movie(db, movie_id)


async def async_crud(db):
    movie_id = await async_app.create_movie(db, {"title": "Benchmark"})
    await async_app.get_movie(db, movie_id)
    await async_app.update_movie(db, movie_id, {"year": 2024})
    await async_app.delete_movie(db, movie_id)


def sync_queries_concurrently(db, concurrency):
    """N peticiones a la vez con hilos; cada una ejecuta las 3 consultas en secuencia."""
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda _: sync_app.run_queries(db), range(concurrency)))


async def async_queries_concurrently(db, concurrency):
    """N peticiones a la vez con gather; cada una ejecuta las 3 consultas con gather."""
    await asyncio.gather(*(async_app.run_queries_gather(db) for _ in range(concurrency)))


# ---------- Presentación de resultados ----------
def print_table(headers, rows, right=()):
    """Imprime una tabla con columnas alineadas que además es válida en Markdown.

    `right` son los índices de las columnas que se alinean a la derecha (números).
    """
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows)]

    def format_row(cells):
        return "| " + " | ".join(
            str(cell).rjust(width) if i in right else str(cell).ljust(width)
            for i, (cell, width) in enumerate(zip(cells, widths))
        ) + " |"

    print(format_row(headers))
    print("|" + "|".join(
        "-" * (width + 1) + ":" if i in right else "-" * (width + 2)
        for i, width in enumerate(widths)
    ) + "|")
    for row in rows:
        print(format_row(row))


def print_results(rows):
    """rows: (app, escenario, concurrencia, media, desviación); sync y async van por pares."""
    print(f"\nRESULTADOS (media de {RUNS} repeticiones)\n")
    print_table(
        ["app", "escenario", "concurrencia", "media (s)", "desviación (s)"],
        [(app, scenario, concurrency, f"{mean:.4f}", f"{std:.4f}")
         for app, scenario, concurrency, mean, std in rows],
        right=(2, 3, 4),
    )

    summary = []
    for sync_row, async_row in zip(rows[0::2], rows[1::2]):
        scenario, sync_mean, async_mean = sync_row[1], sync_row[3], async_row[3]
        ratio = sync_mean / async_mean
        if 0.9 <= ratio <= 1.1:
            verdict = "similar"
        elif ratio > 1:
            verdict = f"{ratio:.2f} veces más rápida"
        else:
            verdict = f"{1 / ratio:.2f} veces más lenta"
        label = f"consultas ({sync_row[2]} a la vez)" if scenario == "consultas" else scenario
        summary.append((label, f"{sync_mean:.4f}", f"{async_mean:.4f}", verdict))

    print("\nRESUMEN: async frente a sync (similar = diferencia menor al 10 %)\n")
    print_table(["escenario", "sync (s)", "async (s)", "async es"], summary, right=(1, 2))


async def main():
    sync_client = sync_app.get_client()
    async_client = async_app.get_client()
    try:
        movies = list(sync_client[sync_app.SOURCE_DB].movies.find().limit(SAMPLE))
        if not movies:
            print(f"{sync_app.SOURCE_DB}.movies está vacía o no existe.")
            return
        print(f"Películas para la carga: {len(movies)} (base temporal: {BENCH_DB})")

        read_sync = sync_client[sync_app.SOURCE_DB]
        read_async = async_client[async_app.SOURCE_DB]
        bench_sync = sync_client[BENCH_DB]
        bench_async = async_client[BENCH_DB]

        same = sync_app.run_queries(read_sync) == list(await async_app.run_queries_gather(read_async))
        print(f"Las dos apps devuelven los mismos resultados: {'sí' if same else 'NO'}\n")

        rows = []

        def add(app, scenario, concurrency, result):
            rows.append((app, scenario, concurrency, *result))

        print("Midiendo carga masiva...", flush=True)
        add("sync", "carga masiva", 1, measure_sync(
            lambda: sync_app.load_movies_bulk(bench_sync, movies, BATCH_SIZE),
            before=lambda: bench_sync.movies.delete_many({})))
        add("async", "carga masiva", ASYNC_CONCURRENCY, await measure_async(
            lambda: async_app.load_movies_bulk(bench_async, movies, BATCH_SIZE, ASYNC_CONCURRENCY),
            before=lambda: bench_async.movies.delete_many({})))

        print("Midiendo CRUD...", flush=True)
        add("sync", "CRUD", 1, measure_sync(
            lambda: sync_crud(bench_sync),
            before=lambda: bench_sync.movies.delete_many({})))
        add("async", "CRUD", 1, await measure_async(
            lambda: async_crud(bench_async),
            before=lambda: bench_async.movies.delete_many({})))

        for concurrency in QUERY_CONCURRENCY:
            print(f"Midiendo consultas ({concurrency} a la vez)...", flush=True)
            add("sync", "consultas", concurrency, measure_sync(
                lambda: sync_queries_concurrently(read_sync, concurrency)))
            add("async", "consultas", concurrency, await measure_async(
                lambda: async_queries_concurrently(read_async, concurrency)))

        print_results(rows)
    finally:
        sync_client.drop_database(BENCH_DB)
        sync_client.close()
        await async_client.close()


if __name__ == "__main__":
    asyncio.run(main())