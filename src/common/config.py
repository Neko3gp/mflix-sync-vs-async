import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "")
DB_NAME = os.getenv("DB_NAME", "mflix_demo")
SOURCE_DB = os.getenv("SOURCE_DB", "sample_mflix")
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "mflix_test")