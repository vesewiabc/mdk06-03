"""
Точка сборки приложения Flask — АИС ресторана «Гурман».
Здесь создаётся app-фабрика и регистрируются модули (blueprints) по подсистемам:
auth, orders, warehouse, dishes, staff, reports.
"""
import os

from flask import Flask, g, redirect, render_template, url_for

import database
from config import Config
from utils import ROLE_LABELS


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    # регистрация работы с БД
    database.init_app(app)

    # регистрация подсистем (blueprints)
    import auth
    import orders
    import warehouse
    import dishes
    import staff
    import reports

    app.register_blueprint(auth.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(warehouse.bp)
    app.register_blueprint(dishes.bp)
    app.register_blueprint(staff.bp)
    app.register_blueprint(reports.bp)

    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))
        return render_template("index.html")

    @app.context_processor
    def inject_globals():
        return {"role_labels": ROLE_LABELS, "restaurant_name": app.config["RESTAURANT_NAME"]}

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404


    # Автоинициализация БД при первом запуске
    with app.app_context():
        database.ensure_db()

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
