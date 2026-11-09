"""App asíncrona (PyMongo Async): carga masiva, CRUD y consultas sobre sample_mflix.movies."""
import asyncio
import os
import re
import time

from pymongo import AsyncMongoClient, InsertOne
from pymongo.errors import BulkWriteError

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
SOURCE_DB = "sample_mflix"  # base original: solo se lee
APP_DB = "mflix_async"      # copia donde trabaja esta app


def get_client():
    return AsyncMongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


# ---------- Carga masiva ----------
async def load_movies_bulk(db, movies, batch_size=1000, concurrency=10):
    """Inserta los lotes con bulk_write; el Semaphore deja hasta `concurrency` a la vez."""
    semaphore = asyncio.Semaphore(concurrency)

    async def load_batch(batch):
        async with semaphore:
            try:
                result = await db.movies.bulk_write(
                    [InsertOne(m) for m in batch], ordered=False
                )
                return result.inserted_count, 0
            except BulkWriteError as error:  # p. ej. _id duplicado
                return error.details["nInserted"], len(error.details["writeErrors"])

    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(load_batch(movies[i:i + batch_size]))
            for i in range(0, len(movies), batch_size)
        ]

    results = [task.result() for task in tasks]
    return {
        "inserted": sum(inserted for inserted, _ in results),
        "failed": sum(failed for _, failed in results),
    }


# ---------- CRUD ----------
async def create_movie(db, movie):
    if not movie.get("title"):
        raise ValueError("La película debe tener 'title'.")
    return (await db.movies.insert_one(movie)).inserted_id


async def get_movie(db, movie_id):
    return await db.movies.find_one({"_id": movie_id})


async def update_movie(db, movie_id, changes):
    result = await db.movies.update_one({"_id": movie_id}, {"$set": changes})
    return result.modified_count


async def delete_movie(db, movie_id):
    return (await db.movies.delete_one({"_id": movie_id})).deleted_count


# ---------- Consultas ----------
async def find_movies_by_year_and_genre(db, year, genre, limit=10):
    """Filtro compuesto + proyección + orden por título."""
    cursor = db.movies.find(
        {"year": year, "genres": genre}, {"_id": 0, "title": 1, "year": 1}
    ).sort("title", 1).limit(limit)
    return await cursor.to_list()  # find() no se espera con await; to_list() sí


async def aggregate_movies_by_genre(db):
    """Top 5 de géneros con más películas."""
    pipeline = [
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    cursor = await db.movies.aggregate(pipeline)  # aggregate() sí se espera con await
    return await cursor.to_list()


async def search_movies_by_regex(db, text):
    """Títulos que contienen el texto, sin importar mayúsculas."""
    query = {"title": {"$regex": re.escape(text), "$options": "i"}}
    cursor = db.movies.find(query, {"_id": 0, "title": 1}).limit(5)
    return await cursor.to_list()


async def run_queries_gather(db):
    """Las tres consultas independientes al mismo tiempo con asyncio.gather()."""
    return await asyncio.gather(
        find_movies_by_year_and_genre(db, 1999, "Action"),
        aggregate_movies_by_genre(db),
        search_movies_by_regex(db, "Matrix"),
    )


async def run_queries_taskgroup(db):
    """Las mismas tres consultas con asyncio.TaskGroup()."""
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(find_movies_by_year_and_genre(db, 1999, "Action")),
            group.create_task(aggregate_movies_by_genre(db)),
            group.create_task(search_movies_by_regex(db, "Matrix")),
        ]
    return [task.result() for task in tasks]


# ---------- Demostración ----------
async def main():
    client = get_client()
    try:
        movies = await client[SOURCE_DB].movies.find().to_list()
        if not movies:
            print(f"{SOURCE_DB}.movies está vacía o no existe.")
            return
        print(f"Películas leídas de {SOURCE_DB}: {len(movies)}")

        db = client[APP_DB]
        await db.movies.drop()
        start = time.perf_counter()
        result = await load_movies_bulk(db, movies)
        print(f"Carga masiva: {result} en {time.perf_counter() - start:.2f} s")

        movie_id = await create_movie(db, {"title": "Película de prueba", "year": 2024})
        print("Crear:", movie_id)
        print("Leer:", await get_movie(db, movie_id))
        print("Actualizar (modificadas):", await update_movie(db, movie_id, {"year": 2025}))
        print("Eliminar (eliminadas):", await delete_movie(db, movie_id))

        start = time.perf_counter()
        year_genre, top_genres, matrix = await run_queries_gather(db)
        print(f"Consultas con gather(): {time.perf_counter() - start:.3f} s")
        start = time.perf_counter()
        await run_queries_taskgroup(db)
        print(f"Consultas con TaskGroup(): {time.perf_counter() - start:.3f} s")
        print("Año 1999 + Action:", year_genre)
        print("Top géneros:", top_genres)
        print("Títulos con 'Matrix':", matrix)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
