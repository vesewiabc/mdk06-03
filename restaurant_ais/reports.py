"""Подсистема финансового учёта и отчётности: выручка, продажи, склад."""
from datetime import date, timedelta

from flask import Blueprint, render_template, request

from database import get_db
from utils import roles_required

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.route("/")
@roles_required("accountant", "admin")
def index():
    db = get_db()

    date_from = request.args.get("date_from") or str(date.today() - timedelta(days=7))
    date_to = request.args.get("date_to") or str(date.today())

    revenue_row = db.execute(
        """
        SELECT COALESCE(SUM(oi.price * oi.qty), 0) AS revenue, COUNT(DISTINCT o.id) AS orders_count
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id AND oi.status != 'cancelled'
        WHERE o.status = 'paid' AND date(o.closed_at) BETWEEN date(?) AND date(?)
        """,
        (date_from, date_to),
    ).fetchone()

    top_dishes = db.execute(
        """
        SELECT d.name, SUM(oi.qty) AS qty_sold, SUM(oi.qty * oi.price) AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN dishes d ON d.id = oi.dish_id
        WHERE o.status = 'paid' AND oi.status != 'cancelled'
          AND date(o.closed_at) BETWEEN date(?) AND date(?)
        GROUP BY d.id ORDER BY revenue DESC LIMIT 10
        """,
        (date_from, date_to),
    ).fetchall()

    daily_revenue = db.execute(
        """
        SELECT date(o.closed_at) AS day, SUM(oi.qty * oi.price) AS revenue
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id AND oi.status != 'cancelled'
        WHERE o.status = 'paid' AND date(o.closed_at) BETWEEN date(?) AND date(?)
        GROUP BY day ORDER BY day
        """,
        (date_from, date_to),
    ).fetchall()

    low_stock = db.execute(
        "SELECT * FROM ingredients WHERE stock_qty <= min_qty ORDER BY name"
    ).fetchall()

    payroll = db.execute(
        "SELECT COALESCE(SUM(salary), 0) AS total FROM employees WHERE is_active = 1"
    ).fetchone()

    daily_revenue_data = [
        {"day": row["day"], "revenue": row["revenue"]} for row in daily_revenue
    ]

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
