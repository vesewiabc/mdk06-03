"""Единая точка хеширования паролей.

Отдельный модуль без зависимостей от БД/HTTP — чтобы db.py,
utils.py и blueprints могли импортировать hash_password() без
циклических импортов.
"""
from werkzeug.security import generate_password_hash

PASSWORD_HASH_METHOD = "pbkdf2:sha256:600000"


def hash_password(pw: str) -> str:
    """Хеширует пароль единым методом (PBKDF2-SHA256, 600 000 итераций).

    Единственная разрешённая точка хеширования — при смене метода
    правится только здесь.
    """
    return generate_password_hash(pw, method=PASSWORD_HASH_METHOD)