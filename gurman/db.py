"""Соединение с БД, схема, миграции, seed, CLI-команды."""
import os
import sqlite3
from datetime import date

import click
from flask import current_app, g
from passwords import hash_password

from config import Config, DEMO_ACCOUNTS, _IDENT_RE


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
    session_version INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
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
CREATE INDEX idx_audit_log_action      ON audit_log(action);
CREATE INDEX idx_restock_status        ON restock_requests(status);
CREATE INDEX idx_dishes_station_active ON dishes(station, is_active);
"""


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


def ensure_db():
    db = get_db()
    has_users = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if has_users is None:
        db.executescript(SCHEMA_SQL)
        db.commit()
        _migrate_schema(db)
        seed_db()
        return
    _migrate_schema(db)
    count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count == 0:
        seed_db()


def _seed_reference_data(db):
    """Справочники: столы, категории, ингредиенты, блюда, техкарты."""
    db.executemany(
        "INSERT INTO restaurant_tables (number, seats) VALUES (?, ?)",
        [(i, 2 if i % 3 else 4) for i in range(1, 13)],
    )
    db.executemany(
        "INSERT INTO categories (name) VALUES (?)",
        [("Салаты",), ("Супы",), ("Горячее",), ("Десерты",),
         ("Напитки",), ("Бар",)],
    )
    db.executemany(
        "INSERT INTO ingredients (name, unit, stock_qty, min_qty) "
        "VALUES (?, ?, ?, ?)",
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
        "INSERT INTO dishes (name, category_id, price, station) "
        "VALUES (?, ?, ?, ?)",
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
        "INSERT INTO tech_cards (dish_id, ingredient_id, qty_per_portion) "
        "VALUES (?, ?, ?)",
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


def _seed_demo_users(db):
    """
    Демонстрационные учётки.

    ВЫЗЫВАЕТСЯ ТОЛЬКО при Config.SHOW_DEMO_ACCOUNTS == True, что
    невозможно в production (см. config.py + app.py).

    Данные берутся из единого источника config.DEMO_ACCOUNTS, чтобы
    пароли, показываемые в UI (dashboard.register_globals), не
    разъезжались с паролями, реально записанными в БД.
    """
    for acc in DEMO_ACCOUNTS:
        cur = db.execute(
            "INSERT INTO users (username, password_hash, full_name, role) "
            "VALUES (?, ?, ?, ?)",
            (acc["login"], hash_password(acc["password"]),
             acc["full_name"], acc["role"]),
        )
        user_id = cur.lastrowid

        # Парная запись в employees — для всех, кроме админа.
        if acc["role"] != "admin":
            db.execute(
                "INSERT INTO employees (full_name, position, phone, "
                "hired_at, salary, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    acc["full_name"],
                    acc.get("position") or acc["role_label"],
                    acc.get("phone"),
                    str(date.today()),
                    acc.get("salary") or 0,
                    user_id,
                ),
            )


def _seed_admin_with_random_password(db):
    """
    Создаёт единственного администратора со случайным паролем и
    записывает его в файл с правами 0600 (не в stdout!).

    Пароль не должен попадать в systemd journal / docker logs / CI-логи.
    Оператор обязан удалить файл после первого входа.
    """
    import secrets as _secrets
    from pathlib import Path

    pw = _secrets.token_urlsafe(18)
    db.execute(
        "INSERT INTO users (username, password_hash, full_name, role, "
        "                   must_change_password) "
        "VALUES (?, ?, ?, ?, 1)",
        ("admin",
         hash_password(pw),
         "Администратор Системы", "admin"),
    )

    try:
        instance_dir = Path(current_app.instance_path)
        instance_dir.mkdir(parents=True, exist_ok=True)
        pwd_path = instance_dir / "admin_bootstrap_password.txt"

        fd = os.open(pwd_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"login:    admin\npassword: {pw}\n")
                f.write(
                    "Смените пароль при первом входе и удалите этот файл.\n"
                )
        except Exception:
            pass

        current_app.logger.warning(
            "Создан администратор admin со случайным паролем. "
            "Пароль сохранён в %s (права 0600). "
            "Смените его при первом входе и удалите файл.",
            pwd_path,
        )
    except Exception:
        current_app.logger.exception(
            "Не удалось записать bootstrap-пароль в файл. "
            "Сбросьте пароль вручную через SQL или удалите БД и "
            "перезапустите сидирование."
        )


def seed_db():
    """
    Заполнение БД: справочники + одна из двух веток для учётных записей.

    Демо-учётки создаются ТОЛЬКО при SHOW_DEMO_ACCOUNTS=1 (вне prod).
    В production всегда срабатывает ветка с одиночным админом и
    случайным паролем.
    """
    db = get_db()
    _seed_reference_data(db)

    if Config.SHOW_DEMO_ACCOUNTS:
        _seed_demo_users(db)
    else:
        _seed_admin_with_random_password(db)

    db.commit()


_ALLOWED_MIGRATIONS = {
    "users": {
        "session_version": "INTEGER NOT NULL DEFAULT 1",
        "must_change_password": "INTEGER NOT NULL DEFAULT 0",
    },
    "audit_log": {
        "entity_type": "TEXT",
        "entity_id":   "INTEGER",
        "ip":          "TEXT",
    },
}


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
                db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {coltype}')
                try:
                    current_app.logger.info(
                        "[migrate] %s.%s добавлена", table, col
                    )
                except RuntimeError:
                    pass

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
        "CREATE INDEX IF NOT EXISTS idx_audit_log_action     ON audit_log(action)",
        "CREATE INDEX IF NOT EXISTS idx_dishes_station_active ON dishes(station, is_active)",
    ]
    for sql in index_stmts:
        try:
            db.execute(sql)
        except sqlite3.OperationalError:
            pass
    db.commit()


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

@click.command("prune-audit")
@click.option("--days", default=365, show_default=True, type=int,
              help="Хранить записи за последние N дней.")
@click.option("--dry-run", is_flag=True,
              help="Только посчитать, не удалять.")
def prune_audit_command(days, dry_run):
    """Ротация audit_log: удаляет старые записи и сжимает БД (VACUUM).

    Вызывать вручную, через cron или systemd timer. См. README → Обслуживание.
    """
    if days < 1:
        raise click.BadParameter("--days должно быть ≥ 1")
    db = get_db()
    expr = f"-{days} days"
    cnt = db.execute(
        "SELECT COUNT(*) AS c FROM audit_log "
        "WHERE created_at < datetime('now', ?)",
        (expr,),
    ).fetchone()["c"]

    if dry_run:
        click.echo(f"[dry-run] К удалению: {cnt} записей старше {days} дней.")
        return
    if cnt == 0:
        click.echo(f"Записей старше {days} дней нет.")
        return

    db.execute(
        "DELETE FROM audit_log WHERE created_at < datetime('now', ?)",
        (expr,),
    )
    db.execute("VACUUM")
    click.echo(f"Удалено {cnt} записей, БД сжата (VACUUM).")

def register_cli(app):
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_db_command)
    app.cli.add_command(prune_audit_command)