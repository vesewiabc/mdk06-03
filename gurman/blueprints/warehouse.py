"""Склад: остатки, движения, заявки."""
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for,
)

from db import get_db
from utils import log_action, roles_required, safe_float


warehouse = Blueprint("warehouse", __name__, url_prefix="/warehouse")


@warehouse.route("/")
@roles_required("storekeeper", "accountant")
def stock():
    db = get_db()
    ingredients = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
    return render_template("warehouse/stock.html", ingredients=ingredients)


@warehouse.route("/new", methods=("GET", "POST"))
@roles_required("storekeeper")
def new_ingredient():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        unit = (request.form.get("unit") or "шт").strip()[:20] or "шт"
        stock_qty = safe_float(request.form.get("stock_qty"), min_=0, max_=1_000_000)
        min_qty = safe_float(request.form.get("min_qty"), min_=0, max_=1_000_000)
        db = get_db()

        if not name:
            flash("Укажите наименование товара.", "error")
        elif len(name) > 200:
            flash("Слишком длинное наименование.", "error")
        elif stock_qty is None or min_qty is None:
            flash("Некорректное количество (0 – 1 000 000).", "error")
        else:
            db.execute(
                "INSERT INTO ingredients (name, unit, stock_qty, min_qty) "
                "VALUES (?, ?, ?, ?)", (name, unit, stock_qty, min_qty),
            )
            log_action(f"Добавлен товар на склад: {name}", entity_type="ingredient")
            flash("Товар добавлен.", "success")
            return redirect(url_for("warehouse.stock"))
    return render_template("warehouse/ingredient_form.html")


@warehouse.route("/<int:ingredient_id>/movement", methods=("POST",))
@roles_required("storekeeper")
def movement(ingredient_id):
    db = get_db()
    reason = request.form.get("reason")
    comment = (request.form.get("comment") or "").strip()[:200]

    if reason not in ("receipt", "writeoff", "inventory"):
        flash("Некорректный тип операции.", "error")
        return redirect(url_for("warehouse.stock"))
    if reason == "inventory" and not comment:
        flash("Для инвентаризации обязателен комментарий с обоснованием.", "error")
        return redirect(url_for("warehouse.stock"))

    qty = safe_float(request.form.get("qty"), min_=0, max_=1_000_000)
    if qty is None:
        flash("Введите корректное количество (0 – 1 000 000).", "error")
        return redirect(url_for("warehouse.stock"))
    if reason in ("receipt", "writeoff") and qty <= 0:
        flash("Количество должно быть больше нуля.", "error")
        return redirect(url_for("warehouse.stock"))

    db.execute("BEGIN IMMEDIATE")
    try:
        ing = db.execute("SELECT * FROM ingredients WHERE id = ?",
                         (ingredient_id,)).fetchone()
        if not ing:
            db.execute("ROLLBACK")
            flash("Товар не найден.", "error")
            return redirect(url_for("warehouse.stock"))

        if reason == "receipt":
            change = qty
        elif reason == "writeoff":
            if qty > ing["stock_qty"]:
                db.execute("ROLLBACK")
                flash("Нельзя списать больше, чем есть на складе.", "error")
                return redirect(url_for("warehouse.stock"))
            change = -qty
        else:
            change = qty - ing["stock_qty"]

        new_stock = ing["stock_qty"] + change
        if new_stock < 0:
            db.execute("ROLLBACK")
            flash("Остаток не может быть отрицательным.", "error")
            return redirect(url_for("warehouse.stock"))

        db.execute("UPDATE ingredients SET stock_qty = ? WHERE id = ?",
                   (new_stock, ingredient_id))
        db.execute(
            "INSERT INTO stock_movements "
            "(ingredient_id, qty_change, reason, comment, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ingredient_id, change, reason, comment or None, g.user["id"]),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    if reason == "inventory":
        log_action(
            f"Инвентаризация #{ingredient_id}: было {ing['stock_qty']:.3f}, "
            f"стало {qty:.3f} ({comment})",
            entity_type="ingredient", entity_id=ingredient_id,
        )
    else:
        log_action(
            f"Складская операция «{reason}» по товару #{ingredient_id}: {change:+.2f}",
            entity_type="ingredient", entity_id=ingredient_id,
        )
    return redirect(url_for("warehouse.stock"))


@warehouse.route("/movements")
@roles_required("storekeeper", "accountant")
def movements():
    db = get_db()
    rows = db.execute(
        """
        SELECT sm.*, i.name AS ingredient_name, i.unit, u.full_name AS user_name
        FROM stock_movements sm
        JOIN ingredients i ON i.id = sm.ingredient_id
        LEFT JOIN users u ON u.id = sm.user_id
        ORDER BY sm.created_at DESC, sm.id DESC
        LIMIT 200
        """
    ).fetchall()
    return render_template("warehouse/movements.html", movements=rows)


@warehouse.route("/requests")
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


@warehouse.route("/requests/new", methods=("POST",))
@roles_required("storekeeper")
def new_request():
    db = get_db()
    ingredient_id = request.form.get("ingredient_id", type=int)
    qty = safe_float(request.form.get("qty"), min_=0.01, max_=1_000_000)

    if not ingredient_id or qty is None:
        flash("Укажите корректное количество.", "error")
        return redirect(url_for("warehouse.requests_list"))
    ing = db.execute("SELECT id FROM ingredients WHERE id = ?",
                     (ingredient_id,)).fetchone()
    if not ing:
        flash("Товар не найден.", "error")
        return redirect(url_for("warehouse.requests_list"))

    db.execute(
        "INSERT INTO restock_requests (ingredient_id, qty, created_by) "
        "VALUES (?, ?, ?)", (ingredient_id, qty, g.user["id"]),
    )
    log_action(f"Создана заявка на пополнение товара #{ingredient_id}",
               entity_type="restock_request")
    flash("Заявка на пополнение создана.", "success")
    return redirect(url_for("warehouse.requests_list"))


@warehouse.route("/requests/<int:request_id>/status", methods=("POST",))
@roles_required("storekeeper", "accountant")
def update_request_status(request_id):
    db = get_db()
    new_status = request.form.get("status")
    if new_status not in ("approved", "done", "rejected"):
        flash("Некорректный статус.", "error")
        return redirect(url_for("warehouse.requests_list"))

    db.execute("BEGIN IMMEDIATE")
    try:
        req = db.execute("SELECT * FROM restock_requests WHERE id = ?",
                         (request_id,)).fetchone()
        if not req:
            db.execute("ROLLBACK")
            flash("Заявка не найдена.", "error")
            return redirect(url_for("warehouse.requests_list"))
        if req["status"] in ("done", "rejected"):
            db.execute("ROLLBACK")
            flash("Заявка уже закрыта.", "error")
            return redirect(url_for("warehouse.requests_list"))

        db.execute("UPDATE restock_requests SET status = ? WHERE id = ?",
                   (new_status, request_id))

        if new_status == "done":
            db.execute("UPDATE ingredients SET stock_qty = stock_qty + ? WHERE id = ?",
                       (req["qty"], req["ingredient_id"]))
            db.execute(
                "INSERT INTO stock_movements "
                "(ingredient_id, qty_change, reason, comment, user_id) "
                "VALUES (?, ?, 'receipt', ?, ?)",
                (req["ingredient_id"], req["qty"],
                 f"Заявка #{request_id}", g.user["id"]),
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Заявка #{request_id} → {new_status}",
               entity_type="restock_request", entity_id=request_id)
    return redirect(url_for("warehouse.requests_list"))