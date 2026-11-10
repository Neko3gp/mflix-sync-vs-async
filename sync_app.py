"""App síncrona (PyMongo): carga masiva, CRUD y consultas sobre sample_mflix.movies."""
import os
import re
import time

from pymongo import InsertOne, MongoClient
from pymongo.errors import BulkWriteError

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
SOURCE_DB = "sample_mflix"  # base original: solo se lee
APP_DB = "mflix_sync"       # copia donde trabaja esta app


def get_client():
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


# ---------- Carga masiva ----------
def load_movies_bulk(db, movies, batch_size=1000):
    """Inserta las películas por lotes con bulk_write, un lote después de otro."""
    inserted = failed = 0
    for i in range(0, len(movies), batch_size):
        batch = movies[i:i + batch_size]
        try:
            result = db.movies.bulk_write([InsertOne(m) for m in batch], ordered=False)
            inserted += result.inserted_count
        except BulkWriteError as error:  # p. ej. _id duplicado
            inserted += error.details["nInserted"]
            failed += len(error.details["writeErrors"])
    return {"inserted": inserted, "failed": failed}


# ---------- CRUD ----------
def create_movie(db, movie):
    if not movie.get("title"):
        raise ValueError("La película debe tener 'title'.")
    return db.movies.insert_one(movie).inserted_id


def get_movie(db, movie_id):
    return db.movies.find_one({"_id": movie_id})


def update_movie(db, movie_id, changes):
    return db.movies.update_one({"_id": movie_id}, {"$set": changes}).modified_count


def delete_movie(db, movie_id):
    return db.movies.delete_one({"_id": movie_id}).deleted_count


# ---------- Consultas ----------
def find_movies_by_year_and_genre(db, year, genre, limit=10):
    """Filtro compuesto + proyección + orden por título."""
    cursor = db.movies.find(
        {"year": year, "genres": genre}, {"_id": 0, "title": 1, "year": 1}
    ).sort("title", 1).limit(limit)
    return list(cursor)


def aggregate_movies_by_genre(db):
    """Top 5 de géneros con más películas."""
    pipeline = [
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    return list(db.movies.aggregate(pipeline))


def search_movies_by_regex(db, text):
    """Títulos que contienen el texto, sin importar mayúsculas."""
    query = {"title": {"$regex": re.escape(text), "$options": "i"}}
    return list(db.movies.find(query, {"_id": 0, "title": 1}).limit(5))


def run_queries(db):
    """Las tres consultas independientes, una después de otra."""
    return [
        find_movies_by_year_and_genre(db, 1999, "Action"),
        aggregate_movies_by_genre(db),
        search_movies_by_regex(db, "Matrix"),
    ]


# ---------- Demostración ----------
def main():
    client = get_client()
    try:
        movies = list(client[SOURCE_DB].movies.find())
        if not movies:
            print(f"{SOURCE_DB}.movies está vacía o no existe.")
            return
        print(f"Películas leídas de {SOURCE_DB}: {len(movies)}")

        db = client[APP_DB]
        db.movies.drop()
        start = time.perf_counter()
        result = load_movies_bulk(db, movies)
        print(f"Carga masiva: {result} en {time.perf_counter() - start:.2f} s")

        movie_id = create_movie(db, {"title": "Película de prueba", "year": 2024})
        print("Crear:", movie_id)
        print("Leer:", get_movie(db, movie_id))
        print("Actualizar (modificadas):", update_movie(db, movie_id, {"year": 2025}))
        print("Eliminar (eliminadas):", delete_movie(db, movie_id))

        start = time.perf_counter()
        year_genre, top_genres, matrix = run_queries(db)
        print(f"Consultas secuenciales: {time.perf_counter() - start:.3f} s")
        print("Año 1999 + Action:", year_genre)
        print("Top géneros:", top_genres)
        print("Títulos con 'Matrix':", matrix)
    finally:
        client.close()


if __name__ == "__main__":
    main()
