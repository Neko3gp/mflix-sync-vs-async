import asyncio
import re

async def find_movies_by_year_and_genre(db, year, genre, limit=10):
    query = {"year": year, "genres": genre}
    projection = {"_id": 0, "title": 1, "year": 1}
    # En motor/pymongo async, los cursores se evalúan con to_list()
    cursor = db.movies.find(query, projection).sort("title", 1).limit(limit)
    return await cursor.to_list(length=limit)

async def aggregate_movies_by_genre(db):
    pipeline = [
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    # CORRECCIÓN: Se requiere await porque aggregate contacta al servidor inmediatamente
    cursor = await db.movies.aggregate(pipeline)
    return await cursor.to_list(length=5)

async def search_movies_by_regex(db, pattern):
    query = {"title": {"$regex": re.escape(pattern), "$options": "i"}}
    projection = {"_id": 0, "title": 1}
    cursor = db.movies.find(query, projection).limit(5)
    return await cursor.to_list(length=5)

async def search_movies_by_text(db, text):
    """Busca palabras usando el índice de texto."""
    cursor = db.movies.find({"$text": {"$search": text}}, {"_id": 0, "title": 1}).limit(5)
    return await cursor.to_list(length=5)

async def run_independent_queries(db):
    # Justificación: gather lanza consultas disjuntas simultáneamente, 
    # ahorrando latencia de red (el total es el tiempo de la consulta más lenta, no la suma de todas).
    results = await asyncio.gather(
        find_movies_by_year_and_genre(db, 1999, "Action"),
        aggregate_movies_by_genre(db),
        search_movies_by_regex(db, "Matrix")
    )
    return results

async def run_queries_taskgroup(db):
    """Ejecuta las tres consultas independientes con TaskGroup."""
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(find_movies_by_year_and_genre(db, 1999, "Action")),
            group.create_task(aggregate_movies_by_genre(db)),
            group.create_task(search_movies_by_regex(db, "Matrix")),
        ]
    return [task.result() for task in tasks]