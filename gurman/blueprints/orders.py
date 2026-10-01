"""Управление заказами."""
from collections import defaultdict

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for,
)

from db import get_db
from utils import log_action, money, roles_required, safe_int


orders = Blueprint("orders", __name__, url_prefix="/orders")


@orders.route("/")
@roles_required("waiter")
def tables():
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


@orders.route("/table/<int:table_id>/open", methods=("POST",))
@roles_required("waiter")
def open_order(table_id):
    db = get_db()
    table = db.execute("SELECT * FROM restaurant_tables WHERE id = ?",
                       (table_id,)).fetchone()
    if not table:
        flash("Стол не найден.", "error")
        return redirect(url_for("orders.tables"))
    if table["status"] == "reserved":
        flash("Стол забронирован. Сначала снимите бронь.", "error")
        return redirect(url_for("orders.tables"))

    guests = safe_int(request.form.get("guests"), min_=1, max_=50, default=1)

    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute(
            "SELECT id FROM orders WHERE table_id = ? "
            "AND status IN ('open', 'sent', 'served')", (table_id,)
        ).fetchone()
        if existing:
            db.execute("ROLLBACK")
            return redirect(url_for("orders.detail", order_id=existing["id"]))
        cur = db.execute(
            "INSERT INTO orders (table_id, waiter_id, guests) VALUES (?, ?, ?)",
            (table_id, g.user["id"], guests),
        )
        db.execute("UPDATE restaurant_tables SET status = 'occupied' WHERE id = ?",
                   (table_id,))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Открыт заказ #{cur.lastrowid} на столе #{table_id}",
               entity_type="order", entity_id=cur.lastrowid)
    return redirect(url_for("orders.detail", order_id=cur.lastrowid))


@orders.route("/<int:order_id>")
@roles_required("waiter")
def detail(order_id):
    db = get_db()
    order = db.execute(
        """
        SELECT o.*, t.number AS table_number, u.full_name AS waiter_name
        FROM orders o
        LEFT JOIN restaurant_tables t ON t.id = o.table_id
        LEFT JOIN users u ON u.id = o.waiter_id
        WHERE o.id = ?
        """, (order_id,),
    ).fetchone()
    if order is None:
        flash("Заказ не найден.", "error")
        return redirect(url_for("orders.tables"))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Этот заказ принадлежит другому официанту.", "error")
        return redirect(url_for("orders.tables"))

    items = db.execute(
        """
        SELECT oi.*, d.name AS dish_name, d.station
        FROM order_items oi
        JOIN dishes d ON d.id = oi.dish_id
        WHERE oi.order_id = ?
        ORDER BY oi.id
        """, (order_id,),
    ).fetchall()
    dishes = db.execute(
        "SELECT d.*, c.name AS category_name FROM dishes d "
        "LEFT JOIN categories c ON c.id = d.category_id "
        "WHERE d.is_active = 1 ORDER BY c.name, d.name"
    ).fetchall()
    total = money(sum(i["price"] * i["qty"] for i in items if i["status"] != "cancelled"))

    return render_template("orders/order_detail.html",
                           order=order, items=items, dishes=dishes, total=total)


@orders.route("/<int:order_id>/add_item", methods=("POST",))
@roles_required("waiter")
def add_item(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order or order["status"] != "open":
        flash("Заказ не найден или уже отправлен/закрыт.", "error")
        return redirect(url_for("orders.tables"))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя менять чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    dish_id = request.form.get("dish_id", type=int)
    qty = safe_int(request.form.get("qty"), min_=1, max_=99, default=1)
    comment = (request.form.get("comment") or "").strip()[:200]

    dish = db.execute("SELECT * FROM dishes WHERE id = ? AND is_active = 1",
                      (dish_id,)).fetchone()
    if not dish:
        flash("Блюдо не найдено.", "error")
        return redirect(url_for("orders.detail", order_id=order_id))

    price = money(dish["price"])
    db.execute(
        "INSERT INTO order_items (order_id, dish_id, qty, price, comment) "
        "VALUES (?, ?, ?, ?, ?)",
        (order_id, dish_id, qty, price, comment or None),
    )
    log_action(f"В заказ #{order_id} добавлено блюдо «{dish['name']}» x{qty}",
               entity_type="order", entity_id=order_id)
    return redirect(url_for("orders.detail", order_id=order_id))


@orders.route("/item/<int:item_id>/remove", methods=("POST",))
@roles_required("waiter")
def remove_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM order_items WHERE id = ?",
                      (item_id,)).fetchone()
    if not item:
        flash("Позиция не найдена.", "error")
        return redirect(url_for("orders.tables"))
    order = db.execute("SELECT * FROM orders WHERE id = ?",
                       (item["order_id"],)).fetchone()
    if not order or order["status"] != "open" or item["status"] != "new":
        flash("Удалить можно только новую позицию из открытого заказа.", "error")
        return redirect(url_for("orders.detail", order_id=item["order_id"]))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя менять чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    db.execute("UPDATE order_items SET status = 'cancelled' WHERE id = ?",
               (item_id,))
    log_action(f"Отменена позиция #{item_id} в заказе #{item['order_id']}",
               entity_type="order_item", entity_id=item_id)
    return redirect(url_for("orders.detail", order_id=item["order_id"]))


@orders.route("/<int:order_id>/send", methods=("POST",))
@roles_required("waiter")
def send_to_kitchen(order_id):
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        order = db.execute("SELECT * FROM orders WHERE id = ?",
                           (order_id,)).fetchone()
        if not order or order["status"] != "open":
            db.execute("ROLLBACK")
            flash("Заказ не найден или уже отправлен.", "error")
            return redirect(url_for("orders.tables"))
        if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
            db.execute("ROLLBACK")
            flash("Нельзя менять чужой заказ.", "error")
            return redirect(url_for("orders.tables"))

        items = db.execute(
            "SELECT * FROM order_items WHERE order_id = ? AND status = 'new'",
            (order_id,),
        ).fetchall()
        if not items:
            db.execute("ROLLBACK")
            flash("Нет новых позиций для отправки.", "warning")
            return redirect(url_for("orders.detail", order_id=order_id))

        dish_ids = [i["dish_id"] for i in items]
        qmarks = ",".join("?" * len(dish_ids))
        tc_rows = db.execute(
            f"SELECT dish_id, ingredient_id, qty_per_portion "
            f"FROM tech_cards WHERE dish_id IN ({qmarks})", dish_ids,
        ).fetchall()
        tc_by_dish = defaultdict(list)
        for r in tc_rows:
            tc_by_dish[r["dish_id"]].append(r)

        needs = defaultdict(float)
        for item in items:
            for ing in tc_by_dish.get(item["dish_id"], []):
                needs[ing["ingredient_id"]] += ing["qty_per_portion"] * item["qty"]

        if not needs:
            db.execute("ROLLBACK")
            flash("У блюд не заполнены техкарты.", "error")
            return redirect(url_for("orders.detail", order_id=order_id))

        ing_ids = list(needs.keys())
        qmarks = ",".join("?" * len(ing_ids))
        stocks = {
            row["id"]: row
            for row in db.execute(
                f"SELECT id, name, unit, stock_qty FROM ingredients "
                f"WHERE id IN ({qmarks})", ing_ids,
            ).fetchall()
        }

        shortages = []
        for ing_id, need in needs.items():
            row = stocks.get(ing_id)
            if not row or row["stock_qty"] + 1e-9 < need:
                shortages.append(
                    (row["name"] if row else f"#{ing_id}", need,
                     row["stock_qty"] if row else 0,
                     row["unit"] if row else "?")
                )
        if shortages:
            db.execute("ROLLBACK")
            for name, need, have, unit in shortages:
                flash(f"Недостаточно «{name}»: нужно {need:.3f} {unit}, "
                      f"есть {have:.3f} {unit}.", "error")
            return redirect(url_for("orders.detail", order_id=order_id))

        for item in items:
            db.execute("UPDATE order_items SET status = 'cooking' WHERE id = ?",
                       (item["id"],))
            for ing in tc_by_dish.get(item["dish_id"], []):
                write_off_qty = ing["qty_per_portion"] * item["qty"]
                db.execute("UPDATE ingredients SET stock_qty = stock_qty - ? WHERE id = ?",
                           (write_off_qty, ing["ingredient_id"]))
                db.execute(
                    "INSERT INTO stock_movements "
                    "(ingredient_id, qty_change, reason, comment, user_id) "
                    "VALUES (?, ?, 'order', ?, ?)",
                    (ing["ingredient_id"], -write_off_qty,
                     f"Заказ #{order_id}", g.user["id"]),
                )
        db.execute("UPDATE orders SET status = 'sent' WHERE id = ?", (order_id,))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Заказ #{order_id} отправлен на кухню/бар",
               entity_type="order", entity_id=order_id)
    return redirect(url_for("orders.detail", order_id=order_id))


@orders.route("/item/<int:item_id>/status", methods=("POST",))
@roles_required("cook", "bartender", "waiter")
def update_item_status(item_id):
    db = get_db()
    new_status = request.form.get("status")
    item = db.execute(
        """
        SELECT oi.*, d.station, o.status AS order_status, o.waiter_id
        FROM order_items oi
        JOIN dishes d ON d.id = oi.dish_id
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.id = ?
        """, (item_id,),
    ).fetchone()
    if not item:
        flash("Позиция не найдена.", "error")
        return redirect(url_for("orders.tables"))

    role = g.user["role"]
    ok = False
    if role in ("cook", "bartender"):
        expected_station = "bar" if role == "bartender" else "kitchen"
        if (item["station"] == expected_station
                and item["status"] == "cooking"
                and new_status == "ready"):
            ok = True
    elif role == "waiter":
        if (item["waiter_id"] == g.user["id"]
                and item["status"] == "ready"
                and new_status == "served"):
            ok = True
    elif role == "admin":
        allowed = {
            "cooking": {"ready", "cancelled"},
            "ready":   {"served", "cancelled"},
            "new":     {"cancelled"},
        }
        if new_status in allowed.get(item["status"], set()):
            ok = True

    if not ok:
        flash("Недопустимый переход статуса.", "error")
        return redirect(url_for("orders.tables"))

    db.execute("UPDATE order_items SET status = ? WHERE id = ?",
               (new_status, item_id))
    log_action(f"Позиция #{item_id} → {new_status}",
               entity_type="order_item", entity_id=item_id)
    return redirect(url_for("orders.detail", order_id=item["order_id"]))


@orders.route("/<int:order_id>/pay", methods=("POST",))
@roles_required("waiter")
def pay(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?",
                       (order_id,)).fetchone()
    if not order:
        flash("Заказ не найден.", "error")
        return redirect(url_for("orders.tables"))
    if order["status"] not in ("sent", "served"):
        flash("Оплатить можно только заказ в статусе «На кухне» "
              "или «Подан».", "error")
        return redirect(url_for("orders.detail", order_id=order_id))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя оплатить чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    # A06-4 / A08-2: не позволяем закрыть заказ, пока по нему есть
    # позиции, которые ещё в работе или не поданы гостю.
    pending = db.execute(
        "SELECT COUNT(*) AS c FROM order_items "
        "WHERE order_id = ? AND status NOT IN ('served', 'cancelled')",
        (order_id,),
    ).fetchone()["c"]
    if pending:
        flash(
            f"Нельзя закрыть заказ: {pending} позиц. ещё не поданы. "
            "Отметьте их как «Подано» или отмените.",
            "error",
        )
        return redirect(url_for("orders.detail", order_id=order_id))

    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE orders SET status = 'paid', closed_at = datetime('now') "
            "WHERE id = ?", (order_id,),
        )
        if order["table_id"]:
            db.execute(
                "UPDATE restaurant_tables SET status = 'free' WHERE id = ?",
                (order["table_id"],),
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Заказ #{order_id} оплачен и закрыт",
               entity_type="order", entity_id=order_id)
    flash("Заказ оплачен и закрыт.", "success")
    return redirect(url_for("orders.tables"))


@orders.route("/<int:order_id>/cancel", methods=("POST",))
@roles_required("waiter")
def cancel(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?",
                       (order_id,)).fetchone()
    if not order:
        flash("Заказ не найден.", "error")
        return redirect(url_for("orders.tables"))
    if order["status"] in ("paid", "cancelled"):
        flash("Заказ уже закрыт.", "error")
        return redirect(url_for("orders.detail", order_id=order_id))
    if g.user["role"] == "waiter" and order["waiter_id"] != g.user["id"]:
        flash("Нельзя отменить чужой заказ.", "error")
        return redirect(url_for("orders.tables"))

    db.execute("BEGIN IMMEDIATE")
    try:
        # A08-1: восстанавливаем склад по тем позициям, ингредиенты
        # которых уже были списаны при отправке на кухню.
        sent_items = db.execute(
            "SELECT id, dish_id, qty FROM order_items "
            "WHERE order_id = ? AND status IN ('cooking', 'ready')",
            (order_id,),
        ).fetchall()

        for item in sent_items:
            tc_rows = db.execute(
                "SELECT ingredient_id, qty_per_portion FROM tech_cards "
                "WHERE dish_id = ?",
                (item["dish_id"],),
            ).fetchall()
            for tc in tc_rows:
                restore_qty = tc["qty_per_portion"] * item["qty"]
                db.execute(
                    "UPDATE ingredients SET stock_qty = stock_qty + ? "
                    "WHERE id = ?",
                    (restore_qty, tc["ingredient_id"]),
                )
                db.execute(
                    "INSERT INTO stock_movements "
                    "(ingredient_id, qty_change, reason, comment, user_id) "
                    "VALUES (?, ?, 'inventory', ?, ?)",
                    (
                        tc["ingredient_id"], restore_qty,
                        f"Возврат на склад по отмене заказа #{order_id}",
                        g.user["id"],
                    ),
                )

        db.execute(
            "UPDATE orders SET status = 'cancelled', "
            "closed_at = datetime('now') WHERE id = ?",
            (order_id,),
        )
        db.execute(
            "UPDATE order_items SET status = 'cancelled' "
            "WHERE order_id = ? AND status NOT IN ('served', 'cancelled')",
            (order_id,),
        )
        if order["table_id"]:
            db.execute(
                "UPDATE restaurant_tables SET status = 'free' WHERE id = ?",
                (order["table_id"],),
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    log_action(f"Заказ #{order_id} отменён", 
               entity_type="order", entity_id=order_id)
    flash("Заказ отменён.", "success")
    return redirect(url_for("orders.tables"))

@orders.route("/kitchen")
@roles_required("cook", "bartender")
def kitchen_view():
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
        """, (station,),
    ).fetchall()
    return render_template("orders/kitchen.html", items=items, station=station)