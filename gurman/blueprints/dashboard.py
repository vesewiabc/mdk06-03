"""Главная страница (дашборд) и глобальный контекст шаблонов.

Все данные фильтруются НА СЕРВЕРЕ по роли пользователя. Шаблонные
проверки {% if R in (...) %} остаются как второй слой (defence in depth),
но не являются единственной защитой.
"""
from flask import Blueprint, g, redirect, render_template, url_for

from config import DEMO_ACCOUNTS, ROLE_LABELS
from db import get_db
from utils import money


def index():
    if g.user is None:
        return redirect(url_for("auth.login"))

    db = get_db()
    R = g.user["role"]

    # ---------- KPI-агрегаты ----------
    stats_row = db.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM restaurant_tables) AS tables_total,
          (SELECT COUNT(*) FROM restaurant_tables WHERE status='free') AS tables_free,
          (SELECT COUNT(*) FROM restaurant_tables WHERE status='occupied') AS tables_busy,
          (SELECT COUNT(*) FROM orders WHERE date(created_at) = date('now')) AS orders_today,
          (SELECT COUNT(*) FROM orders WHERE status IN ('open','sent','served')) AS orders_open,
          (SELECT COALESCE(SUM(oi.price * oi.qty), 0)
             FROM orders o JOIN order_items oi ON oi.order_id = o.id
             WHERE o.status='paid' AND oi.status != 'cancelled'
               AND date(o.closed_at) = date('now')) AS revenue_today,
          (SELECT COALESCE(SUM(oi.price * oi.qty), 0)
             FROM orders o JOIN order_items oi ON oi.order_id = o.id
             WHERE o.status='paid' AND oi.status != 'cancelled'
               AND date(o.closed_at) >= date('now', '-6 days')) AS revenue_week,
          (SELECT COUNT(*) FROM ingredients WHERE stock_qty <= min_qty) AS low_stock_count,
          (SELECT COUNT(*) FROM employees WHERE is_active = 1) AS staff_count,
          (SELECT COALESCE(SUM(salary), 0) FROM employees WHERE is_active = 1) AS payroll_fund,
          (SELECT COUNT(*) FROM restock_requests WHERE status IN ('new','approved')) AS requests_pending
        """
    ).fetchone()
    stats = dict(stats_row) if stats_row else {}
    if stats:
        stats["revenue_today"] = money(stats.get("revenue_today"))
        stats["revenue_week"]  = money(stats.get("revenue_week"))
        stats["payroll_fund"]  = money(stats.get("payroll_fund"))

    # ---------- FIX A01: серверная фильтрация KPI ----------
    # Нерелевантные для роли финансовые поля зануляем, чтобы они не
    # утекли никаким способом (в т.ч. при ошибке в шаблоне).
    if R not in ("admin", "accountant"):
        stats["revenue_today"] = 0.0
        stats["revenue_week"]  = 0.0
        stats["payroll_fund"]  = 0.0
    if R not in ("admin", "storekeeper", "accountant"):
        stats["low_stock_count"] = 0
        stats["requests_pending"] = 0

    # ---------- Последние заказы (только admin / waiter) ----------
    recent_orders = []
    if R in ("admin", "waiter"):
        rows = db.execute(
            """SELECT o.*, t.number AS table_number,
                      COALESCE(u.full_name, '—') AS waiter_name,
                      (SELECT COALESCE(SUM(oi.qty * oi.price), 0)
                       FROM order_items oi
                       WHERE oi.order_id = o.id AND oi.status != 'cancelled') AS total
               FROM orders o
               LEFT JOIN restaurant_tables t ON t.id = o.table_id
               LEFT JOIN users u ON u.id = o.waiter_id
               ORDER BY o.created_at DESC LIMIT 8"""
        ).fetchall()
        recent_orders = [{**dict(r), "total": money(r["total"])} for r in rows]

    # ---------- Низкие остатки (admin / storekeeper / accountant) ----------
    low_stock = []
    if R in ("admin", "storekeeper", "accountant"):
        low_stock = db.execute(
            """SELECT * FROM ingredients
               WHERE stock_qty <= min_qty
               ORDER BY (stock_qty - min_qty) LIMIT 8"""
        ).fetchall()

    # ---------- Топ блюд (финансовые данные: admin / accountant) ----------
    top_dishes = []
    if R in ("admin", "accountant"):
        rows = db.execute(
            """SELECT d.name, SUM(oi.qty) AS qty_sold,
                      SUM(oi.qty * oi.price) AS revenue
               FROM order_items oi
               JOIN orders o ON o.id = oi.order_id
               JOIN dishes d ON d.id = oi.dish_id
               WHERE o.status = 'paid' AND oi.status != 'cancelled'
                 AND date(o.closed_at) >= date('now', '-6 days')
               GROUP BY d.id ORDER BY revenue DESC LIMIT 6"""
        ).fetchall()
        top_dishes = [{**dict(r), "revenue": money(r["revenue"])} for r in rows]

    # ---------- Активные позиции (admin / cook / bartender) ----------
    active_items = []
    if R in ("admin", "cook", "bartender"):
        station = "bar" if R == "bartender" else "kitchen"
        active_items = db.execute(
            """SELECT oi.*, d.name AS dish_name, o.id AS order_id,
                      t.number AS table_number
               FROM order_items oi
               JOIN dishes d ON d.id = oi.dish_id
               JOIN orders o ON o.id = oi.order_id
               LEFT JOIN restaurant_tables t ON t.id = o.table_id
               WHERE d.station = ? AND oi.status IN ('cooking','ready')
               ORDER BY oi.id LIMIT 8""", (station,),
        ).fetchall()

    return render_template(
        "index.html",
        stats=stats, recent_orders=recent_orders,
        low_stock=low_stock, top_dishes=top_dishes,
        active_items=active_items,
    )


def register_globals(app):
    @app.context_processor
    def inject_globals():
        # FIX A04: демо-учётки берутся из config.DEMO_ACCOUNTS
        # (единый источник с db._seed_demo_users). Отдаём в шаблоны
        # только когда Config.SHOW_DEMO_ACCOUNTS == True, что
        # невозможно в production (см. config.py + app.py).
        demo_accounts = None
        if app.config.get("SHOW_DEMO_ACCOUNTS"):
            demo_accounts = [
                {
                    "role": acc["role_label"],
                    "login": acc["login"],
                    "password": acc["password"],
                }
                for acc in DEMO_ACCOUNTS
            ]
        return {
            "role_labels": ROLE_LABELS,
            "restaurant_name": app.config["RESTAURANT_NAME"],
            "is_debug": app.debug,
            "demo_accounts": demo_accounts,
        }