"""Авторизация, пользователи, журнал аудита, смена пароля."""
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from config import ROLE_LABELS, ROLE_VALUES, USERNAME_RE
from db import get_db
from rate_limit import login_limiter, password_change_limiter
from utils import (
    default_landing, get_dummy_hash, is_safe_url, log_action,
    login_required, password_ok, roles_required, safe_int,
)


auth = Blueprint("auth", __name__, url_prefix="/auth")


# Эндпоинты, доступные пользователю с must_change_password=1.
_PASSWORD_CHANGE_EXEMPT_ENDPOINTS = (
    "auth.change_password",
    "auth.logout",
    "static",
)


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
        "SELECT id, username, full_name, role, is_active, session_version, "
        "       must_change_password "
        "FROM users WHERE id = ? AND is_active = 1",
        (user_id,),
    ).fetchone()

    if row is None:
        session.clear()
        g.user = None
        return

    try:
        db_sv = row["session_version"]
    except (KeyError, IndexError):
        db_sv = 1

    if session.get("sv", 1) != db_sv:
        session.clear()
        g.user = None
        return

    g.user = row

    try:
        must_change = row["must_change_password"]
    except (KeyError, IndexError):
        must_change = 0

    if must_change and request.endpoint not in _PASSWORD_CHANGE_EXEMPT_ENDPOINTS:
        return redirect(url_for("auth.change_password"))


@auth.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        ctype = (request.content_type or "").lower()
        if ctype and "application/x-www-form-urlencoded" not in ctype \
                and "multipart/form-data" not in ctype:
            flash("Некорректный формат запроса.", "error")
            return render_template("auth/login.html"), 415

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = request.remote_addr or "?"

        if login_limiter.is_blocked(ip, username):
            log_action(
                f"Rate-limit: отклонён вход с заблокированного IP {ip}"
            )
            flash("Слишком много попыток входа. Повторите позже.", "error")
            return render_template("auth/login.html"), 429

        db = get_db()
        error = None
        user = None

        if not username or not password:
            error = "Введите логин и пароль."
            check_password_hash(get_dummy_hash(), password)
        else:
            user = db.execute(
                "SELECT id, username, password_hash, full_name, role, "
                "       is_active, session_version, must_change_password "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            stored = user["password_hash"] if user else get_dummy_hash()
            password_ok_ = check_password_hash(stored, password)
            if user is None or not password_ok_:
                error = "Неверный логин или пароль."
            elif not user["is_active"]:
                error = "Учётная запись отключена."

        if error is None:
            login_limiter.reset(ip, username)
            session.clear()
            session.permanent = (user["role"] != "admin")
            session["user_id"] = user["id"]
            session["sv"] = user["session_version"]
            g.user = user
            log_action(f"Вход в систему: {user['username']}")

            try:
                must_change = user["must_change_password"]
            except (KeyError, IndexError):
                must_change = 0
            if must_change:
                flash("Смените пароль перед началом работы.", "warning")
                return redirect(url_for("auth.change_password"))

            next_url = request.args.get("next") or request.form.get("next")
            if next_url and is_safe_url(next_url):
                return redirect(next_url)
            return redirect(default_landing(user["role"]))

        just_blocked = login_limiter.register_failure(ip, username)
        log_action(f"Неудачная попытка входа: {username!r}")
        if just_blocked:
            log_action(
                f"Rate-limit: IP {ip} заблокирован после серии "
                f"неудачных попыток (username={username!r})"
            )
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


@auth.route("/audit")
@roles_required("admin")
def audit_log():
    db = get_db()
    page = safe_int(request.args.get("page"), min_=1, max_=100000, default=1) or 1
    per_page = 100
    offset = (page - 1) * per_page

    user_filter = safe_int(request.args.get("user_id"), min_=1, default=None)
    action_filter = (request.args.get("action") or "").strip()[:100]

    where, params = [], []
    if user_filter:
        where.append("a.user_id = ?")
        params.append(user_filter)
    if action_filter:
        where.append("a.action LIKE ?")
        params.append(f"%{action_filter}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    total = db.execute(
        f"SELECT COUNT(*) AS c FROM audit_log a{where_sql}", params
    ).fetchone()["c"]

    rows = db.execute(
        f"""
        SELECT a.*, u.username, u.full_name, u.role
        FROM audit_log a
        LEFT JOIN users u ON u.id = a.user_id
        {where_sql}
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, per_page, offset],
    ).fetchall()

    users_ = db.execute(
        "SELECT id, username, full_name FROM users ORDER BY username"
    ).fetchall()

    return render_template(
        "auth/audit_log.html",
        entries=rows, users=users_,
        page=page, per_page=per_page, total=total,
        pages=max(1, (total + per_page - 1) // per_page),
        user_filter=user_filter, action_filter=action_filter,
    )


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
            pwd_err = password_ok(password, username=username, full_name=full_name)
            if pwd_err:
                error = pwd_err
            elif role not in ROLE_VALUES:
                error = "Некорректная роль."
            elif db.execute("SELECT id FROM users WHERE username = ?",
                            (username,)).fetchone():
                error = "Такой логин уже занят."

        if error:
            flash(error, "error")
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, role) "
                "VALUES (?, ?, ?, ?)",
                (username,
                 generate_password_hash(password, method="pbkdf2:sha256:600000"),
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
        target = db.execute("SELECT * FROM users WHERE id = ?",
                            (user_id,)).fetchone()
        if not target:
            db.execute("ROLLBACK")
            flash("Пользователь не найден.", "error")
            return redirect(url_for("auth.users"))
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

        # FIX A06: используем отдельный лимитер, чтобы серия опечаток
        # при смене пароля не блокировала вход в систему с того же IP.
        ip = request.remote_addr or "?"
        rl_key = f"pwchg|{g.user['id']}"
        if password_change_limiter.is_blocked(ip, rl_key):
            flash("Слишком много попыток. Повторите позже.", "error")
            return render_template("auth/change_password.html"), 429

        error = None
        row = db.execute(
            "SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)
        ).fetchone()

        if not row or not check_password_hash(row["password_hash"], old):
            error = "Старый пароль неверен."
        elif new != confirm:
            error = "Новые пароли не совпадают."
        else:
            pwd_err = password_ok(new, username=g.user["username"],
                                  full_name=g.user["full_name"])
            if pwd_err:
                error = pwd_err
            elif check_password_hash(row["password_hash"], new):
                error = "Новый пароль должен отличаться от старого."

        if error:
            password_change_limiter.register_failure(ip, rl_key)
            flash(error, "error")
            return render_template("auth/change_password.html"), 400

        db.execute(
            "UPDATE users SET password_hash = ?, "
            "must_change_password = 0, "
            "session_version = session_version + 1 WHERE id = ?",
            (generate_password_hash(new, method="pbkdf2:sha256:600000"),
             g.user["id"]),
        )
        password_change_limiter.reset(ip, rl_key)
        log_action("Смена собственного пароля",
                   entity_type="user", entity_id=g.user["id"])
        session.clear()
        flash("Пароль изменён. Войдите заново.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/change_password.html")