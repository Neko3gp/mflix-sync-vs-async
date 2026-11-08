from bson import ObjectId

MENSAJE_ID = "Error: El '_id' debe ser válido."

def _validate_id(movie_id):
    if movie_id is None or movie_id == "" or (isinstance(movie_id, str) and not ObjectId.is_valid(movie_id)):
        raise ValueError(MENSAJE_ID)

def create_movie(db, movie_data):
    """Crea una película y devuelve su identificador."""
    if not movie_data.get("title"):
        raise ValueError("Error: El documento debe contener al menos un 'title'.")
    if "_id" in movie_data:
        _validate_id(movie_data["_id"])
    result = db.movies.insert_one(movie_data)
    return result.inserted_id

def get_movie(db, movie_id):
    """Obtiene una película por identificador."""
    _validate_id(movie_id)
    return db.movies.find_one({"_id": movie_id})

def update_movie(db, movie_id, update_data):
    """Actualiza una película y devuelve coincidencias y modificaciones."""
    _validate_id(movie_id)
    result = db.movies.update_one({"_id": movie_id}, {"$set": update_data})
    return {"matched_count": result.matched_count, "modified_count": result.modified_count}

def delete_movie(db, movie_id):
    """Elimina una película por identificador."""
    _validate_id(movie_id)
    result = db.movies.delete_one({"_id": movie_id})
    return result.deleted_count
    
def delete_many_movies(db, filter_query):
    """Elimina películas que coincidan con un filtro."""
    result = db.movies.delete_many(filter_query)
    return result.deleted_count

def create_many_movies(db, movies_data):
    """Crea varias películas y devuelve los identificadores."""
    if any(not movie.get("title") for movie in movies_data):
        raise ValueError("Error: El documento debe contener al menos un 'title'.")
    result = db.movies.insert_many(movies_data)
    return result.inserted_ids

def get_movies(db, filter_query=None, limit=0):
    """Obtiene películas aplicando filtro y límite."""
    cursor = db.movies.find(filter_query or {})
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)