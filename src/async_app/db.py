from pymongo import AsyncMongoClient
from src.common.config import DB_NAME, MONGO_URI

def get_async_client():
    """Crea un cliente asíncrono reutilizable."""
    return AsyncMongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


def get_async_db(db_name=DB_NAME, client=None):
    """Devuelve una base usando el cliente indicado o uno nuevo."""
    return (client or get_async_client())[db_name]