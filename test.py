import asyncio
from src.sync_app.db import get_sync_client, get_sync_db
from src.async_app.db import get_async_client, get_async_db

def test_sync():
    client = get_sync_client()
    try:
        get_sync_db(client=client).command("ping")
        print("Conexión Síncrona: OK")
    finally:
        client.close()

async def test_async():
    client = get_async_client()
    try:
        await get_async_db(client=client).command("ping")
        print("Conexión Asíncrona: OK")
    finally:
        await client.close()

if __name__ == "__main__":
    test_sync()
    asyncio.run(test_async())