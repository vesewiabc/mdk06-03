"""Подсистема авторизации: вход, выход, управление пользователями (админ)."""
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db
from utils import roles_required, log_action, ROLE_LABELS

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.before_app_request
def load_logged_in_user():
    """Подгружает текущего пользователя в g.user перед каждым запросом."""
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        db = get_db()
        g.user = db.execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)
        ).fetchone()


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        db = get_db()
        error = None
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            error = "Неверный логин или пароль."
        elif not user["is_active"]:
            error = "Учётная запись отключена."

        if error is None:
            session.clear()
            session["user_id"] = user["id"]
            log_action(f"Вход в систему: {user['username']}")
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)

        flash(error, "error")

    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    if g.user:
        log_action(f"Выход из системы: {g.user['username']}")
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/users")
@roles_required("admin")
def users():
    db = get_db()
    rows = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    return render_template("auth/users.html", users=rows, role_labels=ROLE_LABELS)


@bp.route("/users/new", methods=("GET", "POST"))
@roles_required("admin")
def new_user():
    if request.method == "POST":
        username = request.form["username"].strip()
        full_name = request.form["full_name"].strip()
        role = request.form["role"]
        password = request.form["password"]
        db = get_db()
        error = None
        if not username or not password or not full_name:
            error = "Заполните все обязательные поля."
        elif db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            error = "Такой логин уже занят."

        if error:
            flash(error, "error")
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password), full_name, role),
            )
            db.commit()
            log_action(f"Создан пользователь {username} ({role})")
            flash("Пользователь создан.", "success")
            return redirect(url_for("auth.users"))

    return render_template("auth/user_form.html", role_labels=ROLE_LABELS)


@bp.route("/users/<int:user_id>/toggle", methods=("POST",))
@roles_required("admin")
def toggle_user(user_id):
    db = get_db()
    db.execute(
        "UPDATE users SET is_active = 1 - is_active WHERE id = ?", (user_id,)
    )
    db.commit()
    log_action(f"Изменён статус пользователя #{user_id}")
    return redirect(url_for("auth.users"))
