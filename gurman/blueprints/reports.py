"""Финансовая отчётность."""
from datetime import date, timedelta

from flask import Blueprint, render_template, request

from db import get_db
from utils import log_action, money, roles_required


reports = Blueprint("reports", __name__, url_prefix="/reports")


@reports.route("/")
@roles_required("accountant", "admin")
def index():
    db = get_db()

    date_from = request.args.get("date_from") or str(date.today() - timedelta(days=7))
    date_to = request.args.get("date_to") or str(date.today())

    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
        if d_from > d_to:
            d_from, d_to = d_to, d_from
            date_from, date_to = str(d_from), str(d_to)
    except ValueError:
        date_from = str(date.today() - timedelta(days=7))
        date_to = str(date.today())

    revenue_raw = db.execute(
        """
        SELECT COALESCE(SUM(oi.price * oi.qty), 0) AS revenue,
               COUNT(DISTINCT o.id) AS orders_count
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id AND oi.status != 'cancelled'
        WHERE o.status = 'paid' AND date(o.closed_at) BETWEEN date(?) AND date(?)
        """, (date_from, date_to),
    ).fetchone()
    revenue_row = {
        "revenue": money(revenue_raw["revenue"]),
        "orders_count": revenue_raw["orders_count"],
    }

    top_dishes = db.execute(
        """
        SELECT d.name, SUM(oi.qty) AS qty_sold, SUM(oi.qty * oi.price) AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN dishes d ON d.id = oi.dish_id
        WHERE o.status = 'paid' AND oi.status != 'cancelled'
          AND date(o.closed_at) BETWEEN date(?) AND date(?)
        GROUP BY d.id ORDER BY revenue DESC LIMIT 10
        """, (date_from, date_to),
    ).fetchall()

    daily_revenue = db.execute(
        """
        SELECT date(o.closed_at) AS day, SUM(oi.qty * oi.price) AS revenue
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id AND oi.status != 'cancelled'
        WHERE o.status = 'paid' AND date(o.closed_at) BETWEEN date(?) AND date(?)
        GROUP BY day ORDER BY day
        """, (date_from, date_to),
    ).fetchall()

    low_stock = db.execute(
        "SELECT * FROM ingredients WHERE stock_qty <= min_qty ORDER BY name"
    ).fetchall()

    payroll = db.execute(
        "SELECT COALESCE(SUM(salary), 0) AS total FROM employees WHERE is_active = 1"
    ).fetchone()
    payroll = {"total": money(payroll["total"])}

    daily_revenue_data = [
        {"day": row["day"], "revenue": money(row["revenue"])}
        for row in daily_revenue
    ]

    # FIX A09-9: логируем просмотр финансового отчёта.
    # Только когда период задан явно (нажали «Сформировать»),
    # чтобы не спамить при переходах по ссылке.
    if request.args.get("date_from") or request.args.get("date_to"):
        log_action(
            f"Отчёт за период {date_from} – {date_to}",
            entity_type="report",
        )
        
    return render_template(
        "reports/index.html",
        revenue_row=revenue_row,
        top_dishes=top_dishes,
        daily_revenue=daily_revenue_data,
        low_stock=low_stock,
        payroll=payroll,
        date_from=date_from,
        date_to=date_to,
    )