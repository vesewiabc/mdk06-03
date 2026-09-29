"""
АИС ресторана «Гурман» — точка входа.

Запуск:
    python app.py
"""
import os
import secrets

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from db import close_db, ensure_db, register_cli
from extensions import csrf
from security import register_security
from utils import warmup_dummy_hash

from blueprints.auth import auth
from blueprints.orders import orders
from blueprints.warehouse import warehouse
from blueprints.dishes import dishes
from blueprints.staff import staff
from blueprints.reports import reports
from blueprints.admin import admin
from blueprints.dashboard import index as dashboard_index, register_globals


def _is_prod_env() -> bool:
    return (
        os.environ.get("FLASK_ENV") == "production"
        or os.environ.get("APP_ENV") == "production"
    )


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    # ---------- SECRET_KEY ----------
    secret = app.config.get("SECRET_KEY") or os.environ.get("SECRET_KEY")
    if not secret:
        secret = secrets.token_hex(32)
        app.logger.warning(
            "SECRET_KEY не задан — сгенерирован временный ключ. "
            "Сессии сбросятся при перезапуске. Для продакшена задайте "
            "переменную окружения SECRET_KEY."
        )
    app.config["SECRET_KEY"] = secret

    # ---------- FIX A02/A07: жёсткие запреты в production ----------
    if _is_prod_env():
        if app.config.get("SHOW_DEMO_ACCOUNTS"):
            raise RuntimeError(
                "SHOW_DEMO_ACCOUNTS=1 запрещён в production. "
                "Уберите переменную из окружения."
            )
        if not app.config.get("SESSION_COOKIE_SECURE"):
            raise RuntimeError(
                "В production требуется SESSION_COOKIE_SECURE=1."
            )
        if os.environ.get("DEBUG", "0") == "1":
            raise RuntimeError("DEBUG=1 запрещён в production.")

    # ---------- TRUSTED_PROXIES ----------
    if app.config.get("SESSION_COOKIE_SECURE"):
        app.config["PREFERRED_URL_SCHEME"] = "https"

    trusted = app.config.get("TRUSTED_PROXIES", 0)
    if trusted > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=trusted, x_proto=trusted,
            x_host=0, x_port=0, x_prefix=0,
        )

    os.makedirs(app.instance_path, exist_ok=True)

    csrf.init_app(app)
    app.teardown_appcontext(close_db)
    register_cli(app)

    # ---------- Blueprints ----------
    app.register_blueprint(auth)
    app.register_blueprint(orders)
    app.register_blueprint(warehouse)
    app.register_blueprint(dishes)
    app.register_blueprint(staff)
    app.register_blueprint(reports)
    app.register_blueprint(admin)
    app.add_url_rule("/", endpoint="index", view_func=dashboard_index)

    register_security(app)
    register_globals(app)

    warmup_dummy_hash()

    with app.app_context():
        ensure_db()

    return app


app = create_app()


if __name__ == "__main__":
    # FIX A02: безопасный дефолт — debug ВЫКЛЮЧЕН.
    # Включается только явным DEBUG=1.
    debug = os.environ.get("DEBUG", "0") == "1"
    app.run(
        host="127.0.0.1",
        port=5067,
        debug=debug,
        use_reloader=debug,
    )