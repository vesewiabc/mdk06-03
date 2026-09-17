"""Общие вспомогательные функции и декораторы (доступ по ролям, аудит)."""
import functools

from flask import g, redirect, request, session, url_for, flash

from database import get_db

ROLE_LABELS = {
    "admin": "Администратор",
    "waiter": "Официант",
    "cook": "Повар",
    "bartender": "Бармен",
    "storekeeper": "Кладовщик",
    "accountant": "Бухгалтер",
}


def login_required(view):
    """Требует авторизованного пользователя."""
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


def roles_required(*roles):
    """Требует, чтобы у пользователя была одна из перечисленных ролей."""
    def decorator(view):
        @functools.wraps(view)
        def wrapped(**kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.path))
            if g.user["role"] not in roles and g.user["role"] != "admin":
                flash("Недостаточно прав для выполнения этого действия.", "error")
                return redirect(url_for("index"))
            return view(**kwargs)
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
