"""
Подсистема управления блюдами и производственным учётом:
меню, категории, технологические карты (состав блюд).
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from database import get_db
from utils import roles_required, log_action

bp = Blueprint("dishes", __name__, url_prefix="/dishes")


@bp.route("/")
@roles_required("cook", "bartender", "accountant", "waiter")
def list_dishes():
    db = get_db()
    rows = db.execute(
        """
        SELECT d.*, c.name AS category_name
        FROM dishes d
        LEFT JOIN categories c ON c.id = d.category_id
        ORDER BY c.name, d.name
        """
    ).fetchall()
    return render_template("dishes/list.html", dishes=rows)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("cook")
def new_dish():
    db = get_db()
    categories = db.execute("SELECT * FROM categories ORDER BY name").fetchall()

    if request.method == "POST":
        name = request.form["name"].strip()
        category_id = request.form.get("category_id", type=int)
        price = request.form.get("price", 0, type=float)
        station = request.form.get("station", "kitchen")
        description = request.form.get("description", "").strip()

        if not name or price <= 0:
            flash("Укажите название и цену блюда.", "error")
        else:
            cur = db.execute(
                "INSERT INTO dishes (name, category_id, price, station, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, category_id, price, station, description or None),
            )
            db.commit()
            log_action(f"Добавлено блюдо «{name}»")
            flash("Блюдо добавлено. Теперь укажите технологическую карту.", "success")
            return redirect(url_for("dishes.tech_card", dish_id=cur.lastrowid))

    return render_template("dishes/dish_form.html", categories=categories)


@bp.route("/<int:dish_id>/toggle", methods=("POST",))
@roles_required("cook")
def toggle_dish(dish_id):
    db = get_db()
    db.execute("UPDATE dishes SET is_active = 1 - is_active WHERE id = ?", (dish_id,))
    db.commit()
    log_action(f"Изменена доступность блюда #{dish_id}")
    return redirect(url_for("dishes.list_dishes"))


@bp.route("/<int:dish_id>/techcard", methods=("GET", "POST"))
@roles_required("cook")
def tech_card(dish_id):
    db = get_db()
    dish = db.execute("SELECT * FROM dishes WHERE id = ?", (dish_id,)).fetchone()
    if not dish:
        flash("Блюдо не найдено.", "error")
        return redirect(url_for("dishes.list_dishes"))

    if request.method == "POST":
        ingredient_id = request.form.get("ingredient_id", type=int)
        qty = request.form.get("qty_per_portion", type=float)
        if ingredient_id and qty and qty > 0:
            db.execute(
                "INSERT INTO tech_cards (dish_id, ingredient_id, qty_per_portion) VALUES (?, ?, ?) "
                "ON CONFLICT(dish_id, ingredient_id) DO UPDATE SET qty_per_portion = excluded.qty_per_portion",
                (dish_id, ingredient_id, qty),
            )
            db.commit()
            log_action(f"Обновлена техкарта блюда #{dish_id}")
        return redirect(url_for("dishes.tech_card", dish_id=dish_id))

    card = db.execute(
        """
        SELECT tc.*, i.name AS ingredient_name, i.unit
        FROM tech_cards tc JOIN ingredients i ON i.id = tc.ingredient_id
        WHERE tc.dish_id = ? ORDER BY i.name
        """,
        (dish_id,),
    ).fetchall()
    ingredients = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
    return render_template(
        "dishes/techcard.html", dish=dish, card=card, ingredients=ingredients
    )


@bp.route("/techcard/<int:item_id>/remove", methods=("POST",))
@roles_required("cook")
def remove_tech_card_item(item_id):
    db = get_db()
    row = db.execute("SELECT dish_id FROM tech_cards WHERE id = ?", (item_id,)).fetchone()
    if row:
        db.execute("DELETE FROM tech_cards WHERE id = ?", (item_id,))
        db.commit()
        return redirect(url_for("dishes.tech_card", dish_id=row["dish_id"]))
    return redirect(url_for("dishes.list_dishes"))


@bp.route("/categories", methods=("GET", "POST"))
@roles_required("cook")
def categories():
    db = get_db()
    if request.method == "POST":
        name = request.form["name"].strip()
        if name:
            db.execute(
                "INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,)
            )
            db.commit()
            log_action(f"Добавлена категория меню «{name}»")
        return redirect(url_for("dishes.categories"))
    rows = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("dishes/categories.html", categories=rows)
