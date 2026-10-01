"""Админ-модуль: просмотр БД и SQL-консоль (только SELECT)."""
import re
import sqlite3

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, url_for,
)

from config import Config, _IDENT_RE
from db import get_db
from utils import log_action, roles_required, safe_int


admin = Blueprint("admin", __name__, url_prefix="/admin")


_FORBIDDEN_SQL_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create",
    "replace", "attach", "detach", "pragma", "vacuum",
    "reindex", "grant", "revoke", "begin", "commit", "rollback",
    "savepoint", "release", "truncate", "load_extension",
)


def _is_select_only(sql: str) -> tuple[bool, str | None]:
    if not sql or not sql.strip():
        return False, "Пустой запрос."
    if len(sql) > 5000:
        return False, "Запрос слишком длинный (максимум 5000 символов)."
    cleaned = re.sub(r"--[^\n]*", " ", sql)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip().rstrip(";").strip()
    if not re.match(r"^\s*(select|with)\b", cleaned, flags=re.IGNORECASE):
        return False, "Разрешены только SELECT/WITH-запросы."
    if ";" in cleaned:
        return False, "Множественные запросы в одном вызове запрещены."
    lower = cleaned.lower()
    for kw in _FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", lower):
            return False, f"Запрос содержит запрещённое ключевое слово: {kw}."
    return True, None


def _readonly_connection() -> sqlite3.Connection:
    """
    FIX: отдельное read-only соединение для SQL-консоли.

    Гарантирует, что даже при обходе blacklist'а (или будущей ошибке в нём)
    через SQL-консоль нельзя изменить БД: SQLite сам отвергнет любые
    write-операции (`PRAGMA query_only = ON` + открытие через `mode=ro`).
    """
    conn = sqlite3.connect(
        f"file:{Config.DATABASE}?mode=ro",
        uri=True,
        timeout=5.0,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn

@admin.route("/db")
@roles_required("admin")
def db_tables():
    db = get_db()
    rows = db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    tables = []
    for r in rows:
        name = r["name"]
        if not _IDENT_RE.fullmatch(name):
            continue
        try:
            cnt = db.execute(f'SELECT COUNT(*) AS c FROM "{name}"').fetchone()["c"]
        except sqlite3.Error:
            cnt = 0
        tables.append({"name": name, "count": cnt})
    return render_template("admin/db_tables.html", tables=tables)


@admin.route("/db/view/<table>")
@roles_required("admin")
def db_view(table):
    if not _IDENT_RE.fullmatch(table):
        flash("Недопустимое имя таблицы.", "error")
        return redirect(url_for("admin.db_tables"))
    db = get_db()
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    if not exists:
        flash("Таблица не найдена.", "error")
        return redirect(url_for("admin.db_tables"))

    page = safe_int(request.args.get("page"), min_=1, max_=100000, default=1) or 1
    per_page = 50
    offset = (page - 1) * per_page
    columns = db.execute(f'PRAGMA table_info("{table}")').fetchall()
    total = db.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()["c"]
    rows = db.execute(f'SELECT * FROM "{table}" LIMIT ? OFFSET ?',
                      (per_page, offset)).fetchall()
    return render_template(
        "admin/db_view.html",
        table=table, columns=columns, rows=rows,
        page=page, per_page=per_page, total=total,
        pages=max(1, (total + per_page - 1) // per_page),
    )


@admin.route("/db/query", methods=("GET", "POST"))
@roles_required("admin")
def db_query():
    sql = ""
    columns = None
    rows = None
    error = None
    if request.method == "POST":
        sql = (request.form.get("sql") or "").strip()
        ok, err = _is_select_only(sql)
        if not ok:
            error = err
        else:
            conn = None
            try:
                conn = _readonly_connection()
                cur = conn.execute(sql)
                columns = [d[0] for d in (cur.description or [])]
                rows = cur.fetchmany(500)
                log_action(
                    f"SQL-консоль: {sql[:200]}",
                    entity_type="db_query",
                )
            except sqlite3.Error:
                # FIX: детали — только в лог сервера, не в UI.
                current_app.logger.exception(
                    "SQL-консоль: ошибка выполнения запроса"
                )
                error = "Ошибка выполнения запроса. Подробности в журнале сервера."
                columns = None
                rows = None
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
    return render_template(
        "admin/db_query.html",
        sql=sql, columns=columns, rows=rows, error=error,
    )