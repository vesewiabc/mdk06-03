"""
АИС ресторана «Гурман» — единый модуль приложения.
Flask + SQLite + Flask-WTF (CSRF).

Запуск:
    python app.py

Переменные окружения:
    SECRET_KEY            — обязательно в проде
    SESSION_COOKIE_SECURE — "1" для HTTPS
    DEBUG                 — "1" для отладки
    TRUSTED_PROXIES       — число доверенных прокси (X-Forwarded-For)
    SHOW_DEMO_ACCOUNTS    — "1" для показа демо-учёток
    ENVIRONMENT           — "production" для строгих проверок
"""
import functools
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse
import click
from flask import (
    Blueprint, Flask, current_app, flash, g, redirect, render_template,
    request, session, url_for,
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash


# ==============================================================
# КОНФИГУРАЦИЯ
# ==============================================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    DATABASE = os.path.join(BASE_DIR, "restaurant.db")
    RESTAURANT_NAME = "Гурман"

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    SESSION_COOKIE_NAME = "gurman_sid"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    WTF_CSRF_TIME_LIMIT = 60 * 60 * 8

    SHOW_DEMO_ACCOUNTS = os.environ.get("SHOW_DEMO_ACCOUNTS", "0") == "1"

    TRUSTED_PROXIES = int(os.environ.get("TRUSTED_PROXIES", "0") or "0")


# ==============================================================
# СХЕМА БАЗЫ ДАННЫХ
# ==============================================================
SCHEMA_SQL = """
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS schedule;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS restock_requests;
DROP TABLE IF EXISTS stock_movements;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS tech_cards;
DROP TABLE IF EXISTS ingredients;
DROP TABLE IF EXISTS dishes;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS restaurant_tables;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'waiter', 'cook', 'bartender', 'storekeeper', 'accountant')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE restaurant_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number INTEGER UNIQUE NOT NULL,
    seats INTEGER NOT NULL DEFAULT 2,
    status TEXT NOT NULL DEFAULT 'free' CHECK (status IN ('free', 'occupied', 'reserved'))
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE dishes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    price REAL NOT NULL DEFAULT 0,
    description TEXT,
    station TEXT NOT NULL DEFAULT 'kitchen' CHECK (station IN ('kitchen', 'bar')),
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    unit TEXT NOT NULL DEFAULT 'кг',
    stock_qty REAL NOT NULL DEFAULT 0,
    min_qty REAL NOT NULL DEFAULT 0
);

CREATE TABLE tech_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dish_id INTEGER NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    qty_per_portion REAL NOT NULL,
    UNIQUE (dish_id, ingredient_id)
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER REFERENCES restaurant_tables(id) ON DELETE SET NULL,
    waiter_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'sent', 'served', 'paid', 'cancelled')),
    guests INTEGER NOT NULL DEFAULT 1,
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at TEXT
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    dish_id INTEGER NOT NULL REFERENCES dishes(id),
    qty INTEGER NOT NULL DEFAULT 1,
    price REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'cooking', 'ready', 'served', 'cancelled')),
    comment TEXT
);

CREATE TABLE stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    qty_change REAL NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('receipt', 'writeoff', 'inventory', 'order')),
    comment TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE restock_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    qty REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'approved', 'done', 'rejected')),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    position TEXT NOT NULL,
    phone TEXT,
    hired_at TEXT,
    salary REAL NOT NULL DEFAULT 0,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    work_date TEXT NOT NULL,
    shift_start TEXT NOT NULL,
    shift_end TEXT NOT NULL
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    ip TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_orders_status_table   ON orders(status, table_id);
CREATE INDEX idx_orders_closed_at      ON orders(closed_at);
CREATE INDEX idx_orders_waiter         ON orders(waiter_id);
CREATE INDEX idx_orders_created_at     ON orders(created_at);
CREATE INDEX idx_order_items_order     ON order_items(order_id);
CREATE INDEX idx_order_items_status    ON order_items(status);
CREATE INDEX idx_order_items_dish      ON order_items(dish_id);
CREATE INDEX idx_stock_mov_ingr        ON stock_movements(ingredient_id);
CREATE INDEX idx_stock_mov_created     ON stock_movements(created_at DESC);
CREATE INDEX idx_tech_cards_dish       ON tech_cards(dish_id);
CREATE INDEX idx_schedule_emp_date     ON schedule(employee_id, work_date);
CREATE INDEX idx_schedule_date         ON schedule(work_date);
CREATE INDEX idx_audit_log_created     ON audit_log(created_at DESC);
CREATE INDEX idx_audit_log_user        ON audit_log(user_id, created_at DESC);
CREATE INDEX idx_restock_status        ON restock_requests(status);
CREATE INDEX idx_dishes_station_active ON dishes(station, is_active);
"""


# ==============================================================
# РАБОТА С БД
# ==============================================================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            Config.DATABASE,
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=5.0,
            isolation_level=None,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA synchronous = NORMAL")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA_SQL)
    db.commit()


def seed_db():
    db = get_db()

    def h(pw):
        return generate_password_hash(pw, method="pbkdf2:sha256:600000")

    db.executemany(
        "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
        [
            ("admin", h("admin123456"), "Администратор Системы", "admin"),
            ("waiter1", h("waiter12345"), "Иванова Анна", "waiter"),
            ("cook1", h("cook123456"), "Петров Сергей", "cook"),
            ("bartender1", h("bar1234567"), "Сидорова Мария", "bartender"),
            ("storekeeper1", h("store123456"), "Кузнецов Олег", "storekeeper"),
            ("accountant1", h("acc1234567"), "Смирнова Елена", "accountant"),
        ],
    )

    db.executemany(
        "INSERT INTO restaurant_tables (number, seats) VALUES (?, ?)",
        [(i, 2 if i % 3 else 4) for i in range(1, 13)],
    )

    db.executemany(
        "INSERT INTO categories (name) VALUES (?)",
        [("Салаты",), ("Супы",), ("Горячее",), ("Десерты",), ("Напитки",), ("Бар",)],
    )

    db.executemany(
        "INSERT INTO ingredients (name, unit, stock_qty, min_qty) VALUES (?, ?, ?, ?)",
        [
            ("Картофель", "кг", 40, 10),
            ("Курица (филе)", "кг", 25, 8),
            ("Говядина", "кг", 15, 5),
            ("Лосось", "кг", 8, 3),
            ("Сыр Пармезан", "кг", 5, 2),
            ("Салат Айсберг", "кг", 6, 2),
            ("Томаты", "кг", 12, 4),
            ("Огурцы", "кг", 10, 3),
            ("Мука", "кг", 20, 5),
            ("Сливки", "л", 10, 3),
            ("Кофе (зерно)", "кг", 4, 1),
            ("Молоко", "л", 15, 5),
        ],
    )

    db.executemany(
        "INSERT INTO dishes (name, category_id, price, station) VALUES (?, ?, ?, ?)",
        [
            ("Цезарь с курицей", 1, 420, "kitchen"),
            ("Греческий салат", 1, 380, "kitchen"),
            ("Борщ", 2, 320, "kitchen"),
            ("Крем-суп грибной", 2, 340, "kitchen"),
            ("Стейк из говядины", 3, 890, "kitchen"),
            ("Лосось на гриле", 3, 950, "kitchen"),
            ("Паста Карбонара", 3, 460, "kitchen"),
            ("Тирамису", 4, 290, "kitchen"),
            ("Чизкейк", 4, 310, "kitchen"),
            ("Капучино", 5, 180, "bar"),
            ("Американо", 5, 150, "bar"),
            ("Морс домашний", 5, 160, "bar"),
        ],
    )

    db.executemany(
        "INSERT INTO tech_cards (dish_id, ingredient_id, qty_per_portion) VALUES (?, ?, ?)",
        [
            (1, 6, 0.15), (1, 5, 0.03), (1, 2, 0.12),
            (2, 6, 0.10), (2, 7, 0.08), (2, 8, 0.06),
            (3, 1, 0.20), (3, 3, 0.10),
            (5, 3, 0.30),
            (6, 4, 0.25),
            (7, 9, 0.08), (7, 10, 0.05),
            (10, 11, 0.02), (10, 12, 0.10),
            (11, 11, 0.02),
        ],
    )

    db.executemany(
        "INSERT INTO employees (full_name, position, phone, hired_at, salary, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("Иванова Анна", "Официант", "+7 900 111-11-11", str(date.today()), 45000, 2),
            ("Петров Сергей", "Повар", "+7 900 222-22-22", str(date.today()), 55000, 3),
            ("Сидорова Мария", "Бармен", "+7 900 333-33-33", str(date.today()), 42000, 4),
            ("Кузнецов Олег", "Кладовщик", "+7 900 444-44-44", str(date.today()), 40000, 5),
            ("Смирнова Елена", "Бухгалтер", "+7 900 555-55-55", str(date.today()), 60000, 6),
        ],
    )

    db.commit()


# Белый список миграций: имена таблиц/колонок жёстко зафиксированы,
# типы — константы. Никаких внешних источников.
_ALLOWED_MIGRATIONS = {
    "users": {
        "session_version": "INTEGER NOT NULL DEFAULT 1",
    },
    "audit_log": {
        "entity_type": "TEXT",
        "entity_id":   "INTEGER",
        "ip":          "TEXT",
    },
}
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _migrate_schema(db):
    """Идемпотентная миграция по белому списку."""
    for table, columns in _ALLOWED_MIGRATIONS.items():
        if not _IDENT_RE.fullmatch(table):
            continue

        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not exists:
            continue

        have = {
            row["name"]
            for row in db.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        for col, coltype in columns.items():
            if not _IDENT_RE.fullmatch(col):
                continue
            if col not in have:
                # col/coltype — из локального доверенного словаря
                db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {coltype}')
                print(f"[migrate] {table}.{col} добавлена")

    index_stmts = [
        "CREATE INDEX IF NOT EXISTS idx_orders_status_table   ON orders(status, table_id)",
        "CREATE INDEX IF NOT EXISTS idx_orders_closed_at      ON orders(closed_at)",
        "CREATE INDEX IF NOT EXISTS idx_orders_waiter         ON orders(waiter_id)",
        "CREATE INDEX IF NOT EXISTS idx_orders_created_at     ON orders(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_order     ON order_items(order_id)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_status    ON order_items(status)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_dish      ON order_items(dish_id)",
        "CREATE INDEX IF NOT EXISTS idx_stock_mov_ingr        ON stock_movements(ingredient_id)",
        "CREATE INDEX IF NOT EXISTS idx_stock_mov_created     ON stock_movements(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_tech_cards_dish       ON tech_cards(dish_id)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_emp_date     ON schedule(employee_id, work_date)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_date         ON schedule(work_date)",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_created     ON audit_log(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_user        ON audit_log(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_restock_status        ON restock_requests(status)",
        "CREATE INDEX IF NOT EXISTS idx_dishes_station_active ON dishes(station, is_active)",
    ]
    for sql in index_stmts:
        try:
            db.execute(sql)
        except sqlite3.OperationalError:
            pass

    db.commit()


def ensure_db():
    db = get_db()
    has_users = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()

    if has_users is None:
        db.executescript(SCHEMA_SQL)
        db.commit()
        seed_db()
        return

    _migrate_schema(db)

    count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count == 0:
        seed_db()


@click.command("init-db")
@click.option("--yes", is_flag=True, help="Подтвердить удаление всех данных.")
def init_db_command(yes):
    if not yes:
        click.confirm("Будут удалены ВСЕ данные. Продолжить?", abort=True)
    init_db()
    click.echo("База данных инициализирована.")


@click.command("seed-db")
def seed_db_command():
    seed_db()
    click.echo("База данных заполнена демонстрационными данными.")


# ==============================================================
# КОНСТАНТЫ И УТИЛИТЫ
# ==============================================================
ROLE_LABELS = {
    "admin": "Администратор",
    "waiter": "Официант",
    "cook": "Повар",
    "bartender": "Бармен",
    "storekeeper": "Кладовщик",
    "accountant": "Бухгалтер",
}
ROLE_VALUES = set(ROLE_LABELS.keys())
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{5,25}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PASSWORD_MIN = 12
PASSWORD_MAX = 128

# Тривиальные последовательности и слова. Не словарь — он не нужен,
# достаточно отсечь самое очевидное.
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd",
    "qwerty", "qwerty123", "qwertyuiop", "1234567890",
    "12345678", "123456789", "1234567890", "admin123", "admin1234",
    "waiter123", "cook123", "bar123", "letmein", "welcome",
    "iloveyou", "monkey", "dragon", "111111111", "00000000",
}

# Последовательности длиной >= 6 символов.
_SEQ_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
_SEQ_SET = {
    _SEQ_ALPHABET[i:i + 6]
    for i in range(len(_SEQ_ALPHABET) - 5)
} | {
    _SEQ_ALPHABET[::-1][i:i + 6]
    for i in range(len(_SEQ_ALPHABET) - 5)
}


def _password_ok(pw: str, *, username: str = "", full_name: str = "") -> str | None:
    if not isinstance(pw, str):
        return "Некорректный пароль."
    if len(pw) < PASSWORD_MIN:
        return f"Пароль должен содержать минимум {PASSWORD_MIN} символов."
    if len(pw) > PASSWORD_MAX:
        return f"Пароль слишком длинный (максимум {PASSWORD_MAX})."
    if not re.search(r"[A-Za-z]", pw):
        return "Пароль должен содержать хотя бы одну букву."
    if not re.search(r"\d", pw):
        return "Пароль должен содержать хотя бы одну цифру."

    low = pw.lower()

    if low in _COMMON_PASSWORDS:
        return "Пароль слишком простой (в списке распространённых)."

    # Совпадение с логином/ФИО — нельзя.
    if username and username.lower() in low:
        return "Пароль не должен содержать логин."
    if full_name:
        # Разбиваем ФИО на слова, игнорируем короткие.
        for word in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", full_name.lower()):
            if word in low:
                return "Пароль не должен содержать имя/фамилию."

    # Последовательности "abcdef", "123456".
    for seq in _SEQ_SET:
        if seq in low:
            return "Пароль содержит тривиальную последовательность."

    # Одинаковые символы "aaaaaaaaaa".
    if len(set(pw)) < 4:
        return "Пароль слишком однообразный."

    return None


# ---- Денежный хелпер: единая точка округления до копеек ----
def money(x) -> float:
    """Округление до копеек. NaN/Inf → 0.0 (защита от порчи данных)."""
    if x is None:
        return 0.0
    try:
        d = Decimal(str(x))
    except Exception:
        return 0.0
    if not d.is_finite():
        return 0.0
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

import math
from urllib.parse import unquote

def safe_float(raw, *, min_=None, max_=None, default=None):
    """
    Безопасный парсинг float из пользовательского ввода.
    Возвращает None при любой ошибке (не число, NaN, ±Inf, выход за границы).
    """
    if raw is None:
        return default
    try:
        # Пользователь может ввести "1,5" — заменяем запятую
        v = float(str(raw).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if min_ is not None and v < min_:
        return None
    if max_ is not None and v > max_:
        return None
    return v


def safe_int(raw, *, min_=None, max_=None, default=None):
    """Безопасный парсинг int: '1e5', '1.5', 'nan' — всё отсекается."""
    if raw is None:
        return default
    try:
        # int("1.5") бросит ValueError, int("1e5") тоже — это то, что нужно
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if min_ is not None and v < min_:
        return None
    if max_ is not None and v > max_:
        return None
    return v

# Dummy-хэш нужен для защиты от timing-атак (user enumeration).
# Считаем его один раз при старте, а не лениво — чтобы первый
# неудачный логин не отличался по времени от последующих.
_dummy_hash_cache: str | None = None
_dummy_hash_lock = threading.Lock()


def _get_dummy_hash() -> str:
    global _dummy_hash_cache
    if _dummy_hash_cache is None:
        with _dummy_hash_lock:
            if _dummy_hash_cache is None:
                _dummy_hash_cache = generate_password_hash(
                    "dummy-password-for-timing-only",
                    method="pbkdf2:sha256:600000",
                )
    return _dummy_hash_cache


def warmup_dummy_hash() -> None:
    """Прогреть dummy-хэш до первого запроса."""
    _get_dummy_hash()

def _is_safe_url(target: str) -> bool:
    """Разрешает только относительные пути вида /path?query."""
    if not target or not isinstance(target, str):
        return False
    if len(target) > 2000:
        return False

    # Сначала декодируем — защита от %2F%2F, %09 и прочих трюков.
    decoded = unquote(target)

    # Управляющие символы и обратные слэши — сразу отказ.
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in decoded):
        return False
    if "\\" in decoded:
        return False

    # Protocol-relative //evil.com — отказ.
    if decoded.startswith("//"):
        return False

    p = urlparse(decoded)

    # Абсолютные URL с scheme/netloc — отказ.
    if p.scheme or p.netloc:
        return False

    # Должен быть локальный путь, начинающийся с одного "/".
    if not p.path.startswith("/") or p.path.startswith("//"):
        return False

    return True

def _default_landing(role: str) -> str:
    return {
        "cook":        url_for("orders.kitchen_view"),
        "bartender":   url_for("orders.kitchen_view"),
        "storekeeper": url_for("warehouse.stock"),
        "accountant":  url_for("reports.index"),
    }.get(role, url_for("index"))


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.path))
            if g.user["role"] not in roles and g.user["role"] != "admin":
                flash("Недостаточно прав для выполнения этого действия.", "error")
                return redirect(url_for("index"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def log_action(action, entity_type=None, entity_id=None):
    """Запись в журнал аудита.
    Колонки entity_type/entity_id/ip гарантированы _migrate_schema,
    которая вызывается в ensure_db при старте приложения.
    IP: за прокси ProxyFix уже подставляет реальный адрес клиента."""
    db = get_db()
    user_id = g.user["id"] if g.user else None
    ip = request.remote_addr if request else None
    db.execute(
        "INSERT INTO audit_log (user_id, action, entity_type, entity_id, ip) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, action, entity_type, entity_id, ip),
    )


# ==============================================================
# ПОДСИСТЕМА: АВТОРИЗАЦИЯ
# ==============================================================
auth = Blueprint("auth", __name__, url_prefix="/auth")


@auth.before_app_request
def load_logged_in_user():
    if request.endpoint == "static":
        g.user = None
        return

    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        return

    db = get_db()
    row = db.execute(
        "SELECT id, username, full_name, role, is_active, session_version "
        "FROM users WHERE id = ? AND is_active = 1",
        (user_id,),
    ).fetchone()

    if row is None:
        session.clear()
        g.user = None
        return

    # Безопасное чтение session_version: если колонки вдруг нет (старый
    # sqlite3.Row), считаем версию = 1 и не ломаем приложение.
    try:
        db_sv = row["session_version"]
    except (KeyError, IndexError):
        db_sv = 1

    if session.get("sv", 1) != db_sv:
        session.clear()
        g.user = None
        return

    g.user = row

@auth.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        # Отсекаем нестандартные Content-Type (мелочь, но полезно)
        ctype = (request.content_type or "").lower()
        if ctype and "application/x-www-form-urlencoded" not in ctype \
                and "multipart/form-data" not in ctype:
            flash("Некорректный формат запроса.", "error")
            return render_template("auth/login.html"), 415

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = request.remote_addr or "?"

        if login_limiter.is_blocked(ip, username):
            flash("Слишком много попыток входа. Повторите позже.", "error")
            return render_template("auth/login.html"), 429

        db = get_db()
        error = None
        user = None

        if not username or not password:
            error = "Введите логин и пароль."
            # Постоянное время: проверяем фиктивный хэш против введённого пароля
            check_password_hash(_get_dummy_hash(), password)
        else:
            user = db.execute(
                "SELECT id, username, password_hash, full_name, role, is_active, "
                "       session_version "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()

            stored = user["password_hash"] if user else _get_dummy_hash()
            password_ok = check_password_hash(stored, password)

            if user is None or not password_ok:
                error = "Неверный логин или пароль."
            elif not user["is_active"]:
                error = "Учётная запись отключена."

        if error is None:
            login_limiter.reset(ip, username)
            session.clear()
            # Админ — «постоянная» (8ч), остальные — браузерная сессия
            session.permanent = (user["role"] == "admin")
            session["user_id"] = user["id"]
            session["sv"] = user["session_version"]
            g.user = user
            log_action(f"Вход в систему: {user['username']}")

            next_url = request.args.get("next") or request.form.get("next")
            if next_url and _is_safe_url(next_url):
                return redirect(next_url)
            return redirect(_default_landing(user["role"]))

        login_limiter.register_failure(ip, username)
        log_action(f"Неудачная попытка входа: {username!r}")
        flash(error, "error")

    return render_template("auth/login.html")


@auth.route("/logout", methods=("POST",))
def logout():
    if g.user:
        log_action(f"Выход из системы: {g.user['username']}")
    session.clear()
    return redirect(url_for("auth.login"))


@auth.route("/users")
@roles_required("admin")
def users():
    db = get_db()
    rows = db.execute(
        "SELECT id, username, full_name, role, is_active, created_at "
        "FROM users ORDER BY id"
    ).fetchall()
    return render_template("auth/users.html", users=rows, role_labels=ROLE_LABELS)


def _password_ok(pw: str) -> str | None:
    if len(pw) < PASSWORD_MIN:
        return f"Пароль должен содержать минимум {PASSWORD_MIN} символов."
    if not re.search(r"[A-Za-z]", pw):
        return "Пароль должен содержать хотя бы одну букву."
    if not re.search(r"\d", pw):
        return "Пароль должен содержать хотя бы одну цифру."
    if pw.lower() in {"password", "qwerty", "12345678", "admin123", "waiter123"}:
        return "Пароль слишком простой."
    return None


@auth.route("/users/new", methods=("GET", "POST"))
@roles_required("admin")
def new_user():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        full_name = (request.form.get("full_name") or "").strip()
        role = request.form.get("role") or ""
        password = request.form.get("password") or ""
        password_confirm = request.form.get("password_confirm") or ""
        db = get_db()
        error = None

        if not username or not password or not full_name:
            error = "Заполните все обязательные поля."
        elif not USERNAME_RE.match(username):
            error = "Логин: 3–32 символа, латиница, цифры, «.», «_», «-»."
        elif len(full_name) > 200:
            error = "ФИО слишком длинное."
        elif password != password_confirm:
            error = "Пароли не совпадают."
        else:
            pwd_err = _password_ok(password, username=username, full_name=full_name)
            if pwd_err:
                error = pwd_err
            elif role not in ROLE_VALUES:
                error = "Некорректная роль."
            elif db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
                error = "Такой логин уже занят."

        if error:
            flash(error, "error")
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, role) "
                "VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password, method="pbkdf2:sha256:600000"),
                 full_name, role),
            )
            log_action(f"Создан пользователь {username} ({role})",
                       entity_type="user")
            flash("Пользователь создан.", "success")
            return redirect(url_for("auth.users"))

    return render_template("auth/user_form.html")


@auth.route("/users/<int:user_id>/toggle", methods=("POST",))
@roles_required("admin")
def toggle_user(user_id):
    db = get_db()

    if user_id == g.user["id"]:
        flash("Нельзя отключить собственную учётную запись.", "error")
        return redirect(url_for("auth.users"))

    db.execute("BEGIN IMMEDIATE")
    try:
        target = db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not target:
            db.execute("ROLLBACK")
            flash("Пользователь не найден.", "error")
            return redirect(url_for("auth.users"))

        # Отключаем только активного админа → проверяем, что он не последний.
        if target["is_active"] and target["role"] == "admin":
            active_admins = db.execute(
                "SELECT COUNT(*) AS c FROM users "
                "WHERE role='admin' AND is_active=1"
            ).fetchone()["c"]
            if active_admins <= 1:
                db.execute("ROLLBACK")
                flash("Нельзя отключить последнего активного администратора.",
                      "error")
                return redirect(url_for("auth.users"))

        db.execute(
            "UPDATE users SET is_active = 1 - is_active, "
            "session_version = session_version + 1 WHERE id = ?",
            (user_id,),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Изменён статус пользователя #{user_id}",
               entity_type="user", entity_id=user_id)
    return redirect(url_for("auth.users"))


@auth.route("/change-password", methods=("GET", "POST"))
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("new_password_confirm") or ""
        db = get_db()

        error = None
        row = db.execute(
            "SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)
        ).fetchone()

        if not row or not check_password_hash(row["password_hash"], old):
            error = "Старый пароль неверен."
        elif new != confirm:
            error = "Новые пароли не совпадают."
        else:
            pwd_err = _password_ok(new, username=g.user["username"],
                                   full_name=g.user["full_name"])
            if pwd_err:
                error = pwd_err
            elif check_password_hash(row["password_hash"], new):
                error = "Новый пароль должен отличаться от старого."

        if error:
            flash(error, "error")
            return render_template("auth/change_password.html"), 400

        db.execute(
            "UPDATE users SET password_hash = ?, "
            "session_version = session_version + 1 WHERE id = ?",
            (generate_password_hash(new, method="pbkdf2:sha256:600000"),
             g.user["id"]),
        )
        log_action("Смена собственного пароля",
                   entity_type="user", entity_id=g.user["id"])
        session.clear()
        flash("Пароль изменён. Войдите заново.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/change_password.html")


# ==============================================================
# ПОДСИСТЕМА: УПРАВЛЕНИЕ ЗАКАЗАМИ
# ==============================================================
orders = Blueprint("orders", __name__, url_prefix="/orders")


@orders.route("/")
@roles_required("waiter")
def tables():
    db = get_db()
    rows = db.execute(
        """
        SELECT t.*, o.id AS order_id
        FROM restaurant_tables t
        LEFT JOIN orders o ON o.table_id = t.id AND o.status IN ('open', 'sent', 'served')
        ORDER BY t.number
        """
    ).fetchall()
    return render_template("orders/tables.html", tables=rows)


@orders.route("/table/<int:table_id>/open", methods=("POST",))
@roles_required("waiter")
def open_order(table_id):
    db = get_db()
    table = db.execute(
        "SELECT * FROM restaurant_tables WHERE id = ?", (table_id,)
    ).fetchone()
    if not table:
        flash("Стол не найден.", "error")
        return redirect(url_for("orders.tables"))

    if table["status"] == "reserved":
        flash("Стол забронирован. Сначала снимите бронь.", "error")
        return redirect(url_for("orders.tables"))

    guests = safe_int(request.form.get("guests"), min_=1, max_=50, default=1)

    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute(
            "SELECT id FROM orders WHERE table_id = ? "
            "AND status IN ('open', 'sent', 'served')",
            (table_id,),
        ).fetchone()
        if existing:
            db.execute("ROLLBACK")
            return redirect(url_for("orders.detail", order_id=existing["id"]))

        cur = db.execute(
            "INSERT INTO orders (table_id, waiter_id, guests) VALUES (?, ?, ?)",
            (table_id, g.user["id"], guests),
        )
        db.execute(
            "UPDATE restaurant_tables SET status = 'occupied' WHERE id = ?", (table_id,)
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Открыт заказ #{cur.lastrowid} на столе #{table_id}",
               entity_type="order", entity_id=cur.lastrowid)
    return redirect(url_for("orders.detail", order_id=cur.lastrowid))


@orders.route("/<int:order_id>")
@roles_required("waiter")
def detail(order_id):
    db = get_db()
    order = db.execute(
        """
        SELECT o.*, t.number AS table_number, u.full_name AS waiter_name
        FROM orders o
        LEFT JOIN restaurant_tables t ON t.id = o.table_id
        LEFT JOIN users u ON u.id = o.waiter_id
        WHERE o.id = ?
        """,
        (order_id,),
    ).fetchone()
    if order is None:
        flash("Заказ не найден.", "error")
        return redirect(url_for("orders.tables"))

    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Этот заказ принадлежит другому официанту.", "error")
        return redirect(url_for("orders.tables"))

    items = db.execute(
        """
        SELECT oi.*, d.name AS dish_name, d.station
        FROM order_items oi
        JOIN dishes d ON d.id = oi.dish_id
        WHERE oi.order_id = ?
        ORDER BY oi.id
        """,
        (order_id,),
    ).fetchall()
    dishes = db.execute(
        "SELECT d.*, c.name AS category_name FROM dishes d "
        "LEFT JOIN categories c ON c.id = d.category_id "
        "WHERE d.is_active = 1 ORDER BY c.name, d.name"
    ).fetchall()
    # money(): деньги считаются от округлённых копеек → нет накопления FP-ошибки
    total = money(sum(i["price"] * i["qty"] for i in items if i["status"] != "cancelled"))

    return render_template(
        "orders/order_detail.html",
        order=order, items=items, dishes=dishes, total=total,
    )


@orders.route("/<int:order_id>/add_item", methods=("POST",))
@roles_required("waiter")
def add_item(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order or order["status"] != "open":
        flash("Заказ не найден или уже отправлен/закрыт.", "error")
        return redirect(url_for("orders.tables"))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя менять чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    dish_id = request.form.get("dish_id", type=int)
    qty = safe_int(request.form.get("qty"), min_=1, max_=99, default=1)
    comment = (request.form.get("comment") or "").strip()[:200]

    dish = db.execute(
        "SELECT * FROM dishes WHERE id = ? AND is_active = 1", (dish_id,)
    ).fetchone()
    if not dish:
        flash("Блюдо не найдено.", "error")
        return redirect(url_for("orders.detail", order_id=order_id))

    price = money(dish["price"])
    db.execute(
        "INSERT INTO order_items (order_id, dish_id, qty, price, comment) "
        "VALUES (?, ?, ?, ?, ?)",
        (order_id, dish_id, qty, price, comment or None),
    )
    log_action(f"В заказ #{order_id} добавлено блюдо «{dish['name']}» x{qty}",
               entity_type="order", entity_id=order_id)
    return redirect(url_for("orders.detail", order_id=order_id))


@orders.route("/item/<int:item_id>/remove", methods=("POST",))
@roles_required("waiter")
def remove_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM order_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        flash("Позиция не найдена.", "error")
        return redirect(url_for("orders.tables"))

    order = db.execute(
        "SELECT * FROM orders WHERE id = ?", (item["order_id"],)
    ).fetchone()
    if not order or order["status"] != "open" or item["status"] != "new":
        flash("Удалить можно только новую позицию из открытого заказа.", "error")
        return redirect(url_for("orders.detail", order_id=item["order_id"]))

    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя менять чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    db.execute("UPDATE order_items SET status = 'cancelled' WHERE id = ?", (item_id,))
    log_action(f"Отменена позиция #{item_id} в заказе #{item['order_id']}",
               entity_type="order_item", entity_id=item_id)
    return redirect(url_for("orders.detail", order_id=item["order_id"]))


@orders.route("/<int:order_id>/send", methods=("POST",))
@roles_required("waiter")
def send_to_kitchen(order_id):
    db = get_db()

    db.execute("BEGIN IMMEDIATE")
    try:
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order or order["status"] != "open":
            db.execute("ROLLBACK")
            flash("Заказ не найден или уже отправлен.", "error")
            return redirect(url_for("orders.tables"))

        if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
            db.execute("ROLLBACK")
            flash("Нельзя менять чужой заказ.", "error")
            return redirect(url_for("orders.tables"))

        items = db.execute(
            "SELECT * FROM order_items WHERE order_id = ? AND status = 'new'",
            (order_id,),
        ).fetchall()
        if not items:
            db.execute("ROLLBACK")
            flash("Нет новых позиций для отправки.", "warning")
            return redirect(url_for("orders.detail", order_id=order_id))

        dish_ids = [i["dish_id"] for i in items]
        qmarks = ",".join("?" * len(dish_ids))
        tc_rows = db.execute(
            f"SELECT dish_id, ingredient_id, qty_per_portion "
            f"FROM tech_cards WHERE dish_id IN ({qmarks})",
            dish_ids,
        ).fetchall()
        tc_by_dish = defaultdict(list)
        for r in tc_rows:
            tc_by_dish[r["dish_id"]].append(r)

        needs = defaultdict(float)
        for item in items:
            for ing in tc_by_dish.get(item["dish_id"], []):
                needs[ing["ingredient_id"]] += ing["qty_per_portion"] * item["qty"]

        if not needs:
            db.execute("ROLLBACK")
            flash("У блюд не заполнены техкарты.", "error")
            return redirect(url_for("orders.detail", order_id=order_id))

        ing_ids = list(needs.keys())
        qmarks = ",".join("?" * len(ing_ids))
        stocks = {
            row["id"]: row
            for row in db.execute(
                f"SELECT id, name, unit, stock_qty FROM ingredients "
                f"WHERE id IN ({qmarks})",
                ing_ids,
            ).fetchall()
        }

        shortages = []
        for ing_id, need in needs.items():
            row = stocks.get(ing_id)
            if not row or row["stock_qty"] + 1e-9 < need:
                shortages.append(
                    (row["name"] if row else f"#{ing_id}", need,
                     row["stock_qty"] if row else 0,
                     row["unit"] if row else "?")
                )
        if shortages:
            db.execute("ROLLBACK")
            for name, need, have, unit in shortages:
                flash(
                    f"Недостаточно «{name}»: нужно {need:.3f} {unit}, "
                    f"есть {have:.3f} {unit}.",
                    "error",
                )
            return redirect(url_for("orders.detail", order_id=order_id))

        for item in items:
            db.execute("UPDATE order_items SET status = 'cooking' WHERE id = ?",
                       (item["id"],))
            for ing in tc_by_dish.get(item["dish_id"], []):
                write_off_qty = ing["qty_per_portion"] * item["qty"]
                db.execute(
                    "UPDATE ingredients SET stock_qty = stock_qty - ? WHERE id = ?",
                    (write_off_qty, ing["ingredient_id"]),
                )
                db.execute(
                    "INSERT INTO stock_movements "
                    "(ingredient_id, qty_change, reason, comment, user_id) "
                    "VALUES (?, ?, 'order', ?, ?)",
                    (ing["ingredient_id"], -write_off_qty,
                     f"Заказ #{order_id}", g.user["id"]),
                )

        db.execute("UPDATE orders SET status = 'sent' WHERE id = ?", (order_id,))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Заказ #{order_id} отправлен на кухню/бар",
               entity_type="order", entity_id=order_id)
    return redirect(url_for("orders.detail", order_id=order_id))


@orders.route("/item/<int:item_id>/status", methods=("POST",))
@roles_required("cook", "bartender", "waiter")
def update_item_status(item_id):
    db = get_db()
    new_status = request.form.get("status")
    item = db.execute(
        """
        SELECT oi.*, d.station, o.status AS order_status, o.waiter_id
        FROM order_items oi
        JOIN dishes d ON d.id = oi.dish_id
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.id = ?
        """,
        (item_id,),
    ).fetchone()
    if not item:
        flash("Позиция не найдена.", "error")
        return redirect(url_for("orders.tables"))

    role = g.user["role"]
    ok = False

    if role in ("cook", "bartender"):
        expected_station = "bar" if role == "bartender" else "kitchen"
        if (item["station"] == expected_station
                and item["status"] == "cooking"
                and new_status == "ready"):
            ok = True
    elif role == "waiter":
        if (item["waiter_id"] == g.user["id"]
                and item["status"] == "ready"
                and new_status == "served"):
            ok = True
    elif role == "admin":
        allowed = {
            "cooking": {"ready", "cancelled"},
            "ready":   {"served", "cancelled"},
            "new":     {"cancelled"},
        }
        if new_status in allowed.get(item["status"], set()):
            ok = True

    if not ok:
        flash("Недопустимый переход статуса.", "error")
        return redirect(url_for("orders.tables"))

    db.execute("UPDATE order_items SET status = ? WHERE id = ?", (new_status, item_id))
    log_action(f"Позиция #{item_id} → {new_status}",
               entity_type="order_item", entity_id=item_id)
    return redirect(url_for("orders.detail", order_id=item["order_id"]))


@orders.route("/<int:order_id>/pay", methods=("POST",))
@roles_required("waiter")
def pay(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        flash("Заказ не найден.", "error")
        return redirect(url_for("orders.tables"))
    if order["status"] not in ("sent", "served"):
        flash("Оплатить можно только заказ в статусе «На кухне» или «Подан».", "error")
        return redirect(url_for("orders.detail", order_id=order_id))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя оплатить чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE orders SET status = 'paid', closed_at = datetime('now') WHERE id = ?",
            (order_id,),
        )
        if order["table_id"]:
            db.execute(
                "UPDATE restaurant_tables SET status = 'free' WHERE id = ?",
                (order["table_id"],),
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Заказ #{order_id} оплачен и закрыт",
               entity_type="order", entity_id=order_id)
    flash("Заказ оплачен и закрыт.", "success")
    return redirect(url_for("orders.tables"))


@orders.route("/<int:order_id>/cancel", methods=("POST",))
@roles_required("waiter")
def cancel(order_id):
    """Отмена заказа. Освобождает стол, гасит незавершённые позиции."""
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        flash("Заказ не найден.", "error")
        return redirect(url_for("orders.tables"))
    if order["status"] in ("paid", "cancelled"):
        flash("Заказ уже закрыт.", "error")
        return redirect(url_for("orders.detail", order_id=order_id))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя отменить чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE orders SET status = 'cancelled', "
            "closed_at = datetime('now') WHERE id = ?",
            (order_id,),
        )
        db.execute(
            "UPDATE order_items SET status = 'cancelled' "
            "WHERE order_id = ? AND status NOT IN ('served', 'cancelled')",
            (order_id,),
        )
        if order["table_id"]:
            db.execute(
                "UPDATE restaurant_tables SET status = 'free' WHERE id = ?",
                (order["table_id"],),
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Заказ #{order_id} отменён",
               entity_type="order", entity_id=order_id)
    flash("Заказ отменён.", "success")
    return redirect(url_for("orders.tables"))


@orders.route("/kitchen")
@roles_required("cook", "bartender")
def kitchen_view():
    db = get_db()
    station = "bar" if g.user["role"] == "bartender" else "kitchen"
    items = db.execute(
        """
        SELECT oi.*, d.name AS dish_name, o.id AS order_id, t.number AS table_number
        FROM order_items oi
        JOIN dishes d ON d.id = oi.dish_id
        JOIN orders o ON o.id = oi.order_id
        LEFT JOIN restaurant_tables t ON t.id = o.table_id
        WHERE d.station = ? AND oi.status IN ('cooking', 'ready')
        ORDER BY oi.id
        """,
        (station,),
    ).fetchall()
    return render_template("orders/kitchen.html", items=items, station=station)


# ==============================================================
# ПОДСИСТЕМА: СКЛАД
# ==============================================================
warehouse = Blueprint("warehouse", __name__, url_prefix="/warehouse")


@warehouse.route("/")
@roles_required("storekeeper", "accountant")
def stock():
    db = get_db()
    ingredients = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
    return render_template("warehouse/stock.html", ingredients=ingredients)


@warehouse.route("/new", methods=("GET", "POST"))
@roles_required("storekeeper")
def new_ingredient():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        unit = (request.form.get("unit") or "шт").strip()[:20] or "шт"
        stock_qty = safe_float(request.form.get("stock_qty"), min_=0, max_=1_000_000)
        min_qty = safe_float(request.form.get("min_qty"), min_=0, max_=1_000_000)
        db = get_db()

        if not name:
            flash("Укажите наименование товара.", "error")
        elif len(name) > 200:
            flash("Слишком длинное наименование.", "error")
        elif stock_qty is None or min_qty is None:
            flash("Некорректное количество (0 – 1 000 000).", "error")
        else:
            db.execute(
                "INSERT INTO ingredients (name, unit, stock_qty, min_qty) "
                "VALUES (?, ?, ?, ?)",
                (name, unit, stock_qty, min_qty),
            )
            log_action(f"Добавлен товар на склад: {name}", entity_type="ingredient")
            flash("Товар добавлен.", "success")
            return redirect(url_for("warehouse.stock"))
    return render_template("warehouse/ingredient_form.html")


@warehouse.route("/<int:ingredient_id>/movement", methods=("POST",))
@roles_required("storekeeper")
def movement(ingredient_id):
    db = get_db()
    reason = request.form.get("reason")
    raw_qty = request.form.get("qty", "").strip()
    comment = (request.form.get("comment") or "").strip()[:200]

    if reason not in ("receipt", "writeoff", "inventory"):
        flash("Некорректный тип операции.", "error")
        return redirect(url_for("warehouse.stock"))

    # Для инвентаризации комментарий обязателен (обоснование расхождения)
    if reason == "inventory" and not comment:
        flash("Для инвентаризации обязателен комментарий с обоснованием.", "error")
        return redirect(url_for("warehouse.stock"))

    qty = safe_float(request.form.get("qty"), min_=0, max_=1_000_000)
    if qty is None:
        flash("Введите корректное количество (0 – 1 000 000).", "error")
        return redirect(url_for("warehouse.stock"))

    if reason in ("receipt", "writeoff") and qty <= 0:
        flash("Количество должно быть больше нуля.", "error")
        return redirect(url_for("warehouse.stock"))

    db.execute("BEGIN IMMEDIATE")
    try:
        ing = db.execute(
            "SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)
        ).fetchone()
        if not ing:
            db.execute("ROLLBACK")
            flash("Товар не найден.", "error")
            return redirect(url_for("warehouse.stock"))

        if reason == "receipt":
            change = qty
        elif reason == "writeoff":
            if qty > ing["stock_qty"]:
                db.execute("ROLLBACK")
                flash("Нельзя списать больше, чем есть на складе.", "error")
                return redirect(url_for("warehouse.stock"))
            change = -qty
        else:  # inventory
            change = qty - ing["stock_qty"]

        new_stock = ing["stock_qty"] + change
        if new_stock < 0:
            db.execute("ROLLBACK")
            flash("Остаток не может быть отрицательным.", "error")
            return redirect(url_for("warehouse.stock"))

        db.execute("UPDATE ingredients SET stock_qty = ? WHERE id = ?",
                   (new_stock, ingredient_id))
        db.execute(
            "INSERT INTO stock_movements "
            "(ingredient_id, qty_change, reason, comment, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ingredient_id, change, reason, comment or None, g.user["id"]),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    if reason == "inventory":
        log_action(
            f"Инвентаризация #{ingredient_id}: было {ing['stock_qty']:.3f}, "
            f"стало {qty:.3f} ({comment})",
            entity_type="ingredient", entity_id=ingredient_id,
        )
    else:
        log_action(f"Складская операция «{reason}» по товару #{ingredient_id}: {change:+.2f}",
                   entity_type="ingredient", entity_id=ingredient_id)
    return redirect(url_for("warehouse.stock"))


@warehouse.route("/movements")
@roles_required("storekeeper", "accountant")
def movements():
    db = get_db()
    rows = db.execute(
        """
        SELECT sm.*, i.name AS ingredient_name, i.unit, u.full_name AS user_name
        FROM stock_movements sm
        JOIN ingredients i ON i.id = sm.ingredient_id
        LEFT JOIN users u ON u.id = sm.user_id
        ORDER BY sm.created_at DESC, sm.id DESC
        LIMIT 200
        """
    ).fetchall()
    return render_template("warehouse/movements.html", movements=rows)


@warehouse.route("/requests")
@roles_required("storekeeper", "accountant")
def requests_list():
    db = get_db()
    rows = db.execute(
        """
        SELECT r.*, i.name AS ingredient_name, i.unit
        FROM restock_requests r
        JOIN ingredients i ON i.id = r.ingredient_id
        ORDER BY r.status = 'done', r.created_at DESC
        """
    ).fetchall()
    low_stock = db.execute(
        "SELECT * FROM ingredients WHERE stock_qty <= min_qty ORDER BY name"
    ).fetchall()
    return render_template(
        "warehouse/requests.html", requests=rows, low_stock=low_stock
    )


@warehouse.route("/requests/new", methods=("POST",))
@roles_required("storekeeper")
def new_request():
    db = get_db()
    ingredient_id = request.form.get("ingredient_id", type=int)
    qty = safe_float(request.form.get("qty"), min_=0.01, max_=1_000_000)

    if not ingredient_id or qty is None:
        flash("Укажите корректное количество.", "error")
        return redirect(url_for("warehouse.requests_list"))

    ing = db.execute("SELECT id FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
    if not ing:
        flash("Товар не найден.", "error")
        return redirect(url_for("warehouse.requests_list"))

    db.execute(
        "INSERT INTO restock_requests (ingredient_id, qty, created_by) "
        "VALUES (?, ?, ?)",
        (ingredient_id, qty, g.user["id"]),
    )
    log_action(f"Создана заявка на пополнение товара #{ingredient_id}",
               entity_type="restock_request")
    flash("Заявка на пополнение создана.", "success")
    return redirect(url_for("warehouse.requests_list"))


@warehouse.route("/requests/<int:request_id>/status", methods=("POST",))
@roles_required("storekeeper", "accountant")
def update_request_status(request_id):
    db = get_db()
    new_status = request.form.get("status")
    if new_status not in ("approved", "done", "rejected"):
        flash("Некорректный статус.", "error")
        return redirect(url_for("warehouse.requests_list"))

    db.execute("BEGIN IMMEDIATE")
    try:
        req = db.execute(
            "SELECT * FROM restock_requests WHERE id = ?", (request_id,)
        ).fetchone()
        if not req:
            db.execute("ROLLBACK")
            flash("Заявка не найдена.", "error")
            return redirect(url_for("warehouse.requests_list"))
        if req["status"] in ("done", "rejected"):
            db.execute("ROLLBACK")
            flash("Заявка уже закрыта.", "error")
            return redirect(url_for("warehouse.requests_list"))

        db.execute("UPDATE restock_requests SET status = ? WHERE id = ?",
                   (new_status, request_id))

        if new_status == "done":
            db.execute(
                "UPDATE ingredients SET stock_qty = stock_qty + ? WHERE id = ?",
                (req["qty"], req["ingredient_id"]),
            )
            db.execute(
                "INSERT INTO stock_movements "
                "(ingredient_id, qty_change, reason, comment, user_id) "
                "VALUES (?, ?, 'receipt', ?, ?)",
                (req["ingredient_id"], req["qty"],
                 f"Заявка #{request_id}", g.user["id"]),
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Заявка #{request_id} → {new_status}",
               entity_type="restock_request", entity_id=request_id)
    return redirect(url_for("warehouse.requests_list"))


# ==============================================================
# ПОДСИСТЕМА: БЛЮДА И ТЕХКАРТЫ
# ==============================================================
dishes = Blueprint("dishes", __name__, url_prefix="/dishes")


@dishes.route("/")
@roles_required("cook", "bartender", "accountant", "waiter")
def list_dishes():
    db = get_db()
    rows = db.execute(
        """
        SELECT d.*, c.name AS category_name
        FROM dishes d
        LEFT JOIN categories c ON c.id = d.category_id
        ORDER BY c.name, d.name
        """
    ).fetchall()
    return render_template("dishes/list.html", dishes=rows)


@dishes.route("/new", methods=("GET", "POST"))
@roles_required("cook")
def new_dish():
    db = get_db()
    categories = db.execute("SELECT * FROM categories ORDER BY name").fetchall()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        category_id = request.form.get("category_id", type=int)
        price_raw = safe_float(request.form.get("price"), min_=0.01, max_=1_000_000)
        station = request.form.get("station", "kitchen")
        description = (request.form.get("description") or "").strip()[:1000]

        if not name:
            flash("Укажите название.", "error")
        elif len(name) > 200:
            flash("Слишком длинное название.", "error")
        elif price_raw is None:
            flash("Цена должна быть в диапазоне 0.01–1 000 000.", "error")
        elif station not in ("kitchen", "bar"):
            flash("Некорректная станция.", "error")
        elif category_id and not db.execute(
                "SELECT id FROM categories WHERE id = ?", (category_id,)
        ).fetchone():
            flash("Категория не найдена.", "error")
        else:
            price = money(price_raw)
            cur = db.execute(
                "INSERT INTO dishes (name, category_id, price, station, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, category_id, price, station, description or None),
            )
            log_action(f"Добавлено блюдо «{name}»", entity_type="dish",
                       entity_id=cur.lastrowid)
            flash("Блюдо добавлено. Теперь укажите технологическую карту.", "success")
            return redirect(url_for("dishes.tech_card", dish_id=cur.lastrowid))

    return render_template("dishes/dish_form.html", categories=categories)


@dishes.route("/<int:dish_id>/toggle", methods=("POST",))
@roles_required("cook")
def toggle_dish(dish_id):
    db = get_db()
    dish = db.execute("SELECT id FROM dishes WHERE id = ?", (dish_id,)).fetchone()
    if not dish:
        flash("Блюдо не найдено.", "error")
        return redirect(url_for("dishes.list_dishes"))

    db.execute("UPDATE dishes SET is_active = 1 - is_active WHERE id = ?", (dish_id,))
    log_action(f"Изменена доступность блюда #{dish_id}", entity_type="dish",
               entity_id=dish_id)
    return redirect(url_for("dishes.list_dishes"))


@dishes.route("/<int:dish_id>/techcard", methods=("GET", "POST"))
@roles_required("cook")
def tech_card(dish_id):
    db = get_db()
    dish = db.execute("SELECT * FROM dishes WHERE id = ?", (dish_id,)).fetchone()
    if not dish:
        flash("Блюдо не найдено.", "error")
        return redirect(url_for("dishes.list_dishes"))

    if request.method == "POST":
        ingredient_id = request.form.get("ingredient_id", type=int)
        qty = safe_float(request.form.get("qty_per_portion"),
                         min_=0.001, max_=1000)

        if not ingredient_id or qty is None:
            flash("Некорректное количество.", "error")
            return redirect(url_for("dishes.tech_card", dish_id=dish_id))

        ing = db.execute("SELECT id FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
        if not ing:
            flash("Ингредиент не найден.", "error")
            return redirect(url_for("dishes.tech_card", dish_id=dish_id))

        db.execute(
            "INSERT INTO tech_cards (dish_id, ingredient_id, qty_per_portion) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(dish_id, ingredient_id) DO UPDATE SET "
            "qty_per_portion = excluded.qty_per_portion",
            (dish_id, ingredient_id, qty),
        )
        log_action(f"Обновлена техкарта блюда #{dish_id}", entity_type="dish",
                   entity_id=dish_id)
        return redirect(url_for("dishes.tech_card", dish_id=dish_id))

    card = db.execute(
        """
        SELECT tc.*, i.name AS ingredient_name, i.unit
        FROM tech_cards tc JOIN ingredients i ON i.id = tc.ingredient_id
        WHERE tc.dish_id = ? ORDER BY i.name
        """,
        (dish_id,),
    ).fetchall()
    ingredients = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
    return render_template(
        "dishes/techcard.html", dish=dish, card=card, ingredients=ingredients
    )


@dishes.route("/techcard/<int:item_id>/remove", methods=("POST",))
@roles_required("cook")
def remove_tech_card_item(item_id):
    db = get_db()
    row = db.execute("SELECT dish_id FROM tech_cards WHERE id = ?", (item_id,)).fetchone()
    if row:
        db.execute("DELETE FROM tech_cards WHERE id = ?", (item_id,))
        log_action(f"Удалён ингредиент #{item_id} из техкарты блюда #{row['dish_id']}",
                   entity_type="dish", entity_id=row["dish_id"])
        return redirect(url_for("dishes.tech_card", dish_id=row["dish_id"]))
    return redirect(url_for("dishes.list_dishes"))


@dishes.route("/categories", methods=("GET", "POST"))
@roles_required("cook")
def categories():
    db = get_db()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Укажите название категории.", "error")
        elif len(name) > 100:
            flash("Слишком длинное название.", "error")
        else:
            db.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
            log_action(f"Добавлена категория меню «{name}»", entity_type="category")
        return redirect(url_for("dishes.categories"))
    rows = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("dishes/categories.html", categories=rows)


# ==============================================================
# ПОДСИСТЕМА: ПЕРСОНАЛ
# ==============================================================
staff = Blueprint("staff", __name__, url_prefix="/staff")


@staff.route("/")
@roles_required("admin", "accountant")
def list_employees():
    db = get_db()
    rows = db.execute("SELECT * FROM employees ORDER BY full_name").fetchall()
    total_fund = money(sum(e["salary"] for e in rows if e["is_active"]))
    return render_template("staff/list.html", employees=rows, total_fund=total_fund)


@staff.route("/new", methods=("GET", "POST"))
@roles_required("admin")
def new_employee():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        position = (request.form.get("position") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        hired_at = request.form.get("hired_at", "")
        salary_raw = safe_float(request.form.get("salary"), min_=0, max_=10_000_000)
        db = get_db()

        if not full_name or not position:
            flash("Укажите ФИО и должность.", "error")
        elif len(full_name) > 200 or len(position) > 100:
            flash("Слишком длинное значение.", "error")
        elif salary_raw is None:
            flash("Некорректный оклад.", "error")
        elif phone and not PHONE_RE.match(phone):
            flash("Некорректный телефон.", "error")
        elif hired_at and not DATE_RE.match(hired_at):
            flash("Некорректная дата приёма.", "error")
        else:
            db.execute(
                "INSERT INTO employees (full_name, position, phone, hired_at, salary) "
                "VALUES (?, ?, ?, ?, ?)",
                (full_name, position, phone or None, hired_at or None, salary),
            )
            log_action(f"Принят сотрудник «{full_name}» ({position})",
                       entity_type="employee")
            flash("Сотрудник добавлен.", "success")
            return redirect(url_for("staff.list_employees"))
    return render_template("staff/employee_form.html")


@staff.route("/<int:employee_id>/toggle", methods=("POST",))
@roles_required("admin")
def toggle_employee(employee_id):
    db = get_db()
    emp = db.execute("SELECT id FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        flash("Сотрудник не найден.", "error")
        return redirect(url_for("staff.list_employees"))

    db.execute("UPDATE employees SET is_active = 1 - is_active WHERE id = ?",
               (employee_id,))
    log_action(f"Изменён статус занятости сотрудника #{employee_id}",
               entity_type="employee", entity_id=employee_id)
    return redirect(url_for("staff.list_employees"))


@staff.route("/schedule")
@roles_required("admin", "accountant")
def schedule():
    db = get_db()
    rows = db.execute(
        """
        SELECT s.*, e.full_name, e.position
        FROM schedule s JOIN employees e ON e.id = s.employee_id
        ORDER BY s.work_date, s.shift_start
        """
    ).fetchall()
    employees = db.execute(
        "SELECT * FROM employees WHERE is_active = 1 ORDER BY full_name"
    ).fetchall()
    return render_template("staff/schedule.html", schedule=rows, employees=employees)


@staff.route("/schedule/new", methods=("POST",))
@roles_required("admin")
def new_shift():
    db = get_db()
    employee_id = request.form.get("employee_id", type=int)
    work_date = request.form.get("work_date")
    shift_start = request.form.get("shift_start")
    shift_end = request.form.get("shift_end")

    if not employee_id or not work_date or not shift_start or not shift_end:
        flash("Заполните все поля.", "error")
        return redirect(url_for("staff.schedule"))
    if not DATE_RE.match(work_date):
        flash("Некорректная дата.", "error")
        return redirect(url_for("staff.schedule"))
    if shift_start >= shift_end:
        flash("Окончание должно быть позже начала.", "error")
        return redirect(url_for("staff.schedule"))

    emp = db.execute("SELECT id FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        flash("Сотрудник не найден.", "error")
        return redirect(url_for("staff.schedule"))

    overlap = db.execute(
        """SELECT id FROM schedule
           WHERE employee_id = ? AND work_date = ?
             AND NOT (shift_end <= ? OR shift_start >= ?)""",
        (employee_id, work_date, shift_start, shift_end),
    ).fetchone()
    if overlap:
        flash("У сотрудника уже есть пересекающаяся смена в этот день.", "error")
        return redirect(url_for("staff.schedule"))

    db.execute(
        "INSERT INTO schedule (employee_id, work_date, shift_start, shift_end) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, work_date, shift_start, shift_end),
    )
    log_action(f"Добавлена смена для сотрудника #{employee_id} на {work_date}",
               entity_type="employee", entity_id=employee_id)
    return redirect(url_for("staff.schedule"))


@staff.route("/schedule/<int:shift_id>/remove", methods=("POST",))
@roles_required("admin")
def remove_shift(shift_id):
    db = get_db()
    db.execute("DELETE FROM schedule WHERE id = ?", (shift_id,))
    log_action(f"Удалена смена #{shift_id}", entity_type="schedule",
               entity_id=shift_id)
    return redirect(url_for("staff.schedule"))


# ==============================================================
# ПОДСИСТЕМА: ОТЧЁТНОСТЬ
# ==============================================================
reports = Blueprint("reports", __name__, url_prefix="/reports")


@reports.route("/")
@roles_required("accountant", "admin")
def index():
    db = get_db()

    date_from = request.args.get("date_from") or str(date.today() - timedelta(days=7))
    date_to = request.args.get("date_to") or str(date.today())

    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
        if d_from > d_to:
            d_from, d_to = d_to, d_from
            date_from, date_to = str(d_from), str(d_to)
    except ValueError:
        date_from = str(date.today() - timedelta(days=7))
        date_to = str(date.today())

    revenue_raw = db.execute(
        """
        SELECT COALESCE(SUM(oi.price * oi.qty), 0) AS revenue,
               COUNT(DISTINCT o.id) AS orders_count
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id AND oi.status != 'cancelled'
        WHERE o.status = 'paid' AND date(o.closed_at) BETWEEN date(?) AND date(?)
        """,
        (date_from, date_to),
    ).fetchone()
    revenue_row = {
        "revenue": money(revenue_raw["revenue"]),
        "orders_count": revenue_raw["orders_count"],
    }

    top_dishes = db.execute(
        """
        SELECT d.name, SUM(oi.qty) AS qty_sold, SUM(oi.qty * oi.price) AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN dishes d ON d.id = oi.dish_id
        WHERE o.status = 'paid' AND oi.status != 'cancelled'
          AND date(o.closed_at) BETWEEN date(?) AND date(?)
        GROUP BY d.id ORDER BY revenue DESC LIMIT 10
        """,
        (date_from, date_to),
    ).fetchall()

    daily_revenue = db.execute(
        """
        SELECT date(o.closed_at) AS day, SUM(oi.qty * oi.price) AS revenue
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id AND oi.status != 'cancelled'
        WHERE o.status = 'paid' AND date(o.closed_at) BETWEEN date(?) AND date(?)
        GROUP BY day ORDER BY day
        """,
        (date_from, date_to),
    ).fetchall()

    low_stock = db.execute(
        "SELECT * FROM ingredients WHERE stock_qty <= min_qty ORDER BY name"
    ).fetchall()

    payroll = db.execute(
        "SELECT COALESCE(SUM(salary), 0) AS total FROM employees WHERE is_active = 1"
    ).fetchone()
    payroll = {"total": money(payroll["total"])}

    daily_revenue_data = [
        {"day": row["day"], "revenue": money(row["revenue"])}
        for row in daily_revenue
    ]

    return render_template(
        "reports/index.html",
        revenue_row=revenue_row,
        top_dishes=top_dishes,
        daily_revenue=daily_revenue_data,
        low_stock=low_stock,
        payroll=payroll,
        date_from=date_from,
        date_to=date_to,
    )


# ==============================================================
# RATE LIMITER
# ==============================================================
class LoginRateLimiter:
    """In-memory rate limiter с TTL и периодической чисткой.
    Держит два счётчика: (ip, username) и (ip).
    Для мультипроцесса — заменить на Redis (интерфейс сохранён)."""

    def __init__(self, max_attempts=5, window=300, block=900,
                 ip_max_attempts=20, cleanup_interval=300):
        self._attempts = {}     # key -> list[float]
        self._blocked = {}      # key -> unblock_ts
        self._lock = threading.Lock()
        self.max_attempts = max_attempts
        self.ip_max_attempts = ip_max_attempts
        self.window = window
        self.block = block
        self._last_cleanup = time.time()
        self.cleanup_interval = cleanup_interval

    def _key(self, ip, username):
        return f"u|{ip}|{(username or '').lower()}"

    def _ip_key(self, ip):
        return f"i|{ip}"

    def _maybe_cleanup(self, now):
        if now - self._last_cleanup < self.cleanup_interval:
            return
        self._last_cleanup = now
        cutoff_att = now - self.window
        for k in list(self._attempts):
            self._attempts[k] = [t for t in self._attempts[k] if t >= cutoff_att]
            if not self._attempts[k]:
                self._attempts.pop(k, None)
        for k in list(self._blocked):
            if self._blocked[k] <= now:
                self._blocked.pop(k, None)

    def is_blocked(self, ip, username):
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            for k in (self._key(ip, username), self._ip_key(ip)):
                until = self._blocked.get(k, 0)
                if until > now:
                    return True
                if until and until <= now:
                    self._blocked.pop(k, None)
                    self._attempts.pop(k, None)
            return False

    def register_failure(self, ip, username):
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            for k, limit in ((self._key(ip, username), self.max_attempts),
                             (self._ip_key(ip),      self.ip_max_attempts)):
                bucket = [t for t in self._attempts.get(k, [])
                          if now - t < self.window]
                bucket.append(now)
                if len(bucket) >= limit:
                    self._blocked[k] = now + self.block
                    self._attempts[k] = []
                else:
                    self._attempts[k] = bucket

    def reset(self, ip, username):
        with self._lock:
            self._attempts.pop(self._key(ip, username), None)
            self._blocked.pop(self._key(ip, username), None)
            # IP-счётчик НЕ сбрасываем при успехе — держит защиту
            # от перебора разных логинов с одного IP.


login_limiter = LoginRateLimiter()


# ==============================================================
# ФАБРИКА ПРИЛОЖЕНИЯ
# ==============================================================
csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    # ---------- SECRET_KEY ----------
    env = (
            os.environ.get("ENVIRONMENT")
            or os.environ.get("FLASK_ENV")
            or ""
    ).lower()
    is_production = env in ("production", "prod")

    secret = app.config.get("SECRET_KEY")

    if secret and secret.startswith("dev-insecure"):
        raise RuntimeError(
            "SECRET_KEY содержит небезопасное значение 'dev-insecure'. "
            "Сгенерируйте ключ: python -c \"import secrets; "
            "print(secrets.token_hex(32))\" и задайте его в SECRET_KEY."
        )

    if not secret:
        if is_production:
            raise RuntimeError(
                "SECRET_KEY не задан в продакшене (ENVIRONMENT=production). "
                "Задайте переменную окружения SECRET_KEY, например:\n"
                "    python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning(
            "SECRET_KEY не задан — сгенерирован временный ключ (dev-режим). "
            "Сессии будут сбрасываться при каждом перезапуске. "
            "Для продакшена задайте SECRET_KEY и ENVIRONMENT=production."
        )

    # В проде предупредим, если cookie не помечены Secure
    # В проде cookie ОБЯЗАНЫ быть Secure. Иначе — отказ старта.
    if is_production:
        if not app.config.get("SESSION_COOKIE_SECURE"):
            raise RuntimeError(
                "SESSION_COOKIE_SECURE=0 в продакшене. "
                "Cookie сессии передаются по HTTP — это утечка токена. "
                "Установите SESSION_COOKIE_SECURE=1 и используйте HTTPS."
            )
        if app.config.get("TRUSTED_PROXIES", 0) == 0:
            app.logger.warning(
                "TRUSTED_PROXIES=0 в продакшене. Если приложение работает "
                "за reverse-proxy (nginx/traefik/CDN), задайте "
                "TRUSTED_PROXIES=<количество прокси>, иначе "
                "rate limiter и audit_log будут видеть IP прокси, "
                "а не клиента."
            )

    if app.config.get("SESSION_COOKIE_SECURE"):
        app.config["PREFERRED_URL_SCHEME"] = "https"

    # ProxyFix: x_host/x_port/x_prefix отключены — доверяем только X-Forwarded-For/Proto
    trusted = app.config.get("TRUSTED_PROXIES", 0)
    if trusted > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=trusted,
            x_proto=trusted,
            x_host=0,
            x_port=0,
            x_prefix=0,
        )

    os.makedirs(app.instance_path, exist_ok=True)

    csrf.init_app(app)

    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_db_command)

    app.register_blueprint(auth)
    app.register_blueprint(orders)
    app.register_blueprint(warehouse)
    app.register_blueprint(dishes)
    app.register_blueprint(staff)
    app.register_blueprint(reports)

    # ---------- Security headers ----------
    @app.after_request
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), "
            "usb=(), serial=(), midi=(), magnetometer=(), "
            "accelerometer=(), gyroscope=()"
        )
        # Изоляция opener'а от других окон — защита от tabnabbing
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # CSP: без 'unsafe-inline', без 'unsafe-eval'
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "object-src 'none'"
        )

        if request.endpoint and not request.endpoint.startswith("static"):
            response.headers.setdefault("Cache-Control", "no-store, private")

        if request.endpoint == "static":
            response.cache_control.public = True
            response.cache_control.max_age = 31536000

        return response


    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        # Возвращаем осмысленный код, а не редирект.
        if g.user is None:
            flash("Сессия истекла. Войдите заново.", "error")
            return render_template("auth/login.html"), 400

        flash("Сессия истекла. Обновите страницу и повторите действие.",
              "error")
        # Отправляем обратно на ту же страницу, если referer локальный.
        back = request.referrer
        if back and _is_safe_url(urlparse(back).path):
            return redirect(back), 400
        return redirect(url_for("index")), 400

    @app.errorhandler(413)
    def payload_too_large(e):
        flash("Слишком большой объём данных в запросе.", "error")
        return render_template("404.html"), 413

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        flash("Метод не разрешён.", "error")
        return redirect(url_for("index")), 405

    @app.errorhandler(500)
    def internal_error(e):
        app.logger.exception("Внутренняя ошибка сервера")
        # Откатываем незавершённую транзакцию, если она была
        db = g.pop("db", None)
        if db is not None:
            try:
                db.execute("ROLLBACK")
            except Exception:
                pass
            try:
                db.close()
            except Exception:
                pass
        return render_template("500.html"), 500

    # ---------- Дашборд ----------
    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))

        db = get_db()

        stats_row = db.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM restaurant_tables) AS tables_total,
              (SELECT COUNT(*) FROM restaurant_tables WHERE status='free') AS tables_free,
              (SELECT COUNT(*) FROM restaurant_tables WHERE status='occupied') AS tables_busy,
              (SELECT COUNT(*) FROM orders WHERE date(created_at) = date('now')) AS orders_today,
              (SELECT COUNT(*) FROM orders WHERE status IN ('open','sent','served')) AS orders_open,
              (SELECT COALESCE(SUM(oi.price * oi.qty), 0)
                 FROM orders o JOIN order_items oi ON oi.order_id = o.id
                 WHERE o.status='paid' AND oi.status != 'cancelled'
                   AND date(o.closed_at) = date('now')) AS revenue_today,
              (SELECT COALESCE(SUM(oi.price * oi.qty), 0)
                 FROM orders o JOIN order_items oi ON oi.order_id = o.id
                 WHERE o.status='paid' AND oi.status != 'cancelled'
                   AND date(o.closed_at) >= date('now', '-6 days')) AS revenue_week,
              (SELECT COUNT(*) FROM ingredients WHERE stock_qty <= min_qty) AS low_stock_count,
              (SELECT COUNT(*) FROM employees WHERE is_active = 1) AS staff_count,
              (SELECT COALESCE(SUM(salary), 0) FROM employees WHERE is_active = 1) AS payroll_fund,
              (SELECT COUNT(*) FROM restock_requests WHERE status IN ('new','approved')) AS requests_pending
            """
        ).fetchone()
        stats = dict(stats_row) if stats_row else {}
        # Денежные значения — приводим к «копеечной» точности
        if stats:
            stats["revenue_today"] = money(stats.get("revenue_today"))
            stats["revenue_week"]  = money(stats.get("revenue_week"))
            stats["payroll_fund"]  = money(stats.get("payroll_fund"))

        recent_orders = db.execute(
            """SELECT o.*, t.number AS table_number,
                      COALESCE(u.full_name, '—') AS waiter_name,
                      (SELECT COALESCE(SUM(oi.qty * oi.price), 0)
                       FROM order_items oi
                       WHERE oi.order_id = o.id AND oi.status != 'cancelled') AS total
               FROM orders o
               LEFT JOIN restaurant_tables t ON t.id = o.table_id
               LEFT JOIN users u ON u.id = o.waiter_id
               ORDER BY o.created_at DESC LIMIT 8"""
        ).fetchall()
        recent_orders = [
            {**dict(r), "total": money(r["total"])} for r in recent_orders
        ]

        low_stock = db.execute(
            """SELECT * FROM ingredients
               WHERE stock_qty <= min_qty
               ORDER BY (stock_qty - min_qty) LIMIT 8"""
        ).fetchall()

        top_dishes = db.execute(
            """SELECT d.name, SUM(oi.qty) AS qty_sold,
                      SUM(oi.qty * oi.price) AS revenue
               FROM order_items oi
               JOIN orders o ON o.id = oi.order_id
               JOIN dishes d ON d.id = oi.dish_id
               WHERE o.status = 'paid' AND oi.status != 'cancelled'
                 AND date(o.closed_at) >= date('now', '-6 days')
               GROUP BY d.id ORDER BY revenue DESC LIMIT 6"""
        ).fetchall()
        top_dishes = [
            {**dict(r), "revenue": money(r["revenue"])} for r in top_dishes
        ]

        station = "bar" if g.user["role"] == "bartender" else "kitchen"
        active_items = db.execute(
            """SELECT oi.*, d.name AS dish_name, o.id AS order_id,
                      t.number AS table_number
               FROM order_items oi
               JOIN dishes d ON d.id = oi.dish_id
               JOIN orders o ON o.id = oi.order_id
               LEFT JOIN restaurant_tables t ON t.id = o.table_id
               WHERE d.station = ? AND oi.status IN ('cooking','ready')
               ORDER BY oi.id LIMIT 8""",
            (station,),
        ).fetchall()

        return render_template(
            "index.html",
            stats=stats,
            recent_orders=recent_orders,
            low_stock=low_stock,
            top_dishes=top_dishes,
            active_items=active_items,
        )

    @app.context_processor
    def inject_globals():
        demo_accounts = None
        if app.config.get("SHOW_DEMO_ACCOUNTS"):
            demo_accounts = [
                {"role": "Администратор", "login": "admin",        "password": "admin123456"},
                {"role": "Официант",      "login": "waiter1",      "password": "waiter12345"},
                {"role": "Повар",         "login": "cook1",        "password": "cook123456"},
                {"role": "Бармен",        "login": "bartender1",   "password": "bar1234567"},
                {"role": "Кладовщик",     "login": "storekeeper1", "password": "store123456"},
                {"role": "Бухгалтер",     "login": "accountant1",  "password": "acc1234567"},
            ]
        return {
            "role_labels": ROLE_LABELS,
            "restaurant_name": app.config["RESTAURANT_NAME"],
            "is_debug": app.debug,
            "demo_accounts": demo_accounts,
        }

    # Прогреваем dummy-хэш и (опционально) соединение с БД
    warmup_dummy_hash()

    with app.app_context():
        ensure_db()

    return app


# ==============================================================
# ТОЧКА ВХОДА
# ==============================================================
app = create_app()


if __name__ == "__main__":
    debug = os.environ.get("DEBUG", "0") == "1"
    app.run(
        host="127.0.0.1",
        port=5067,
        debug=debug,
        use_reloader=debug,
    )