from copy import deepcopy

from pymongo import InsertOne
from pymongo.errors import BulkWriteError


def load_movies_bulk(db, movies_data, batch_size=1000, concurrency=10):
    """Carga documentos por lotes y devuelve insertados, fallidos y errores."""
    collection = db.movies
    inserted_count = 0
    failed_count = 0
    errors = []

    for i in range(0, len(movies_data), batch_size):
        batch = movies_data[i:i + batch_size]
        requests = [InsertOne(deepcopy(doc)) for doc in batch]
        try:
            result = collection.bulk_write(requests, ordered=False)
            inserted_count += result.inserted_count
        except BulkWriteError as error:
            inserted_count += error.details.get("nInserted", 0)
            failed_count += len(error.details.get("writeErrors", []))
            errors.append(str(error))
        except Exception as error:
            failed_count += len(batch)
            errors.append(str(error))

    return {"inserted": inserted_count, "failed": failed_count, "errors": errors}
