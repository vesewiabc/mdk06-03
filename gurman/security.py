"""Security headers и обработчики ошибок."""
from urllib.parse import urlparse

from flask import (
    flash, g, redirect, render_template, request, url_for,
)
from flask_wtf.csrf import CSRFError

from utils import is_safe_url


def _safe_local_path(referrer: str | None) -> str | None:
    """
    Возвращает локальный path(+query) из referrer'а, если его можно
    безопасно использовать как цель редиректа. Никогда не возвращает
    схему/хост — только относительный путь. Это исключает open redirect,
    даже если referrer указывает на чужой домен.
    """
    if not referrer:
        return None
    try:
        p = urlparse(referrer)
    except ValueError:
        return None
    if p.scheme and p.scheme not in ("http", "https"):
        return None
    local = p.path or "/"
    if p.query:
        local = f"{local}?{p.query}"
    return local if is_safe_url(local) else None


def register_security(app):
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), "
            "usb=(), serial=(), midi=(), magnetometer=(), "
            "accelerometer=(), gyroscope=(), fullscreen=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

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
        if g.user is None:
            flash("Сессия истекла. Войдите заново.", "error")
            return render_template("auth/login.html"), 400
        flash("Сессия истекла. Обновите страницу и повторите действие.", "error")
        local = _safe_local_path(request.referrer)
        if local:
            return redirect(local), 400
        return redirect(url_for("index")), 400

    @app.errorhandler(413)
    def payload_too_large(e):
        return render_template(
            "error.html",
            code=413,
            title="413 — запрос слишком большой",
            message="Размер запроса превышает допустимый лимит.",
        ), 413

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template(
            "error.html",
            code=405,
            title="405 — метод не разрешён",
            message="Этот HTTP-метод не поддерживается для данного адреса.",
        ), 405

    @app.errorhandler(500)
    def internal_error(e):
        user_id = None
        try:
            if g.user is not None:
                user_id = g.user["id"]
        except (KeyError, IndexError, TypeError):
            user_id = None

        app.logger.exception(
            "Внутренняя ошибка сервера: %s %s (user_id=%s)",
            request.method,
            request.path,
            user_id,
        )
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