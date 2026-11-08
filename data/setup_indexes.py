from pymongo import ASCENDING, TEXT
from src.common.config import DB_NAME
from src.sync_app.db import get_sync_client, get_sync_db

def _show_explain(db, name, query, projection=None, sort=None):
    cursor = db.movies.find(query, projection)
    if sort:
        cursor = cursor.sort(*sort)
    # PyMongo 4: Cursor.explain() no acepta argumentos y ya incluye executionStats
    explanation = cursor.explain()
    stats = explanation.get("executionStats", {})
    stages = str(explanation.get("queryPlanner", {}).get("winningPlan", {}))
    scan = "IXSCAN" if "IXSCAN" in stages else "COLLSCAN"
    print(
        f"{name}: examinados={stats.get('totalDocsExamined', 'N/A')}, "
        f"devueltos={stats.get('nReturned', 'N/A')}, "
        f"tiempo={stats.get('executionTimeMillis', 'N/A')} ms, plan={scan}"
    )

def _find_key(data, key):
    """Busca 'key' en un resultado de explain anidado (en agregaciones no está en la raíz)."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = _find_key(value, key)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_key(item, key)
            if found:
                return found
    return {}

def _show_aggregate_explain(db):
    pipeline = [
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}},
        },
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    explanation = db.command(
        "explain",
        {"aggregate": "movies", "pipeline": pipeline, "cursor": {}},
        verbosity="executionStats",
    )
    stats = _find_key(explanation, "executionStats")
    text = str(explanation)
    print(
        f"Agregación: examinados={stats.get('totalDocsExamined', 'N/A')}, "
        f"devueltos={stats.get('nReturned', 'N/A')}, "
        f"tiempo={stats.get('executionTimeMillis', 'N/A')} ms, "
        f"plan={'IXSCAN' if 'IXSCAN' in text else 'COLLSCAN'}"
    )

def create_and_explain_indexes():
    client = get_sync_client()
    db = get_sync_db(DB_NAME, client)
    try:
        print("--- Antes de crear índices ---")
        _show_explain(db, "Compuesta", {"year": 1999, "genres": "Action"},
                      {"_id": 0, "title": 1, "year": 1}, ("title", 1))
        _show_explain(db, "Regex", {"title": {"$regex": "Matrix", "$options": "i"}},
                      {"_id": 0, "title": 1})
        _show_aggregate_explain(db)
        print("--- Creando Índices ---")
        db.movies.create_index([("year", ASCENDING), ("genres", ASCENDING), ("title", ASCENDING)])
        db.movies.create_index([("title", TEXT)])
        print("--- Después de crear índices ---")
        _show_explain(db, "Compuesta", {"year": 1999, "genres": "Action"},
                      {"_id": 0, "title": 1, "year": 1}, ("title", 1))
        _show_explain(db, "Regex", {"title": {"$regex": "Matrix", "$options": "i"}},
                      {"_id": 0, "title": 1})
        _show_aggregate_explain(db)
    finally:
        client.close()

if __name__ == "__main__":
    create_and_explain_indexes()