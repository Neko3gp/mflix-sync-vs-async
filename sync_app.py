"""App síncrona (PyMongo): carga masiva, CRUD y consultas sobre sample_mflix.movies."""
import re
import time

from pymongo import InsertOne, MongoClient
from pymongo.errors import BulkWriteError

MONGO_URI = "mongodb://localhost:27017"  # MongoDB local (Docker)
SOURCE_DB = "sample_mflix"  # base original: solo se lee
APP_DB = "mflix_sync"       # copia donde trabaja esta app


def get_client():
    # Se crea un cliente nuevo para que cada ejecución controle explícitamente
    # su propia conexión y pueda cerrarla en el bloque `finally` de `main`.
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


# ---------- Carga masiva ----------
def load_movies_bulk(db, movies, batch_size=1000):
    """Inserta las películas por lotes con bulk_write, un lote después de otro."""
    # Estos acumuladores conservan el resultado total de todos los lotes.
    inserted = failed = 0
    # range avanza de batch_size en batch_size para no construir una operación
    # gigante y para que cada iteración represente una escritura independiente.
    for i in range(0, len(movies), batch_size):
        # El último lote puede tener menos elementos que los demás.
        batch = movies[i:i + batch_size]
        try:
            # ordered=False permite que MongoDB intente el resto del lote aunque
            # una película concreta produzca un error de escritura.
            result = db.movies.bulk_write([InsertOne(m) for m in batch], ordered=False)
            # En el camino normal, todas las escrituras válidas se contabilizan
            # desde el resultado que devuelve bulk_write.
            inserted += result.inserted_count
        except BulkWriteError as error:  # p. ej. _id duplicado
            # Un lote puede insertar parte de sus documentos antes de fallar;
            # por eso se suman tanto los insertados como los errores individuales.
            inserted += error.details["nInserted"]
            failed += len(error.details["writeErrors"])
    # Se devuelve un resumen acumulado para que la CLI y la interfaz puedan
    # mostrar el mismo formato de resultado.
    return {"inserted": inserted, "failed": failed}


# ---------- CRUD ----------
def create_movie(db, movie):
    # Se valida el campo obligatorio antes de enviar el documento a MongoDB.
    if not movie.get("title"):
        raise ValueError("La película debe tener 'title'.")
    # insert_one genera o conserva el _id y se devuelve solo ese identificador.
    return db.movies.insert_one(movie).inserted_id


def get_movie(db, movie_id):
    # find_one devuelve el documento completo o None si el identificador no existe.
    return db.movies.find_one({"_id": movie_id})


def update_movie(db, movie_id, changes):
    # $set modifica únicamente los campos recibidos, sin reemplazar el documento.
    return db.movies.update_one({"_id": movie_id}, {"$set": changes}).modified_count


def delete_movie(db, movie_id):
    # deleted_count permite informar si realmente se eliminó algún documento.
    return db.movies.delete_one({"_id": movie_id}).deleted_count


# ---------- Consultas ----------
def find_movies_by_year_and_genre(db, year, genre, limit=10):
    """Filtro compuesto + proyección + orden por título."""
    # El filtro exige simultáneamente el año y la pertenencia del género.
    cursor = db.movies.find(
        {"year": year, "genres": genre}, {"_id": 0, "title": 1, "year": 1}
    ).sort("title", 1).limit(limit)
    # La conversión a list ejecuta el cursor y materializa sus resultados.
    return list(cursor)


def aggregate_movies_by_genre(db):
    """Top 5 de géneros con más películas."""
    # Cada etapa transforma el flujo: separa géneros, cuenta, ordena y limita.
    pipeline = [
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    # aggregate devuelve documentos con el género en _id y su cantidad en count.
    return list(db.movies.aggregate(pipeline))


def search_movies_by_regex(db, text):
    """Títulos que contienen el texto, sin importar mayúsculas."""
    # re.escape trata el texto del usuario como texto literal, no como regex libre.
    query = {"title": {"$regex": re.escape(text), "$options": "i"}}
    # Solo se proyecta el título y se limita la respuesta para mantenerla manejable.
    return list(db.movies.find(query, {"_id": 0, "title": 1}).limit(5))


def run_queries(db):
    """Las tres consultas independientes, una después de otra."""
    # La lista conserva el orden esperado por main: filtro, agregación y búsqueda.
    return [
        find_movies_by_year_and_genre(db, 1999, "Action"),
        aggregate_movies_by_genre(db),
        search_movies_by_regex(db, "Matrix"),
    ]


# ---------- Demostración ----------
def main():
    # El cliente se cierra incluso si una operación de lectura o escritura falla.
    client = get_client()
    try:
        # Se copia la colección original a memoria para reutilizarla en la carga.
        movies = list(client[SOURCE_DB].movies.find())
        # Sin datos de origen no hay nada que cargar ni comparar.
        if not movies:
            print(f"{SOURCE_DB}.movies está vacía o no existe.")
            return
        print(f"Películas leídas de {SOURCE_DB}: {len(movies)}")

        db = client[APP_DB]
        # La copia se recrea en cada demostración para evitar datos de ejecuciones previas.
        db.movies.drop()
        start = time.perf_counter()
        result = load_movies_bulk(db, movies)
        print(f"Carga masiva: {result} en {time.perf_counter() - start:.2f} s")

        movie_id = create_movie(db, {"title": "Película de prueba", "year": 2024})
        # Las siguientes operaciones ejercitan el ciclo CRUD completo con el mismo _id.
        print("Crear:", movie_id)
        print("Leer:", get_movie(db, movie_id))
        print("Actualizar (modificadas):", update_movie(db, movie_id, {"year": 2025}))
        print("Eliminar (eliminadas):", delete_movie(db, movie_id))

        start = time.perf_counter()
        # run_queries ejecuta las tres consultas en orden y devuelve sus tres resultados.
        year_genre, top_genres, matrix = run_queries(db)
        print(f"Consultas secuenciales: {time.perf_counter() - start:.3f} s")
        print("Año 1999 + Action:", year_genre)
        print("Top géneros:", top_genres)
        print("Títulos con 'Matrix':", matrix)
    finally:
        # MongoClient mantiene recursos de red; siempre se libera al terminar.
        client.close()


if __name__ == "__main__":
    main()