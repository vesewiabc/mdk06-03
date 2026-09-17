"""
Модуль работы с базой данных SQLite.
Инициализация соединения на запрос (Flask g), создание схемы, наполнение
тестовыми данными командой `flask init-db`.
"""
import sqlite3
from datetime import date

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash


def get_db():
    """Возвращает соединение с БД, привязанное к текущему запросу."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
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
    """Пересоздаёт схему БД из schema.sql."""
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))


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

    dishes = [
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
    ]
    db.executemany(
        "INSERT INTO dishes (name, category_id, price, station) VALUES (?, ?, ?, ?)",
        dishes,
    )

    tech_cards = [
        (1, 6, 0.15), (1, 5, 0.03), (1, 2, 0.12),
        (2, 6, 0.10), (2, 7, 0.08), (2, 8, 0.06),
        (3, 1, 0.20), (3, 3, 0.10),
        (5, 3, 0.30),
        (6, 4, 0.25),
        (7, 9, 0.08), (7, 10, 0.05),
        (10, 11, 0.02), (10, 12, 0.10),
        (11, 11, 0.02),
    ]
    db.executemany(
        "INSERT INTO tech_cards (dish_id, ingredient_id, qty_per_portion) VALUES (?, ?, ?)",
        tech_cards,
    )

    db.executemany(
        "INSERT INTO employees (full_name, position, phone, hired_at, salary, user_id) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("Иванова Анна", "Официант", "+7 900 111-11-11", str(date.today()), 45000, 2),
            ("Петров Сергей", "Повар", "+7 900 222-22-22", str(date.today()), 55000, 3),
            ("Сидорова Мария", "Бармен", "+7 900 333-33-33", str(date.today()), 42000, 4),
            ("Кузнецов Олег", "Кладовщик", "+7 900 444-44-44", str(date.today()), 40000, 5),
            ("Смирнова Елена", "Бухгалтер", "+7 900 555-55-55", str(date.today()), 60000, 6),
        ],
    )

    db.commit()


def init_app(app):
    """Регистрирует функции работы с БД в приложении Flask."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_db_command)


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

def ensure_db():
    """Гарантирует, что БД создана и наполнена.
       Вызывается при старте приложения — чтобы сразу можно было логиниться."""
    db = get_db()
    has_users = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()

    if has_users is None:
        # Таблиц нет — создаём схему
        with current_app.open_resource("schema.sql") as f:
            db.executescript(f.read().decode("utf8"))
        db.commit()
        seed_db()
        current_app.logger.info("БД создана и заполнена демо-данными.")
    else:
        # Таблицы есть, но пользователей нет — наполняем
        count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count == 0:
            seed_db()
            current_app.logger.info("БД заполнена демо-данными.")