"""Exporta sample_mflix.movies (Atlas) a data/movies.json (Extended JSON, un documento por línea)."""
import argparse
from pathlib import Path

from bson import json_util

from src.common.config import SOURCE_DB
from src.sync_app.db import get_sync_client

OUTPUT = Path("data/movies.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Máximo de documentos a exportar")
    args = parser.parse_args()
    client = get_sync_client()
    try:
        total = client[SOURCE_DB].movies.estimated_document_count()
        if total == 0:
            print(f"{SOURCE_DB}.movies está vacía o no existe. En Atlas: Database > ... > Load Sample Dataset.")
            return 1
        OUTPUT.parent.mkdir(exist_ok=True)
        count = 0
        with OUTPUT.open("w", encoding="utf-8") as file:
            cursor = client[SOURCE_DB].movies.find()
            if args.limit is not None:
                cursor = cursor.limit(args.limit)
            for doc in cursor:
                file.write(json_util.dumps(doc, ensure_ascii=False) + "\n")
                count += 1
        print(f"Exportados {count} documentos de {SOURCE_DB}.movies a {OUTPUT}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())