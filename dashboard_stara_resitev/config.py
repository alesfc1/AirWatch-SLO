import os

# postgres connection config
DB_HOST = os.getenv("DATABASE_HOST", os.getenv("DB_HOST", "127.0.0.1"))
DB_PORT = os.getenv("DATABASE_PORT", os.getenv("DB_PORT", "5433"))
DB_NAME = os.getenv("DATABASE_NAME", os.getenv("DB_NAME", "airwatch"))
DB_USER = os.getenv("DATABASE_USER", os.getenv("DB_USER", "airwatch"))
DB_PASSWORD = os.getenv("DATABASE_PASSWORD", os.getenv("DB_PASSWORD", "airwatch"))

