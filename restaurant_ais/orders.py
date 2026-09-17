"""
Подсистема управления заказами: столы, приём заказов официантом,
отправка на кухню/бар, статусы позиций, оплата (закрытие заказа).
"""
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from database import get_db
from utils import login_required, roles_required, log_action

bp = Blueprint("orders", __name__, url_prefix="/orders")


@bp.route("/")
@login_required
def tables():
    """Схема зала: столы и их текущий статус."""
    db = get_db()
    rows = db.execute(
        """
        SELECT t.*, o.id AS order_id
        FROM restaurant_tables t
        LEFT JOIN orders o ON o.table_id = t.id AND o.status IN ('open', 'sent', 'served')
        ORDER BY t.number
        """
    ).fetchall()
    return render_template("orders/tables.html", tables=rows)


@bp.route("/table/<int:table_id>/open", methods=("POST",))
@roles_required("waiter")
def open_order(table_id):
    """Открывает новый заказ на столе (или переходит к уже открытому)."""
    db = get_db()
    existing = db.execute(
        "SELECT id FROM orders WHERE table_id = ? AND status IN ('open', 'sent', 'served')",
        (table_id,),
    ).fetchone()
    if existing:
        return redirect(url_for("orders.detail", order_id=existing["id"]))

    guests = request.form.get("guests", 1, type=int)
    cur = db.execute(
        "INSERT INTO orders (table_id, waiter_id, guests) VALUES (?, ?, ?)",
        (table_id, g.user["id"], guests),
    )
    db.execute(
        "UPDATE restaurant_tables SET status = 'occupied' WHERE id = ?", (table_id,)
    )
    db.commit()
    log_action(f"Открыт заказ #{cur.lastrowid} на столе #{table_id}")
    return redirect(url_for("orders.detail", order_id=cur.lastrowid))


@bp.route("/<int:order_id>")
@login_required
def detail(order_id):
    db = get_db()
    order = db.execute(
        """
        SELECT o.*, t.number AS table_number, u.full_name AS waiter_name
        FROM orders o
        LEFT JOIN restaurant_tables t ON t.id = o.table_id
        LEFT JOIN users u ON u.id = o.waiter_id
        WHERE o.id = ?
        """,
        (order_id,),
    ).fetchone()
    if order is None:
        flash("Заказ не найден.", "error")
        return redirect(url_for("orders.tables"))

    items = db.execute(
        """
        SELECT oi.*, d.name AS dish_name, d.station
        FROM order_items oi
        JOIN dishes d ON d.id = oi.dish_id
        WHERE oi.order_id = ?
        ORDER BY oi.id
        """,
        (order_id,),
    ).fetchall()
    dishes = db.execute(
        "SELECT d.*, c.name AS category_name FROM dishes d "
        "LEFT JOIN categories c ON c.id = d.category_id WHERE d.is_active = 1 ORDER BY c.name, d.name"
    ).fetchall()
    total = sum(i["price"] * i["qty"] for i in items if i["status"] != "cancelled")

    return render_template(
        "orders/order_detail.html", order=order, items=items, dishes=dishes, total=total
    )


@bp.route("/<int:order_id>/add_item", methods=("POST",))
@roles_required("waiter")
def add_item(order_id):
    db = get_db()
    dish_id = request.form.get("dish_id", type=int)
    qty = request.form.get("qty", 1, type=int)
    comment = request.form.get("comment", "").strip()

    dish = db.execute("SELECT * FROM dishes WHERE id = ?", (dish_id,)).fetchone()
    if not dish:
        flash("Блюдо не найдено.", "error")
        return redirect(url_for("orders.detail", order_id=order_id))

    db.execute(
        "INSERT INTO order_items (order_id, dish_id, qty, price, comment) VALUES (?, ?, ?, ?, ?)",
        (order_id, dish_id, max(qty, 1), dish["price"], comment or None),
    )
    db.commit()
    log_action(f"В заказ #{order_id} добавлено блюдо «{dish['name']}» x{qty}")
    return redirect(url_for("orders.detail", order_id=order_id))


@bp.route("/item/<int:item_id>/remove", methods=("POST",))
@roles_required("waiter")
def remove_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM order_items WHERE id = ?", (item_id,)).fetchone()
    if item:
        db.execute("UPDATE order_items SET status = 'cancelled' WHERE id = ?", (item_id,))
        db.commit()
        log_action(f"Отменена позиция #{item_id} в заказе #{item['order_id']}")
        return redirect(url_for("orders.detail", order_id=item["order_id"]))
    return redirect(url_for("orders.tables"))


@bp.route("/<int:order_id>/send", methods=("POST",))
@roles_required("waiter")
def send_to_kitchen(order_id):
    """Отправка заказа на кухню/бар — списание ингредиентов по техкартам."""
    db = get_db()
    items = db.execute(
        "SELECT * FROM order_items WHERE order_id = ? AND status = 'new'", (order_id,)
    ).fetchall()

    for item in items:
        db.execute(
            "UPDATE order_items SET status = 'cooking' WHERE id = ?", (item["id"],)
        )
        ingredients = db.execute(
            "SELECT * FROM tech_cards WHERE dish_id = ?", (item["dish_id"],)
        ).fetchall()
        for ing in ingredients:
            write_off_qty = ing["qty_per_portion"] * item["qty"]
            db.execute(
                "UPDATE ingredients SET stock_qty = stock_qty - ? WHERE id = ?",
                (write_off_qty, ing["ingredient_id"]),
            )
            db.execute(
                "INSERT INTO stock_movements (ingredient_id, qty_change, reason, comment, user_id) "
                "VALUES (?, ?, 'order', ?, ?)",
                (ing["ingredient_id"], -write_off_qty, f"Заказ #{order_id}", g.user["id"]),
            )

    db.execute("UPDATE orders SET status = 'sent' WHERE id = ?", (order_id,))
    db.commit()
    log_action(f"Заказ #{order_id} отправлен на кухню/бар")
    return redirect(url_for("orders.detail", order_id=order_id))


@bp.route("/item/<int:item_id>/status", methods=("POST",))
@roles_required("cook", "bartender", "waiter")
def update_item_status(item_id):
    """Изменение статуса позиции: cooking -> ready -> served."""
    db = get_db()
    new_status = request.form.get("status")
    if new_status not in ("cooking", "ready", "served"):
        return redirect(url_for("orders.tables"))
    item = db.execute("SELECT * FROM order_items WHERE id = ?", (item_id,)).fetchone()
    if item:
        db.execute("UPDATE order_items SET status = ? WHERE id = ?", (new_status, item_id))
        db.commit()
        return redirect(request.referrer or url_for("orders.detail", order_id=item["order_id"]))
    return redirect(url_for("orders.tables"))


@bp.route("/<int:order_id>/pay", methods=("POST",))
@roles_required("waiter")
def pay(order_id):
    """Оплата и закрытие заказа, освобождение стола."""
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        return redirect(url_for("orders.tables"))

    db.execute(
        "UPDATE orders SET status = 'paid', closed_at = datetime('now') WHERE id = ?",
        (order_id,),
    )
    if order["table_id"]:
        db.execute(
            "UPDATE restaurant_tables SET status = 'free' WHERE id = ?", (order["table_id"],)
        )
    db.commit()
    log_action(f"Заказ #{order_id} оплачен и закрыт")
    flash("Заказ оплачен и закрыт.", "success")
    return redirect(url_for("orders.tables"))


@bp.route("/kitchen")
@roles_required("cook", "bartender")
def kitchen_view():
    """Экран кухни/бара: активные позиции заказов по станции."""
    db = get_db()
    station = "bar" if g.user["role"] == "bartender" else "kitchen"
    items = db.execute(
        """
        SELECT oi.*, d.name AS dish_name, o.id AS order_id, t.number AS table_number
        FROM order_items oi
        JOIN dishes d ON d.id = oi.dish_id
        JOIN orders o ON o.id = oi.order_id
        LEFT JOIN restaurant_tables t ON t.id = o.table_id
        WHERE d.station = ? AND oi.status IN ('cooking', 'ready')
        ORDER BY oi.id
        """,
        (station,),
    ).fetchall()
    return render_template("orders/kitchen.html", items=items, station=station)
