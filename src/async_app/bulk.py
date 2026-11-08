import asyncio
from copy import deepcopy

from pymongo import InsertOne
from pymongo.errors import BulkWriteError


async def load_movies_bulk(db, movies_data, batch_size=1000, concurrency=10):
    """Carga documentos por lotes y devuelve insertados, fallidos y errores."""
    collection = db.movies
    sem = asyncio.Semaphore(concurrency)

    async def process_batch(batch):
        try:
            requests = [InsertOne(deepcopy(doc)) for doc in batch]
            async with sem:
                result = await collection.bulk_write(requests, ordered=False)
                return result.inserted_count, 0, None
        except BulkWriteError as error:
            details = error.details
            return (
                details.get("nInserted", 0),
                len(details.get("writeErrors", [])),
                str(error),
            )
        except Exception as error:
            return 0, len(batch), str(error)

    async with asyncio.TaskGroup() as task_group:
        tasks = [
            task_group.create_task(process_batch(movies_data[i:i + batch_size]))
            for i in range(0, len(movies_data), batch_size)
        ]

    results = [task.result() for task in tasks]
    return {
        "inserted": sum(inserted for inserted, _, _ in results),
        "failed": sum(failed for _, failed, _ in results),
        "errors": [error for _, _, error in results if error],
    }
