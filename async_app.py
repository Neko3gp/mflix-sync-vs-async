"""App asíncrona (PyMongo Async): carga masiva, CRUD y consultas sobre sample_mflix.movies."""
import asyncio
import re
import time

from pymongo import AsyncMongoClient, InsertOne
from pymongo.errors import BulkWriteError

MONGO_URI = "mongodb://localhost:27017"  # MongoDB local (Docker)
SOURCE_DB = "sample_mflix"  # base original: solo se lee
APP_DB = "mflix_async"      # copia donde trabaja esta app


def get_client():
    # Cada llamada crea un cliente asíncrono independiente para que el propietario
    # pueda cerrarlo con await cuando finalice su operación.
    return AsyncMongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) #tiempo de espera para la conexión


# ---------- Carga masiva ----------
async def load_movies_bulk(db, movies, batch_size=1000, concurrency=10): #tamaño del lote y concurrencia
    """Inserta los lotes con bulk_write; el Semaphore deja hasta `concurrency` a la vez."""
    # El semáforo evita lanzar más escrituras simultáneas de las configuradas.
    semaphore = asyncio.Semaphore(concurrency) #limita el número de operaciones concurrentes

    async def load_batch(batch): #carga un lote de películas
        # Cada lote adquiere un permiso y lo libera automáticamente al salir del bloque.
        async with semaphore:#semaforo para limitar la concurrencia
            try:
                # ordered=False deja que el servidor procese documentos independientes
                # aunque alguno del lote falle.
                result = await db.movies.bulk_write( #intenta insertar el lote de películas
                    [InsertOne(m) for m in batch], ordered=False #no se garantiza el orden de inserción
                )
                # En el camino normal no hay errores individuales.
                return result.inserted_count, 0
            except BulkWriteError as error:  # excepción si hay errores de escritura, como _id duplicado
                # BulkWriteError incluye tanto el número insertado como los errores
                # concretos, incluso cuando solo una parte del lote falló.
                return error.details["nInserted"], len(error.details["writeErrors"])

    async with asyncio.TaskGroup() as group: #agrupa las tareas de carga de lotes para ejecutarlas concurrentemente
        # Se crea una tarea por lote; TaskGroup espera a que todas terminen.
        tasks = [ #se le da la tarea de cargar cada lote al grupo de tareas
            group.create_task(load_batch(movies[i:i + batch_size]))
            for i in range(0, len(movies), batch_size) #divide la lista de películas en lotes
        ]

    # Las tareas ya terminaron al salir de TaskGroup, por lo que result() es seguro.
    results = [task.result() for task in tasks] #recoge los resultados de cada tarea
    # Se reducen los pares (insertados, fallidos) a un único resumen total.
    return {
        "inserted": sum(inserted for inserted, _ in results),#regresa el total de películas insertadas
        "failed": sum(failed for _, failed in results), #regresa el total de películas que fallaron al insertarse
    }


# ---------- CRUD ----------
async def create_movie(db, movie):
    # La validación evita insertar documentos que la aplicación no puede identificar.
    if not movie.get("title"):
        raise ValueError("La película debe tener 'title'.")
    # Se espera insert_one porque PyMongo Async no bloquea el hilo de la interfaz.
    return (await db.movies.insert_one(movie)).inserted_id


async def get_movie(db, movie_id):
    # find_one devuelve el documento o None cuando no existe el _id solicitado.
    return await db.movies.find_one({"_id": movie_id})


async def update_movie(db, movie_id, changes):
    # $set conserva los campos no incluidos en changes.
    result = await db.movies.update_one({"_id": movie_id}, {"$set": changes})
    # modified_count distingue una actualización efectiva de un _id inexistente
    # o de un documento que ya tenía esos mismos valores.
    return result.modified_count


async def delete_movie(db, movie_id):
    # Solo se devuelve la cantidad afectada, igual que en la implementación sync.
    return (await db.movies.delete_one({"_id": movie_id})).deleted_count


# ---------- Consultas ----------
async def find_movies_by_year_and_genre(db, year, genre, limit=10):
    """Filtro compuesto + proyección + orden por título."""
    # find devuelve un cursor asíncrono; la consulta se ejecuta al consumirlo.
    cursor = db.movies.find(
        {"year": year, "genres": genre}, {"_id": 0, "title": 1, "year": 1}
    ).sort("title", 1).limit(limit)
    # to_list consume el cursor sin bloquear el hilo que ejecuta asyncio.
    return await cursor.to_list()  # find() no se espera con await; to_list() sí


async def aggregate_movies_by_genre(db):
    """Top 5 de géneros con más películas."""
    # El pipeline separa arrays, cuenta cada género, ordena y conserva los cinco primeros.
    pipeline = [
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    # En PyMongo Async aggregate requiere await para obtener el cursor.
    cursor = await db.movies.aggregate(pipeline)  # aggregate() sí se espera con await
    # La materialización asíncrona permite consumir todos los documentos del cursor.
    return await cursor.to_list()


async def search_movies_by_regex(db, text):
    """Títulos que contienen el texto, sin importar mayúsculas."""
    # Escapar el texto evita que caracteres especiales del usuario cambien el patrón.
    query = {"title": {"$regex": re.escape(text), "$options": "i"}}
    # La proyección excluye _id y el límite protege la salida de la demostración.
    cursor = db.movies.find(query, {"_id": 0, "title": 1}).limit(5)
    return await cursor.to_list()


async def run_queries_gather(db):
    """Las tres consultas independientes al mismo tiempo con asyncio.gather()."""
    # gather inicia las operaciones juntas y conserva el orden de las expresiones.
    return await asyncio.gather(
        find_movies_by_year_and_genre(db, 1999, "Action"),
        aggregate_movies_by_genre(db),
        search_movies_by_regex(db, "Matrix"),
    )


async def run_queries_taskgroup(db):
    """Las mismas tres consultas con asyncio.TaskGroup()."""
    async with asyncio.TaskGroup() as group:
        # Cada consulta se convierte en una tarea administrada por el grupo.
        tasks = [
            group.create_task(find_movies_by_year_and_genre(db, 1999, "Action")),
            group.create_task(aggregate_movies_by_genre(db)),
            group.create_task(search_movies_by_regex(db, "Matrix")),
        ]
    # Al salir del contexto todas las tareas terminaron; entonces se pueden leer.
    return [task.result() for task in tasks]


# ---------- Demostración ----------
async def main():
    # El cierre en finally evita dejar conexiones abiertas ante cualquier excepción.
    client = get_client()
    try:
        # Se lee la fuente completa antes de recrear la base de la aplicación.
        movies = await client[SOURCE_DB].movies.find().to_list()
        # Una fuente vacía termina la demostración sin ejecutar escrituras innecesarias.
        if not movies:
            print(f"{SOURCE_DB}.movies está vacía o no existe.")
            return
        print(f"Películas leídas de {SOURCE_DB}: {len(movies)}")

        db = client[APP_DB]
        # Cada ejecución comienza con una copia limpia y reproducible.
        await db.movies.drop()
        start = time.perf_counter()
        result = await load_movies_bulk(db, movies)
        print(f"Carga masiva: {result} en {time.perf_counter() - start:.2f} s")

        movie_id = await create_movie(db, {"title": "Película de prueba", "year": 2024})
        # Se usa el mismo identificador para demostrar leer, actualizar y eliminar.
        print("Crear:", movie_id)
        print("Leer:", await get_movie(db, movie_id))
        print("Actualizar (modificadas):", await update_movie(db, movie_id, {"year": 2025}))
        print("Eliminar (eliminadas):", await delete_movie(db, movie_id))

        start = time.perf_counter()
        # gather permite comparar las tres consultas concurrentes en una sola medición.
        year_genre, top_genres, matrix = await run_queries_gather(db)
        print(f"Consultas con gather(): {time.perf_counter() - start:.3f} s")
        start = time.perf_counter()
        # TaskGroup ofrece una alternativa estructurada para las mismas consultas.
        await run_queries_taskgroup(db)
        print(f"Consultas con TaskGroup(): {time.perf_counter() - start:.3f} s")
        print("Año 1999 + Action:", year_genre)
        print("Top géneros:", top_genres)
        print("Títulos con 'Matrix':", matrix)
    finally:
        # AsyncMongoClient debe cerrarse con await para liberar sus recursos asíncronos.
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())