"""
Общие фикстуры для тестов.

Ключевые решения:
- SHOW_DEMO_ACCOUNTS=1 выставляется ДО импорта config, чтобы seed
  создал предсказуемых пользователей (admin/admin123456 и т.д.).
- Config.DATABASE подменяется на временный файл. db.get_db() читает
  атрибут класса Config, а не current_app.config, поэтому патчим
  сам класс (см. db.py — там же оставлен комментарий).
- CSRF в тестах выключается: тесты не гоняют реальный HTML-парсинг.
  Отдельный тест проверяет, что CSRF-защита включена в проде.
"""
import os
import tempfile

# --- ВАЖНО: выставить ДО импорта config/db/app -------------------
os.environ.setdefault("SHOW_DEMO_ACCOUNTS", "1")
os.environ.setdefault("DEBUG", "0")
# -----------------------------------------------------------------

import pytest  # noqa: E402

import config as config_module  # noqa: E402
from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from db import get_db  # noqa: E402


# Демо-пароли из config.DEMO_ACCOUNTS — единый источник правды.
DEMO_PASSWORDS = {
    "admin": "admin123456",
    "waiter1": "waiter12345",
    "cook1": "cook123456",
    "bartender1": "bar1234567",
    "storekeeper1": "store123456",
    "accountant1": "acc1234567",
}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """Свежее приложение на временной SQLite-БД."""
    db_path = tmp_path / "test.db"

    # Патчим и класс, и инстанс-конфиг — на случай, если код начнёт
    # читать из current_app.config.
    monkeypatch.setattr(Config, "DATABASE", str(db_path), raising=False)
    monkeypatch.setattr(config_module.Config, "DATABASE", str(db_path), raising=False)

    application = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-secret-not-for-prod",
            "DATABASE": str(db_path),
            "SHOW_DEMO_ACCOUNTS": True,
        }
    )
    # create_app вызывает ensure_db() — на пустом файле сидирует демо.
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


def login(client, username, password=None):
    """Логин. Возвращает response (для проверки redirect/200)."""
    if password is None:
        password = DEMO_PASSWORDS[username]
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


@pytest.fixture()
def login_as():
    """Фабрика: login_as(client, 'waiter1') → response."""
    return login


@pytest.fixture()
def db(app):
    """Прямой доступ к БД внутри app_context (для подготовки данных)."""
    with app.app_context():
        yield get_db()