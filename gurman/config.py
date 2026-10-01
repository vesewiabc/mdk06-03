"""Конфигурация и общие константы приложения."""
import os
import re

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Окружение. Используется для безопасных дефолтов.
_IS_PROD = (
    os.environ.get("FLASK_ENV") == "production"
    or os.environ.get("APP_ENV") == "production"
)


class Config:
    DATABASE = os.path.join(BASE_DIR, "restaurant.db")
    RESTAURANT_NAME = "Гурман"

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Secure cookie: в production — всегда True (нельзя выключить).
    # Локально включается только явным SESSION_COOKIE_SECURE=1.
    SESSION_COOKIE_SECURE = (
        _IS_PROD
        or os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    )
    SESSION_COOKIE_NAME = "gurman_sid"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    # FIX A02: Flask 3.1+ умеет проверять Host автоматически.
    _trusted_hosts_raw = (os.environ.get("TRUSTED_HOSTS") or "").strip()
    TRUSTED_HOSTS = (
        [h.strip() for h in _trusted_hosts_raw.split(",") if h.strip()]
        or None
    )

    # FIX A07: CSRF-токен живёт 1 час.
    WTF_CSRF_TIME_LIMIT = 60 * 60

    # Демо-учётки: только вне production И только явным флагом.
    # Двойное условие исключает случайный показ паролей в prod,
    # даже если переменная окружения осталась в .env.
    SHOW_DEMO_ACCOUNTS = (
        not _IS_PROD
        and os.environ.get("SHOW_DEMO_ACCOUNTS", "0") == "1"
    )

    TRUSTED_PROXIES = int(os.environ.get("TRUSTED_PROXIES", "0") or "0")


# ---------- Роли ----------
ROLE_LABELS = {
    "admin": "Администратор",
    "waiter": "Официант",
    "cook": "Повар",
    "bartender": "Бармен",
    "storekeeper": "Кладовщик",
    "accountant": "Бухгалтер",
}
ROLE_VALUES = set(ROLE_LABELS.keys())

# ---------- Регулярки ----------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{5,25}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# ---------- Пароли ----------
PASSWORD_MIN = 12
PASSWORD_MAX = 128

_COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd",
    "qwerty", "qwerty123", "qwertyuiop", "1234567890",
    "12345678", "123456789", "1234567890", "admin123", "admin1234",
    "waiter123", "cook123", "bar123", "letmein", "welcome",
    "iloveyou", "monkey", "dragon", "111111111", "00000000",
}

_SEQ_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
_SEQ_SET = {
    _SEQ_ALPHABET[i:i + 6]
    for i in range(len(_SEQ_ALPHABET) - 5)
} | {
    _SEQ_ALPHABET[::-1][i:i + 6]
    for i in range(len(_SEQ_ALPHABET) - 5)
}

# ---------- Демо-учётки ----------
# Единственный источник правды. Используется в db._seed_demo_users()
# и в blueprints.dashboard.register_globals(). UI-показ возможен только
# при Config.SHOW_DEMO_ACCOUNTS == True (что в prod недостижимо).
DEMO_ACCOUNTS = [
    {
        "role": "admin",
        "role_label": "Администратор",
        "login": "admin",
        "password": "admin123456",
        "full_name": "Администратор Системы",
        "position": None,
        "phone": None,
        "salary": None,
    },
    {
        "role": "waiter",
        "role_label": "Официант",
        "login": "waiter1",
        "password": "waiter12345",
        "full_name": "Иванова Анна",
        "position": "Официант",
        "phone": "+7 900 111-11-11",
        "salary": 45000,
    },
    {
        "role": "cook",
        "role_label": "Повар",
        "login": "cook1",
        "password": "cook123456",
        "full_name": "Петров Сергей",
        "position": "Повар",
        "phone": "+7 900 222-22-22",
        "salary": 55000,
    },
    {
        "role": "bartender",
        "role_label": "Бармен",
        "login": "bartender1",
        "password": "bar1234567",
        "full_name": "Сидорова Мария",
        "position": "Бармен",
        "phone": "+7 900 333-33-33",
        "salary": 42000,
    },
    {
        "role": "storekeeper",
        "role_label": "Кладовщик",
        "login": "storekeeper1",
        "password": "store123456",
        "full_name": "Кузнецов Олег",
        "position": "Кладовщик",
        "phone": "+7 900 444-44-44",
        "salary": 40000,
    },
    {
        "role": "accountant",
        "role_label": "Бухгалтер",
        "login": "accountant1",
        "password": "acc1234567",
        "full_name": "Смирнова Елена",
        "position": "Бухгалтер",
        "phone": "+7 900 555-55-55",
        "salary": 60000,
    },
]