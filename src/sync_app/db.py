from pymongo import MongoClient
from src.common.config import DB_NAME, MONGO_URI

def get_sync_client():
    """Crea un cliente síncrono reutilizable."""
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


def get_sync_db(db_name=DB_NAME, client=None):
    """Devuelve una base usando el cliente indicado o uno nuevo."""
    return (client or get_sync_client())[db_name]