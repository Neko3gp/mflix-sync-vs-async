import argparse
import asyncio
import csv
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bson import ObjectId, json_util

from src.async_app.bulk import load_movies_bulk as async_load
from src.async_app.crud import (
    create_movie as async_create,
    delete_movie as async_delete,
    get_movie as async_get,
    update_movie as async_update,
)
from src.async_app.db import get_async_client, get_async_db
from src.async_app.queries import run_independent_queries as async_queries
from src.sync_app.bulk import load_movies_bulk as sync_load
from src.sync_app.crud import (
    create_movie as sync_create,
    delete_movie as sync_delete,
    get_movie as sync_get,
    update_movie as sync_update,
)
from src.sync_app.db import get_sync_client, get_sync_db
from src.sync_app.queries import run_independent_queries as sync_queries

BENCH_DB = "mflix_bench"
CONCURRENCY_LEVELS = [1, 10, 50, 100]


def load_sample(path, sample):
    """Lee una muestra del archivo o genera documentos para una prueba aislada."""
    file = Path(path)
    if not file.exists():
        return [{"_id": ObjectId(), "title": f"Benchmark {i}"} for i in range(sample)]
    with file.open(encoding="utf-8") as source:
        first = source.read(1)
        source.seek(0)
        if first == "[":
            return json_util.load(source)[:sample]
        documents = []
        for line in source:
            if line.strip():
                documents.append(json_util.loads(line))
                if len(documents) == sample:
                    break
        return documents


def calculate_stats(times):
    return statistics.mean(times), statistics.stdev(times) if len(times) > 1 else 0


def measure_sync_work(db, operation, runs):
    values = []
    for iteration in range(runs + 1):
        db.movies.delete_many({})
        start = time.perf_counter()
        operation()
        if iteration:
            values.append(time.perf_counter() - start)
    return calculate_stats(values)


async def measure_async_work(db, operation, runs):
    values = []
    for iteration in range(runs + 1):
        await db.movies.delete_many({})
        start = time.perf_counter()
        await operation()
        if iteration:
            values.append(time.perf_counter() - start)
    return calculate_stats(values)


def measure_sync_queries(db, concurrency, runs):
    values = []
    for iteration in range(runs + 1):
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(lambda _: sync_queries(db), range(concurrency)))
        if iteration:
            values.append(time.perf_counter() - start)
    return calculate_stats(values)


async def measure_async_queries(db, concurrency, runs):
    values = []
    for iteration in range(runs + 1):
        start = time.perf_counter()
        await asyncio.gather(*(async_queries(db) for _ in range(concurrency)))
        if iteration:
            values.append(time.perf_counter() - start)
    return calculate_stats(values)


def sync_crud(db):
    movie_id = sync_create(db, {"title": "Benchmark"})
    sync_get(db, movie_id)
    sync_update(db, movie_id, {"year": 2024})
    sync_delete(db, movie_id)


async def async_crud(db):
    movie_id = await async_create(db, {"title": "Benchmark"})
    await async_get(db, movie_id)
    await async_update(db, movie_id, {"year": 2024})
    await async_delete(db, movie_id)


def write_results(rows):
    output = Path("benchmarks")
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "| app | escenario | concurrencia | media (s) | desviación (s) |",
        "|---|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {row['app']} | {row['scenario']} | {row['concurrency']} | "
        f"{row['mean_s']:.4f} | {row['std_s']:.4f} |"
        for row in rows
    )
    (output / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_benchmarks(sample, runs, batch_size):
    sync_client = get_sync_client()
    async_client = get_async_client()
    sync_work = get_sync_db(BENCH_DB, sync_client)
    async_work = get_async_db(BENCH_DB, async_client)
    sync_read = get_sync_db(client=sync_client)
    async_read = get_async_db(client=async_client)
    try:
        movies = load_sample("data/movies.json", sample)
        print(f"Documentos de carga: {len(movies)} (base aislada: {BENCH_DB})")
        rows = []
        sync_mean, sync_std = measure_sync_work(
            sync_work, lambda: sync_load(sync_work, movies, batch_size), runs
        )
        async_mean, async_std = await measure_async_work(
            async_work, lambda: async_load(async_work, movies, batch_size, 10), runs
        )
        rows.extend([
            {"app": "sync", "scenario": "carga masiva", "concurrency": 1, "mean_s": sync_mean, "std_s": sync_std},
            {"app": "async", "scenario": "carga masiva", "concurrency": 10, "mean_s": async_mean, "std_s": async_std},
        ])
        sync_mean, sync_std = measure_sync_work(sync_work, lambda: sync_crud(sync_work), runs)
        async_mean, async_std = await measure_async_work(async_work, lambda: async_crud(async_work), runs)
        rows.extend([
            {"app": "sync", "scenario": "CRUD", "concurrency": 1, "mean_s": sync_mean, "std_s": sync_std},
            {"app": "async", "scenario": "CRUD", "concurrency": 1, "mean_s": async_mean, "std_s": async_std},
        ])
        for concurrency in CONCURRENCY_LEVELS:
            sync_mean, sync_std = measure_sync_queries(sync_read, concurrency, runs)
            async_mean, async_std = await measure_async_queries(async_read, concurrency, runs)
            rows.extend([
                {"app": "sync", "scenario": "consultas", "concurrency": concurrency, "mean_s": sync_mean, "std_s": sync_std},
                {"app": "async", "scenario": "consultas", "concurrency": concurrency, "mean_s": async_mean, "std_s": async_std},
            ])
        write_results(rows)
        print("Resultados escritos en benchmarks/results.csv y benchmarks/results.md.")
    finally:
        try:
            sync_work.movies.drop()
        except Exception as error:
            try:
                sync_work.movies.delete_many({})
                print(f"No se pudo eliminar la colección de benchmark: {error}")
            except Exception as cleanup_error:
                print(f"No se pudo limpiar {BENCH_DB}.movies: {cleanup_error}")
        sync_client.close()
        await async_client.close()


def main():
    parser = argparse.ArgumentParser(description="Benchmark sync y async sin modificar DB_NAME.")
    parser.add_argument("--sample", type=int, default=2000)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run_benchmarks(args.sample, args.runs, args.batch_size))


if __name__ == "__main__":
    main()
