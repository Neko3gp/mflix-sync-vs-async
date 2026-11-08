import asyncio
import pytest
import pytest_asyncio
from bson import ObjectId

from src.async_app.bulk import load_movies_bulk as async_load
from src.async_app.crud import create_movie as async_create, delete_movie as async_delete, get_movie as async_get, update_movie as async_update
from src.async_app.db import get_async_client, get_async_db
from src.async_app.queries import aggregate_movies_by_genre as async_aggregate, find_movies_by_year_and_genre as async_find, search_movies_by_regex as async_regex
from src.common.config import TEST_DB_NAME
from src.sync_app.bulk import load_movies_bulk as sync_load
from src.sync_app.crud import create_movie as sync_create, delete_movie as sync_delete, get_movie as sync_get, update_movie as sync_update
from src.sync_app.db import get_sync_client, get_sync_db
from src.sync_app.queries import aggregate_movies_by_genre as sync_aggregate, find_movies_by_year_and_genre as sync_find, search_movies_by_regex as sync_regex


@pytest.fixture
def sync_db():
    client = get_sync_client()
    db = get_sync_db(TEST_DB_NAME, client)
    db.movies.delete_many({})
    yield db
    db.movies.delete_many({})
    client.close()


@pytest_asyncio.fixture
async def async_db():
    client = get_async_client()
    db = get_async_db(TEST_DB_NAME, client)
    await db.movies.delete_many({})
    yield db
    await db.movies.delete_many({})
    await client.close()


def test_query_equivalence(sync_db):
    documents = [
        {"_id": ObjectId(), "title": "The Matrix", "year": 1999, "genres": ["Action"]},
        {"_id": ObjectId(), "title": "Action Film", "year": 1999, "genres": ["Action"]},
    ]
    sync_db.movies.insert_many(documents)
    expected = [sync_find(sync_db, 1999, "Action"), sync_aggregate(sync_db), sync_regex(sync_db, "Matrix")]

    async def compare():
        client = get_async_client()
        try:
            db = get_async_db(TEST_DB_NAME, client)
            actual = [await async_find(db, 1999, "Action"), await async_aggregate(db), await async_regex(db, "Matrix")]
            return actual
        finally:
            await client.close()

    assert expected == asyncio.run(compare())


@pytest.mark.asyncio
async def test_queries_async(async_db):
    await async_db.movies.insert_many([
        {"_id": ObjectId(), "title": "The Matrix", "year": 1999, "genres": ["Action"]},
        {"_id": ObjectId(), "title": "Action Film", "year": 1999, "genres": ["Action"]},
    ])
    assert await async_find(async_db, 1999, "Action") == [
        {"title": "Action Film", "year": 1999}, {"title": "The Matrix", "year": 1999}
    ]
    assert await async_aggregate(async_db) == await async_aggregate(async_db)
    assert await async_regex(async_db, "Matrix") == [{"title": "The Matrix"}]


def test_crud_cycle(sync_db):
    movie_id = sync_create(sync_db, {"title": "Prueba", "year": 2024})
    assert sync_get(sync_db, movie_id)["title"] == "Prueba"
    assert sync_update(sync_db, movie_id, {"year": 2025}) == {"matched_count": 1, "modified_count": 1}
    assert sync_delete(sync_db, movie_id) == 1


@pytest.mark.asyncio
async def test_crud_cycle_async(async_db):
    movie_id = await async_create(async_db, {"title": "Prueba", "year": 2024})
    assert (await async_get(async_db, movie_id))["title"] == "Prueba"
    assert await async_update(async_db, movie_id, {"year": 2025}) == {"matched_count": 1, "modified_count": 1}
    assert await async_delete(async_db, movie_id) == 1


def test_bulk_duplicate_ids(sync_db):
    documents = [{"_id": ObjectId(), "title": "Uno"}]
    result = sync_load(sync_db, documents + documents, batch_size=2)
    assert result["inserted"] == 1
    assert result["failed"] == 1
    assert result["errors"]


@pytest.mark.asyncio
async def test_bulk_duplicate_ids_async(async_db):
    documents = [{"_id": ObjectId(), "title": "Uno"}]
    result = await async_load(async_db, documents + documents, batch_size=2)
    assert result["inserted"] == 1
    assert result["failed"] == 1
    assert result["errors"]


@pytest.mark.asyncio
async def test_bulk_200_documentos_equivalente(sync_db, async_db):
    documents = [
        {"_id": ObjectId(), "title": f"Película {index}"}
        for index in range(100)
    ]
    documents = documents + documents
    sync_result = sync_load(sync_db, documents, batch_size=25)
    await async_db.movies.delete_many({})
    async_result = await async_load(async_db, documents, batch_size=25)

    assert (sync_result["inserted"], sync_result["failed"]) == (
        async_result["inserted"],
        async_result["failed"],
    )
    assert (sync_result["inserted"], sync_result["failed"]) == (100, 100)
