"""Carga data/movies.json en una base de trabajo con ambas implementaciones."""
import argparse
import asyncio
import time
from pathlib import Path

from bson import json_util

from src.async_app.bulk import load_movies_bulk as async_load
from src.async_app.db import get_async_client, get_async_db
from src.common.config import DB_NAME, SOURCE_DB
from src.sync_app.bulk import load_movies_bulk as sync_load
from src.sync_app.db import get_sync_client, get_sync_db


def read_movies(path, limit=None):
    """Lee Extended JSON y limita documentos por línea sin leer el archivo completo."""
    with path.open(encoding="utf-8") as file:
        first = file.read(1)
        file.seek(0)
        if first == "[":
            documents = json_util.load(file)
            return documents if limit is None else documents[:limit]
        documents = []
        for line in file:
            if line.strip():
                documents.append(json_util.loads(line))
                if limit is not None and len(documents) >= limit:
                    break
        return documents


async def run_async(movies, batch_size, concurrency, database):
    client = get_async_client()
    try:
        db = get_async_db(database, client)
        await db.movies.drop()
        start = time.perf_counter()
        result = await async_load(db, movies, batch_size, concurrency)
        return result, time.perf_counter() - start
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="data/movies.json")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--database", default=DB_NAME)
    args = parser.parse_args()
    if args.database == SOURCE_DB:
        parser.error("No se permite escribir ni borrar la base SOURCE_DB.")
    path = Path(args.file)
    if not path.exists():
        print(f"No existe {path}. Ejecuta primero scripts.export_data.")
        return 1
    movies = read_movies(path, args.limit)
    print(f"Documentos leídos: {len(movies)}")

    sync_client = get_sync_client()
    try:
        sync_db = get_sync_db(args.database, sync_client)
        sync_db.movies.drop()
        start = time.perf_counter()
        sync_result = sync_load(sync_db, movies, args.batch_size, args.concurrency)
        print(f"SYNC: {sync_result}, tiempo={time.perf_counter() - start:.3f}s")
    finally:
        sync_client.close()

    async_result, async_time = asyncio.run(
        run_async(movies, args.batch_size, args.concurrency, args.database)
    )
    print(f"ASYNC: {async_result}, tiempo={async_time:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
