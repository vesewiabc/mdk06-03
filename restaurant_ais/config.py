import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Базовая конфигурация приложения."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    DATABASE = os.path.join(BASE_DIR, "restaurant.db")
    SCHEMA = os.path.join(BASE_DIR, "schema.sql")
    RESTAURANT_NAME = "Гурман"
