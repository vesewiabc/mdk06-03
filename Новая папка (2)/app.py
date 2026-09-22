"""
АИС ресторана «Гурман» — единый модуль приложения.
Flask + SQLite + Flask-WTF (CSRF).

Запуск:
    python app.py

Переменные окружения:
    SECRET_KEY            — обязательно в проде (иначе дефолт с warning)
    SESSION_COOKIE_SECURE — "1" для HTTPS
    DEBUG                 — "1" для отладки
"""
import functools
import os
import re
import sqlite3
from datetime import date, timedelta
from urllib.parse import urlparse, urljoin

import click
from flask import (
    Blueprint, Flask, flash, g, redirect, render_template, request,
    session, url_for,
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.security import check_password_hash, generate_password_hash


# ==============================================================
# КОНФИГУРАЦИЯ
# ==============================================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ВАЖНО: в проде обязательно задать SECRET_KEY через переменную окружения.
    # Дефолт нужен только чтобы приложение не падало при первом запуске.
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-insecure-CHANGE-ME-in-production"
    DATABASE = os.path.join(BASE_DIR, "restaurant.db")
    RESTAURANT_NAME = "Гурман"

    # Безопасность cookie сессии
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8   # 8 часов
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024       # 4 МБ

    # CSRF
    WTF_CSRF_TIME_LIMIT = None                 # токен живёт всю сессию


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
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ==============================================================
# РАБОТА С БД
# ==============================================================
def get_db():
    """Возвращает соединение с БД, привязанное к текущему запросу."""
    if "db" not in g:
        g.db = sqlite3.connect(
            Config.DATABASE,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Пересоздаёт схему БД."""
    db = get_db()
    db.executescript(SCHEMA_SQL)
    db.commit()


def seed_db():
    """Заполняет БД демонстрационными данными."""
    db = get_db()

    def h(pw):
        return generate_password_hash(pw)

    db.executemany(
        "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
        [
            ("admin", h("admin123"), "Администратор Системы", "admin"),
            ("waiter1", h("waiter123"), "Иванова Анна", "waiter"),
            ("cook1", h("cook123"), "Петров Сергей", "cook"),
            ("bartender1", h("bar123"), "Сидорова Мария", "bartender"),
            ("storekeeper1", h("store123"), "Кузнецов Олег", "storekeeper"),
            ("accountant1", h("acc123"), "Смирнова Елена", "accountant"),
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


def ensure_db():
    """Гарантирует, что БД создана и наполнена."""
    db = get_db()
    has_users = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()

    if has_users is None:
        db.executescript(SCHEMA_SQL)
        db.commit()
        seed_db()
    else:
        count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count == 0:
            seed_db()


@click.command("init-db")
def init_db_command():
    """CLI: flask init-db — создать таблицы заново."""
    init_db()
    click.echo("База данных инициализирована.")


@click.command("seed-db")
def seed_db_command():
    """CLI: flask seed-db — заполнить демо-данными."""
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

# Фиктивный хэш для защиты от timing-атак на логине
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing-only")


def _is_safe_url(target: str) -> bool:
    """Разрешает только внутренние URL — защита от open-redirect."""
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def _default_landing(role: str) -> str:
    """Куда отправлять пользователя после входа в зависимости от роли."""
    return {
        "cook":        url_for("orders.kitchen_view"),
        "bartender":   url_for("orders.kitchen_view"),
        "storekeeper": url_for("warehouse.stock"),
        "accountant":  url_for("reports.index"),
    }.get(role, url_for("index"))


def login_required(view):
    """Требует авторизованного пользователя."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    """Требует, чтобы у пользователя была одна из перечисленных ролей."""
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


def log_action(action):
    """Записывает действие пользователя в журнал аудита."""
    db = get_db()
    user_id = g.user["id"] if g.user else None
    db.execute(
        "INSERT INTO audit_log (user_id, action) VALUES (?, ?)",
        (user_id, action),
    )
    db.commit()


# ==============================================================
# ПОДСИСТЕМА: АВТОРИЗАЦИЯ
# ==============================================================
auth = Blueprint("auth", __name__, url_prefix="/auth")


@auth.before_app_request
def load_logged_in_user():
    """Подгружает текущего пользователя в g.user перед каждым запросом."""
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        return
    db = get_db()
    g.user = db.execute(
        "SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)
    ).fetchone()
    if g.user is None:
        # Пользователь удалён/отключён — сбрасываем сессию
        session.clear()


@auth.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        db = get_db()
        error = None
        user = None

        if not username or not password:
            error = "Введите логин и пароль."
            # Прогоняем фиктивный хэш — постоянное время ответа
            check_password_hash(_DUMMY_HASH, password or "x")
        else:
            user = db.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()

            # Защита от timing-атак: считаем хэш всегда
            stored = user["password_hash"] if user else _DUMMY_HASH
            password_ok = check_password_hash(stored, password)

            if user is None or not password_ok:
                error = "Неверный логин или пароль."
            elif not user["is_active"]:
                error = "Учётная запись отключена."

        if error is None:
            # Защита от session fixation
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            log_action(f"Вход в систему: {user['username']}")

            next_url = request.args.get("next") or request.form.get("next")
            if next_url and _is_safe_url(next_url):
                return redirect(next_url)
            return redirect(_default_landing(user["role"]))

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
    rows = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    return render_template("auth/users.html", users=rows, role_labels=ROLE_LABELS)


@auth.route("/users/new", methods=("GET", "POST"))
@roles_required("admin")
def new_user():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        full_name = (request.form.get("full_name") or "").strip()
        role = request.form.get("role") or ""
        password = request.form.get("password") or ""
        db = get_db()
        error = None

        if not username or not password or not full_name:
            error = "Заполните все обязательные поля."
        elif not USERNAME_RE.match(username):
            error = "Логин: 3–32 символа, латиница, цифры, «.», «_», «-»."
        elif len(full_name) > 200:
            error = "ФИО слишком длинное."
        elif len(password) < 8:
            error = "Пароль должен содержать минимум 8 символов."
        elif role not in ROLE_VALUES:
            error = "Некорректная роль."
        elif db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone():
            error = "Такой логин уже занят."

        if error:
            flash(error, "error")
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, role) "
                "VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password), full_name, role),
            )
            db.commit()
            log_action(f"Создан пользователь {username} ({role})")
            flash("Пользователь создан.", "success")
            return redirect(url_for("auth.users"))

    return render_template("auth/user_form.html", role_labels=ROLE_LABELS)


@auth.route("/users/<int:user_id>/toggle", methods=("POST",))
@roles_required("admin")
def toggle_user(user_id):
    db = get_db()

    # Нельзя отключить себя
    if user_id == g.user["id"]:
        flash("Нельзя отключить собственную учётную запись.", "error")
        return redirect(url_for("auth.users"))

    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        flash("Пользователь не найден.", "error")
        return redirect(url_for("auth.users"))

    # Нельзя отключить последнего активного админа
    if target["is_active"] and target["role"] == "admin":
        active_admins = db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()["c"]
        if active_admins <= 1:
            flash("Нельзя отключить последнего активного администратора.", "error")
            return redirect(url_for("auth.users"))

    db.execute(
        "UPDATE users SET is_active = 1 - is_active WHERE id = ?", (user_id,)
    )
    db.commit()
    log_action(f"Изменён статус пользователя #{user_id}")
    return redirect(url_for("auth.users"))


# ==============================================================
# ПОДСИСТЕМА: УПРАВЛЕНИЕ ЗАКАЗАМИ
# ==============================================================
orders = Blueprint("orders", __name__, url_prefix="/orders")


@orders.route("/")
@roles_required("waiter")
def tables():
    """Схема зала: столы и их текущий статус."""
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
    """Открывает новый заказ на столе (или переходит к уже открытому)."""
    db = get_db()
    table = db.execute(
        "SELECT * FROM restaurant_tables WHERE id = ?", (table_id,)
    ).fetchone()
    if not table:
        flash("Стол не найден.", "error")
        return redirect(url_for("orders.tables"))

    existing = db.execute(
        "SELECT id FROM orders WHERE table_id = ? AND status IN ('open', 'sent', 'served')",
        (table_id,),
    ).fetchone()
    if existing:
        return redirect(url_for("orders.detail", order_id=existing["id"]))

    guests = request.form.get("guests", 1, type=int) or 1
    guests = max(1, min(guests, 50))

    cur = db.execute(
        "INSERT INTO orders (table_id, waiter_id, guests) VALUES (?, ?, ?)",
        (table_id, g.user["id"], guests),
    )
    db.execute(
        "UPDATE restaurant_tables SET status = 'occupied' WHERE id = ?", (table_id,)
    )
    db.commit()
    log_action(f"Открыт заказ #{cur.lastrowid} на столе #{table_id}")
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

    # IDOR: официант видит только свои заказы
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
    total = sum(i["price"] * i["qty"] for i in items if i["status"] != "cancelled")

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
    qty = request.form.get("qty", 1, type=int) or 1
    qty = max(1, min(qty, 99))
    comment = (request.form.get("comment") or "").strip()[:200]

    dish = db.execute(
        "SELECT * FROM dishes WHERE id = ? AND is_active = 1", (dish_id,)
    ).fetchone()
    if not dish:
        flash("Блюдо не найдено.", "error")
        return redirect(url_for("orders.detail", order_id=order_id))

    db.execute(
        "INSERT INTO order_items (order_id, dish_id, qty, price, comment) "
        "VALUES (?, ?, ?, ?, ?)",
        (order_id, dish_id, qty, dish["price"], comment or None),
    )
    db.commit()
    log_action(f"В заказ #{order_id} добавлено блюдо «{dish['name']}» x{qty}")
    return redirect(url_for("orders.detail", order_id=order_id))


@orders.route("/item/<int:item_id>/remove", methods=("POST",))
@roles_required("waiter")
def remove_item(item_id):
    db = get_db()
    item = db.execute(
        "SELECT * FROM order_items WHERE id = ?", (item_id,)
    ).fetchone()
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

    db.execute(
        "UPDATE order_items SET status = 'cancelled' WHERE id = ?", (item_id,)
    )
    db.commit()
    log_action(f"Отменена позиция #{item_id} в заказе #{item['order_id']}")
    return redirect(url_for("orders.detail", order_id=item["order_id"]))


@orders.route("/<int:order_id>/send", methods=("POST",))
@roles_required("waiter")
def send_to_kitchen(order_id):
    """Отправка заказа на кухню/бар — списание ингредиентов по техкартам."""
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order or order["status"] != "open":
        flash("Заказ не найден или уже отправлен.", "error")
        return redirect(url_for("orders.tables"))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя менять чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    items = db.execute(
        "SELECT * FROM order_items WHERE order_id = ? AND status = 'new'",
        (order_id,),
    ).fetchall()
    if not items:
        flash("Нет новых позиций для отправки.", "warning")
        return redirect(url_for("orders.detail", order_id=order_id))

    for item in items:
        tc = db.execute(
            "SELECT * FROM tech_cards WHERE dish_id = ?", (item["dish_id"],)
        ).fetchall()

        # Проверяем остатки (не блокируем, но предупреждаем)
        for ing in tc:
            need = ing["qty_per_portion"] * item["qty"]
            stock = db.execute(
                "SELECT stock_qty FROM ingredients WHERE id = ?",
                (ing["ingredient_id"],),
            ).fetchone()
            if not stock or stock["stock_qty"] < need:
                flash(
                    f"Недостаточно ингредиента «{ing['ingredient_id']}» на складе.",
                    "warning",
                )

        db.execute(
            "UPDATE order_items SET status = 'cooking' WHERE id = ?", (item["id"],)
        )
        for ing in tc:
            write_off_qty = ing["qty_per_portion"] * item["qty"]
            db.execute(
                "UPDATE ingredients SET stock_qty = stock_qty - ? WHERE id = ?",
                (write_off_qty, ing["ingredient_id"]),
            )
            db.execute(
                "INSERT INTO stock_movements "
                "(ingredient_id, qty_change, reason, comment, user_id) "
                "VALUES (?, ?, 'order', ?, ?)",
                (ing["ingredient_id"], -write_off_qty, f"Заказ #{order_id}", g.user["id"]),
            )

    db.execute("UPDATE orders SET status = 'sent' WHERE id = ?", (order_id,))
    db.commit()
    log_action(f"Заказ #{order_id} отправлен на кухню/бар")
    return redirect(url_for("orders.detail", order_id=order_id))


@orders.route("/item/<int:item_id>/status", methods=("POST",))
@roles_required("cook", "bartender", "waiter")
def update_item_status(item_id):
    """Изменение статуса позиции с жёсткой машиной состояний и проверкой роли."""
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
        ok = new_status in ("cooking", "ready", "served")

    if not ok:
        flash("Недопустимый переход статуса.", "error")
        return redirect(request.referrer or url_for("orders.tables"))

    db.execute(
        "UPDATE order_items SET status = ? WHERE id = ?", (new_status, item_id)
    )
    db.commit()
    log_action(f"Позиция #{item_id} → {new_status}")
    return redirect(
        request.referrer or url_for("orders.detail", order_id=item["order_id"])
    )


@orders.route("/<int:order_id>/pay", methods=("POST",))
@roles_required("waiter")
def pay(order_id):
    """Оплата и закрытие заказа, освобождение стола."""
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        flash("Заказ не найден.", "error")
        return redirect(url_for("orders.tables"))
    if order["status"] not in ("sent", "served"):
        flash(
            "Оплатить можно только заказ в статусе «На кухне» или «Подан».",
            "error",
        )
        return redirect(url_for("orders.detail", order_id=order_id))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя оплатить чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    db.execute(
        "UPDATE orders SET status = 'paid', closed_at = datetime('now') WHERE id = ?",
        (order_id,),
    )
    if order["table_id"]:
        db.execute(
            "UPDATE restaurant_tables SET status = 'free' WHERE id = ?",
            (order["table_id"],),
        )
    db.commit()
    log_action(f"Заказ #{order_id} оплачен и закрыт")
    flash("Заказ оплачен и закрыт.", "success")
    return redirect(url_for("orders.tables"))


@orders.route("/kitchen")
@roles_required("cook", "bartender")
def kitchen_view():
    """Экран кухни/бара: активные позиции заказов по станции."""
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
        stock_qty = request.form.get("stock_qty", 0, type=float) or 0
        min_qty = request.form.get("min_qty", 0, type=float) or 0
        db = get_db()

        if not name:
            flash("Укажите наименование товара.", "error")
        elif len(name) > 200:
            flash("Слишком длинное наименование.", "error")
        elif stock_qty < 0 or min_qty < 0:
            flash("Количество не может быть отрицательным.", "error")
        else:
            db.execute(
                "INSERT INTO ingredients (name, unit, stock_qty, min_qty) "
                "VALUES (?, ?, ?, ?)",
                (name, unit, stock_qty, min_qty),
            )
            db.commit()
            log_action(f"Добавлен товар на склад: {name}")
            flash("Товар добавлен.", "success")
            return redirect(url_for("warehouse.stock"))
    return render_template("warehouse/ingredient_form.html")


@warehouse.route("/<int:ingredient_id>/movement", methods=("POST",))
@roles_required("storekeeper")
def movement(ingredient_id):
    """Приход / списание / корректировка по инвентаризации."""
    db = get_db()
    reason = request.form.get("reason")
    qty = request.form.get("qty", 0, type=float)
    comment = (request.form.get("comment") or "").strip()[:200]

    if reason not in ("receipt", "writeoff", "inventory"):
        flash("Некорректный тип операции.", "error")
        return redirect(url_for("warehouse.stock"))

    if qty is None or qty < 0:
        flash("Количество должно быть неотрицательным.", "error")
        return redirect(url_for("warehouse.stock"))

    ing = db.execute(
        "SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)
    ).fetchone()
    if not ing:
        flash("Товар не найден.", "error")
        return redirect(url_for("warehouse.stock"))

    if reason == "receipt":
        change = qty
    elif reason == "writeoff":
        if qty > ing["stock_qty"]:
            flash("Нельзя списать больше, чем есть на складе.", "error")
            return redirect(url_for("warehouse.stock"))
        change = -qty
    else:  # inventory
        change = qty - ing["stock_qty"]

    db.execute(
        "UPDATE ingredients SET stock_qty = stock_qty + ? WHERE id = ?",
        (change, ingredient_id),
    )
    db.execute(
        "INSERT INTO stock_movements "
        "(ingredient_id, qty_change, reason, comment, user_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (ingredient_id, change, reason, comment or None, g.user["id"]),
    )
    db.commit()
    log_action(f"Складская операция «{reason}» по товару #{ingredient_id}: {change:+.2f}")
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
        ORDER BY sm.created_at DESC LIMIT 200
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
    qty = request.form.get("qty", 0, type=float) or 0

    if not ingredient_id or qty <= 0:
        flash("Укажите корректное количество.", "error")
        return redirect(url_for("warehouse.requests_list"))

    ing = db.execute(
        "SELECT id FROM ingredients WHERE id = ?", (ingredient_id,)
    ).fetchone()
    if not ing:
        flash("Товар не найден.", "error")
        return redirect(url_for("warehouse.requests_list"))

    db.execute(
        "INSERT INTO restock_requests (ingredient_id, qty, created_by) "
        "VALUES (?, ?, ?)",
        (ingredient_id, qty, g.user["id"]),
    )
    db.commit()
    log_action(f"Создана заявка на пополнение товара #{ingredient_id}")
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

    req = db.execute(
        "SELECT * FROM restock_requests WHERE id = ?", (request_id,)
    ).fetchone()
    if not req:
        flash("Заявка не найдена.", "error")
        return redirect(url_for("warehouse.requests_list"))
    if req["status"] in ("done", "rejected"):
        flash("Заявка уже закрыта.", "error")
        return redirect(url_for("warehouse.requests_list"))

    db.execute(
        "UPDATE restock_requests SET status = ? WHERE id = ?",
        (new_status, request_id),
    )
    db.commit()
    log_action(f"Заявка #{request_id} переведена в статус {new_status}")
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
        price = request.form.get("price", 0, type=float) or 0
        station = request.form.get("station", "kitchen")
        description = (request.form.get("description") or "").strip()[:1000]

        if not name:
            flash("Укажите название.", "error")
        elif len(name) > 200:
            flash("Слишком длинное название.", "error")
        elif price <= 0 or price > 1_000_000:
            flash("Цена должна быть в диапазоне 0.01–1 000 000.", "error")
        elif station not in ("kitchen", "bar"):
            flash("Некорректная станция.", "error")
        elif category_id and not db.execute(
            "SELECT id FROM categories WHERE id = ?", (category_id,)
        ).fetchone():
            flash("Категория не найдена.", "error")
        else:
            cur = db.execute(
                "INSERT INTO dishes (name, category_id, price, station, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, category_id, price, station, description or None),
            )
            db.commit()
            log_action(f"Добавлено блюдо «{name}»")
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

    db.execute(
        "UPDATE dishes SET is_active = 1 - is_active WHERE id = ?", (dish_id,)
    )
    db.commit()
    log_action(f"Изменена доступность блюда #{dish_id}")
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
        qty = request.form.get("qty_per_portion", type=float)

        if not ingredient_id or not qty or qty <= 0 or qty > 1000:
            flash("Некорректное количество.", "error")
            return redirect(url_for("dishes.tech_card", dish_id=dish_id))

        ing = db.execute(
            "SELECT id FROM ingredients WHERE id = ?", (ingredient_id,)
        ).fetchone()
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
        db.commit()
        log_action(f"Обновлена техкарта блюда #{dish_id}")
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
    row = db.execute(
        "SELECT dish_id FROM tech_cards WHERE id = ?", (item_id,)
    ).fetchone()
    if row:
        db.execute("DELETE FROM tech_cards WHERE id = ?", (item_id,))
        db.commit()
        log_action(f"Удалён ингредиент #{item_id} из техкарты блюда #{row['dish_id']}")
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
            db.commit()
            log_action(f"Добавлена категория меню «{name}»")
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
    total_fund = sum(e["salary"] for e in rows if e["is_active"])
    return render_template(
        "staff/list.html", employees=rows, total_fund=total_fund
    )


@staff.route("/new", methods=("GET", "POST"))
@roles_required("admin")
def new_employee():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        position = (request.form.get("position") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        hired_at = request.form.get("hired_at", "")
        salary = request.form.get("salary", 0, type=float) or 0
        db = get_db()

        if not full_name or not position:
            flash("Укажите ФИО и должность.", "error")
        elif len(full_name) > 200 or len(position) > 100:
            flash("Слишком длинное значение.", "error")
        elif salary < 0 or salary > 10_000_000:
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
            db.commit()
            log_action(f"Принят сотрудник «{full_name}» ({position})")
            flash("Сотрудник добавлен.", "success")
            return redirect(url_for("staff.list_employees"))
    return render_template("staff/employee_form.html")


@staff.route("/<int:employee_id>/toggle", methods=("POST",))
@roles_required("admin")
def toggle_employee(employee_id):
    """Увольнение / восстановление сотрудника."""
    db = get_db()
    emp = db.execute(
        "SELECT id FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    if not emp:
        flash("Сотрудник не найден.", "error")
        return redirect(url_for("staff.list_employees"))

    db.execute(
        "UPDATE employees SET is_active = 1 - is_active WHERE id = ?",
        (employee_id,),
    )
    db.commit()
    log_action(f"Изменён статус занятости сотрудника #{employee_id}")
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
    return render_template(
        "staff/schedule.html", schedule=rows, employees=employees
    )


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

    emp = db.execute(
        "SELECT id FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    if not emp:
        flash("Сотрудник не найден.", "error")
        return redirect(url_for("staff.schedule"))

    db.execute(
        "INSERT INTO schedule (employee_id, work_date, shift_start, shift_end) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, work_date, shift_start, shift_end),
    )
    db.commit()
    log_action(f"Добавлена смена для сотрудника #{employee_id} на {work_date}")
    return redirect(url_for("staff.schedule"))


@staff.route("/schedule/<int:shift_id>/remove", methods=("POST",))
@roles_required("admin")
def remove_shift(shift_id):
    db = get_db()
    db.execute("DELETE FROM schedule WHERE id = ?", (shift_id,))
    db.commit()
    log_action(f"Удалена смена #{shift_id}")
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

    # Валидация дат
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
        if d_from > d_to:
            d_from, d_to = d_to, d_from
            date_from, date_to = str(d_from), str(d_to)
    except ValueError:
        date_from = str(date.today() - timedelta(days=7))
        date_to = str(date.today())

    revenue_row = db.execute(
        """
        SELECT COALESCE(SUM(oi.price * oi.qty), 0) AS revenue,
               COUNT(DISTINCT o.id) AS orders_count
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id AND oi.status != 'cancelled'
        WHERE o.status = 'paid' AND date(o.closed_at) BETWEEN date(?) AND date(?)
        """,
        (date_from, date_to),
    ).fetchone()

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

    daily_revenue_data = [
        {"day": row["day"], "revenue": row["revenue"]} for row in daily_revenue
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
# ФАБРИКА ПРИЛОЖЕНИЯ
# ==============================================================
csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    # Предупреждение о дефолтном SECRET_KEY
    if app.config["SECRET_KEY"].startswith("dev-insecure") and not app.debug:
        app.logger.warning(
            "SECRET_KEY не задан! Установите переменную окружения SECRET_KEY."
        )

    os.makedirs(app.instance_path, exist_ok=True)

    # ---------- CSRF ----------
    csrf.init_app(app)

    # ---------- БД и CLI ----------
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_db_command)

    # ---------- Blueprints ----------
    app.register_blueprint(auth)
    app.register_blueprint(orders)
    app.register_blueprint(warehouse)
    app.register_blueprint(dishes)
    app.register_blueprint(staff)
    app.register_blueprint(reports)

    # ---------- Security headers ----------
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        return response

    # ---------- CSRF error handler ----------
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash("Сессия истекла. Обновите страницу и попробуйте снова.", "error")
        return redirect(request.referrer or url_for("auth.login")), 400

    # ---------- Корневой маршрут: ДАШБОРД ----------
    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))

        db = get_db()
        R = g.user["role"]
        stats = {}

        def q(sql, args=(), one=True):
            row = db.execute(sql, args).fetchone()
            return row[0] if row and row[0] is not None else 0

        # --- Общие ---
        stats["tables_total"] = q("SELECT COUNT(*) FROM restaurant_tables")
        stats["tables_free"]  = q("SELECT COUNT(*) FROM restaurant_tables WHERE status='free'")
        stats["tables_busy"]  = q("SELECT COUNT(*) FROM restaurant_tables WHERE status='occupied'")

        # --- Заказы ---
        stats["orders_today"] = q(
            "SELECT COUNT(*) FROM orders WHERE date(created_at) = date('now')"
        )
        stats["orders_open"] = q(
            "SELECT COUNT(*) FROM orders WHERE status IN ('open','sent','served')"
        )

        # --- Выручка ---
        stats["revenue_today"] = q(
            """SELECT COALESCE(SUM(oi.price * oi.qty), 0)
               FROM orders o JOIN order_items oi ON oi.order_id = o.id
               WHERE o.status = 'paid' AND oi.status != 'cancelled'
                 AND date(o.closed_at) = date('now')"""
        )
        stats["revenue_week"] = q(
            """SELECT COALESCE(SUM(oi.price * oi.qty), 0)
               FROM orders o JOIN order_items oi ON oi.order_id = o.id
               WHERE o.status = 'paid' AND oi.status != 'cancelled'
                 AND date(o.closed_at) >= date('now', '-6 days')"""
        )

        # --- Склад ---
        stats["low_stock_count"] = q(
            "SELECT COUNT(*) FROM ingredients WHERE stock_qty <= min_qty"
        )
        stats["low_stock_value"] = q(
            """SELECT COALESCE(SUM((min_qty - stock_qty) * 100), 0)
               FROM ingredients WHERE stock_qty <= min_qty"""
        )

        # --- Персонал ---
        stats["staff_count"] = q(
            "SELECT COUNT(*) FROM employees WHERE is_active = 1"
        )
        stats["payroll_fund"] = q(
            "SELECT COALESCE(SUM(salary), 0) FROM employees WHERE is_active = 1"
        )

        # --- Заявки на закупку ---
        stats["requests_pending"] = q(
            "SELECT COUNT(*) FROM restock_requests WHERE status IN ('new','approved')"
        )

        # --- Последние заказы ---
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

        # --- Низкие остатки ---
        low_stock = db.execute(
            """SELECT * FROM ingredients
               WHERE stock_qty <= min_qty
               ORDER BY (stock_qty - min_qty) LIMIT 8"""
        ).fetchall()

        # --- Топ блюд за неделю ---
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

        # --- Блюда в работе ---
        station = "bar" if R == "bartender" else "kitchen"
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

    # ---------- Глобальные переменные для шаблонов ----------
    @app.context_processor
    def inject_globals():
        return {
            "role_labels": ROLE_LABELS,
            "restaurant_name": app.config["RESTAURANT_NAME"],
            "is_debug": app.debug,
        }

    # ---------- Обработчик 404 ----------
    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    # ---------- Автоинициализация БД ----------
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
        port=5005,
        debug=debug,
        use_reloader=debug,
    )