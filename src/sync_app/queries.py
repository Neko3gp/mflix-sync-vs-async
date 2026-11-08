import re
from concurrent.futures import ThreadPoolExecutor


def find_movies_by_year_and_genre(db, year, genre, limit=10):
    # Filtro compuesto, proyección (oculta _id, muestra título/año) y ordenación
    query = {"year": year, "genres": genre}
    projection = {"_id": 0, "title": 1, "year": 1}
    cursor = db.movies.find(query, projection).sort("title", 1).limit(limit)
    return list(cursor)

def aggregate_movies_by_genre(db):
    # Pipeline: separa el array de géneros, agrupa, cuenta y ordena los 5 más populares
    pipeline = [
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    return list(db.movies.aggregate(pipeline))

def search_movies_by_regex(db, pattern):
    # Búsqueda por texto parcial ignorando mayúsculas (Case Insensitive)
    query = {"title": {"$regex": re.escape(pattern), "$options": "i"}}
    projection = {"_id": 0, "title": 1}
    return list(db.movies.find(query, projection).limit(5))

def search_movies_by_text(db, text):
    """Busca palabras usando el índice de texto."""
    return list(db.movies.find({"$text": {"$search": text}}, {"_id": 0, "title": 1}).limit(5))

def run_independent_queries(db):
    # A diferencia del gather asíncrono, aquí las operaciones bloquean el hilo
    # y deben esperar a que termine la anterior para comenzar.
    res1 = find_movies_by_year_and_genre(db, 1999, "Action")
    res2 = aggregate_movies_by_genre(db)
    res3 = search_movies_by_regex(db, "Matrix")
    
    return [res1, res2, res3]

def run_queries_threadpool(db, workers=3):
    """Ejecuta las tres consultas independientes con hilos."""
    functions = (
        lambda: find_movies_by_year_and_genre(db, 1999, "Action"),
        lambda: aggregate_movies_by_genre(db),
        lambda: search_movies_by_regex(db, "Matrix"),
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(lambda function: function(), functions))