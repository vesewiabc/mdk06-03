"""Блюда, категории, техкарты."""
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for,
)

from db import get_db
from utils import log_action, money, roles_required, safe_float


dishes = Blueprint("dishes", __name__, url_prefix="/dishes")


@dishes.route("/")
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


@dishes.route("/new", methods=("GET", "POST"))
@roles_required("cook")
def new_dish():
    db = get_db()
    categories = db.execute("SELECT * FROM categories ORDER BY name").fetchall()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        category_id = request.form.get("category_id", type=int)
        price_raw = safe_float(request.form.get("price"), min_=0.01, max_=1_000_000)
        station = request.form.get("station", "kitchen")
        description = (request.form.get("description") or "").strip()[:1000]

        if not name:
            flash("Укажите название.", "error")
        elif len(name) > 200:
            flash("Слишком длинное название.", "error")
        elif price_raw is None:
            flash("Цена должна быть в диапазоне 0.01–1 000 000.", "error")
        elif station not in ("kitchen", "bar"):
            flash("Некорректная станция.", "error")
        elif category_id and not db.execute(
                "SELECT id FROM categories WHERE id = ?", (category_id,)
        ).fetchone():
            flash("Категория не найдена.", "error")
        else:
            price = money(price_raw)
            cur = db.execute(
                "INSERT INTO dishes (name, category_id, price, station, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, category_id, price, station, description or None),
            )
            log_action(f"Добавлено блюдо «{name}»", entity_type="dish",
                       entity_id=cur.lastrowid)
            flash("Блюдо добавлено. Теперь укажите технологическую карту.", "success")
            return redirect(url_for("dishes.tech_card", dish_id=cur.lastrowid))

    return render_template("dishes/dish_form.html", categories=categories)


@dishes.route("/<int:dish_id>/toggle", methods=("POST",))
@roles_required("cook")
def toggle_dish(dish_id):
    db = get_db()
    dish = db.execute("SELECT id FROM dishes WHERE id = ?", (dish_id,)).fetchone()
    if not dish:
        flash("Блюдо не найдено.", "error")
        return redirect(url_for("dishes.list_dishes"))
    db.execute("UPDATE dishes SET is_active = 1 - is_active WHERE id = ?", (dish_id,))
    log_action(f"Изменена доступность блюда #{dish_id}", entity_type="dish",
               entity_id=dish_id)
    return redirect(url_for("dishes.list_dishes"))


@dishes.route("/<int:dish_id>/techcard", methods=("GET", "POST"))
@roles_required("cook")
def tech_card(dish_id):
    db = get_db()
    dish = db.execute("SELECT * FROM dishes WHERE id = ?", (dish_id,)).fetchone()
    if not dish:
        flash("Блюдо не найдено.", "error")
        return redirect(url_for("dishes.list_dishes"))

    if request.method == "POST":
        ingredient_id = request.form.get("ingredient_id", type=int)
        qty = safe_float(request.form.get("qty_per_portion"), min_=0.001, max_=1000)

        if not ingredient_id or qty is None:
            flash("Некорректное количество.", "error")
            return redirect(url_for("dishes.tech_card", dish_id=dish_id))
        ing = db.execute("SELECT id FROM ingredients WHERE id = ?",
                         (ingredient_id,)).fetchone()
        if not ing:
            flash("Ингредиент не найден.", "error")
            return redirect(url_for("dishes.tech_card", dish_id=dish_id))

        db.execute(
            "INSERT INTO tech_cards (dish_id, ingredient_id, qty_per_portion) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(dish_id, ingredient_id) DO UPDATE SET "
            "qty_per_portion = excluded.qty_per_portion",
            (dish_id, ingredient_id, qty),
        )
        log_action(f"Обновлена техкарта блюда #{dish_id}", entity_type="dish",
                   entity_id=dish_id)
        return redirect(url_for("dishes.tech_card", dish_id=dish_id))

    card = db.execute(
        """
        SELECT tc.*, i.name AS ingredient_name, i.unit
        FROM tech_cards tc JOIN ingredients i ON i.id = tc.ingredient_id
        WHERE tc.dish_id = ? ORDER BY i.name
        """, (dish_id,),
    ).fetchall()
    ingredients = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
    return render_template("dishes/techcard.html",
                           dish=dish, card=card, ingredients=ingredients)


@dishes.route("/techcard/<int:item_id>/remove", methods=("POST",))
@roles_required("cook")
def remove_tech_card_item(item_id):
    db = get_db()
    row = db.execute("SELECT dish_id FROM tech_cards WHERE id = ?",
                     (item_id,)).fetchone()
    if row:
        db.execute("DELETE FROM tech_cards WHERE id = ?", (item_id,))
        log_action(f"Удалён ингредиент #{item_id} из техкарты блюда #{row['dish_id']}",
                   entity_type="dish", entity_id=row["dish_id"])
        return redirect(url_for("dishes.tech_card", dish_id=row["dish_id"]))
    return redirect(url_for("dishes.list_dishes"))


@dishes.route("/categories", methods=("GET", "POST"))
@roles_required("cook")
def categories():
    db = get_db()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Укажите название категории.", "error")
        elif len(name) > 100:
            flash("Слишком длинное название.", "error")
        else:
            db.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
            log_action(f"Добавлена категория меню «{name}»", entity_type="category")
        return redirect(url_for("dishes.categories"))
    rows = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("dishes/categories.html", categories=rows)