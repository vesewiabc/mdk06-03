"""
Подсистема складского учёта: товары/ингредиенты, остатки, инвентаризация,
заявки на пополнение.
"""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from database import get_db
from utils import roles_required, log_action

bp = Blueprint("warehouse", __name__, url_prefix="/warehouse")


@bp.route("/")
@roles_required("storekeeper", "accountant")
def stock():
    db = get_db()
    ingredients = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
    return render_template("warehouse/stock.html", ingredients=ingredients)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("storekeeper")
def new_ingredient():
    if request.method == "POST":
        name = request.form["name"].strip()
        unit = request.form["unit"].strip() or "шт"
        stock_qty = request.form.get("stock_qty", 0, type=float)
        min_qty = request.form.get("min_qty", 0, type=float)
        db = get_db()
        if not name:
            flash("Укажите наименование товара.", "error")
        else:
            db.execute(
                "INSERT INTO ingredients (name, unit, stock_qty, min_qty) VALUES (?, ?, ?, ?)",
                (name, unit, stock_qty, min_qty),
            )
            db.commit()
            log_action(f"Добавлен товар на склад: {name}")
            flash("Товар добавлен.", "success")
            return redirect(url_for("warehouse.stock"))
    return render_template("warehouse/ingredient_form.html")


@bp.route("/<int:ingredient_id>/movement", methods=("POST",))
@roles_required("storekeeper")
def movement(ingredient_id):
    """Приход / списание / корректировка по инвентаризации."""
    db = get_db()
    reason = request.form.get("reason")
    qty = request.form.get("qty", 0, type=float)
    comment = request.form.get("comment", "").strip()

    if reason not in ("receipt", "writeoff", "inventory"):
        flash("Некорректный тип операции.", "error")
        return redirect(url_for("warehouse.stock"))

    change = qty if reason == "receipt" else -qty
    if reason == "inventory":
        ing = db.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
        change = qty - ing["stock_qty"]

    db.execute(
        "UPDATE ingredients SET stock_qty = stock_qty + ? WHERE id = ?",
        (change, ingredient_id),
    )
    db.execute(
        "INSERT INTO stock_movements (ingredient_id, qty_change, reason, comment, user_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (ingredient_id, change, reason, comment or None, g.user["id"]),
    )
    db.commit()
    log_action(f"Складская операция «{reason}» по товару #{ingredient_id}: {change:+.2f}")
    return redirect(url_for("warehouse.stock"))


@bp.route("/movements")
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


@bp.route("/requests")
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
    return render_template("warehouse/requests.html", requests=rows, low_stock=low_stock)


@bp.route("/requests/new", methods=("POST",))
@roles_required("storekeeper")
def new_request():
    db = get_db()
    ingredient_id = request.form.get("ingredient_id", type=int)
    qty = request.form.get("qty", 0, type=float)
    if ingredient_id and qty > 0:
        db.execute(
            "INSERT INTO restock_requests (ingredient_id, qty, created_by) VALUES (?, ?, ?)",
            (ingredient_id, qty, g.user["id"]),
        )
        db.commit()
        log_action(f"Создана заявка на пополнение товара #{ingredient_id}")
        flash("Заявка на пополнение создана.", "success")
    return redirect(url_for("warehouse.requests_list"))


@bp.route("/requests/<int:request_id>/status", methods=("POST",))
@roles_required("storekeeper", "accountant")
def update_request_status(request_id):
    db = get_db()
    new_status = request.form.get("status")
    if new_status in ("approved", "done", "rejected"):
        db.execute(
            "UPDATE restock_requests SET status = ? WHERE id = ?", (new_status, request_id)
        )
        db.commit()
        log_action(f"Заявка #{request_id} переведена в статус {new_status}")
    return redirect(url_for("warehouse.requests_list"))
