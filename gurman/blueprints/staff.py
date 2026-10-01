"""Персонал: сотрудники и график смен."""
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for,
)

from config import DATE_RE, PHONE_RE
from db import get_db
from utils import log_action, money, roles_required, safe_float


staff = Blueprint("staff", __name__, url_prefix="/staff")


@staff.route("/")
@roles_required("admin", "accountant")
def list_employees():
    db = get_db()
    rows = db.execute("SELECT * FROM employees ORDER BY full_name").fetchall()
    total_fund = money(sum(e["salary"] for e in rows if e["is_active"]))
    return render_template("staff/list.html", employees=rows, total_fund=total_fund)


@staff.route("/new", methods=("GET", "POST"))
@roles_required("admin")
def new_employee():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        position = (request.form.get("position") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        hired_at = request.form.get("hired_at", "")
        salary_raw = safe_float(request.form.get("salary"), min_=0, max_=10_000_000)
        db = get_db()

        if not full_name or not position:
            flash("Укажите ФИО и должность.", "error")
        elif len(full_name) > 200 or len(position) > 100:
            flash("Слишком длинное значение.", "error")
        elif salary_raw is None:
            flash("Некорректный оклад.", "error")
        elif phone and not PHONE_RE.match(phone):
            flash("Некорректный телефон.", "error")
        elif hired_at and not DATE_RE.match(hired_at):
            flash("Некорректная дата приёма.", "error")
        else:
            db.execute(
                "INSERT INTO employees (full_name, position, phone, hired_at, salary) "
                "VALUES (?, ?, ?, ?, ?)",
                (full_name, position, phone or None, hired_at or None, salary_raw),
            )
            log_action(f"Принят сотрудник «{full_name}» ({position})",
                       entity_type="employee")
            flash("Сотрудник добавлен.", "success")
            return redirect(url_for("staff.list_employees"))
    return render_template("staff/employee_form.html")


@staff.route("/<int:employee_id>/toggle", methods=("POST",))
@roles_required("admin")
def toggle_employee(employee_id):
    db = get_db()
    emp = db.execute("SELECT id FROM employees WHERE id = ?",
                     (employee_id,)).fetchone()
    if not emp:
        flash("Сотрудник не найден.", "error")
        return redirect(url_for("staff.list_employees"))
    db.execute("UPDATE employees SET is_active = 1 - is_active WHERE id = ?",
               (employee_id,))
    log_action(f"Изменён статус занятости сотрудника #{employee_id}",
               entity_type="employee", entity_id=employee_id)
    return redirect(url_for("staff.list_employees"))


@staff.route("/schedule")
@roles_required("admin", "accountant")
def schedule():
    db = get_db()
    rows = db.execute(
        """
        SELECT s.*, e.full_name, e.position
        FROM schedule s JOIN employees e ON e.id = s.employee_id
        ORDER BY s.work_date, s.shift_start
        """
    ).fetchall()
    employees = db.execute(
        "SELECT * FROM employees WHERE is_active = 1 ORDER BY full_name"
    ).fetchall()
    return render_template("staff/schedule.html",
                           schedule=rows, employees=employees)


@staff.route("/schedule/new", methods=("POST",))
@roles_required("admin")
def new_shift():
    db = get_db()
    employee_id = request.form.get("employee_id", type=int)
    work_date = request.form.get("work_date")
    shift_start = request.form.get("shift_start")
    shift_end = request.form.get("shift_end")

    if not employee_id or not work_date or not shift_start or not shift_end:
        flash("Заполните все поля.", "error")
        return redirect(url_for("staff.schedule"))
    if not DATE_RE.match(work_date):
        flash("Некорректная дата.", "error")
        return redirect(url_for("staff.schedule"))
    if shift_start >= shift_end:
        flash("Окончание должно быть позже начала.", "error")
        return redirect(url_for("staff.schedule"))

    emp = db.execute("SELECT id FROM employees WHERE id = ?",
                     (employee_id,)).fetchone()
    if not emp:
        flash("Сотрудник не найден.", "error")
        return redirect(url_for("staff.schedule"))

    overlap = db.execute(
        """SELECT id FROM schedule
           WHERE employee_id = ? AND work_date = ?
             AND NOT (shift_end <= ? OR shift_start >= ?)""",
        (employee_id, work_date, shift_start, shift_end),
    ).fetchone()
    if overlap:
        flash("У сотрудника уже есть пересекающаяся смена в этот день.", "error")
        return redirect(url_for("staff.schedule"))

    db.execute(
        "INSERT INTO schedule (employee_id, work_date, shift_start, shift_end) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, work_date, shift_start, shift_end),
    )
    log_action(f"Добавлена смена для сотрудника #{employee_id} на {work_date}",
               entity_type="employee", entity_id=employee_id)
    return redirect(url_for("staff.schedule"))


@staff.route("/schedule/<int:shift_id>/remove", methods=("POST",))
@roles_required("admin")
def remove_shift(shift_id):
    db = get_db()
    db.execute("DELETE FROM schedule WHERE id = ?", (shift_id,))
    log_action(f"Удалена смена #{shift_id}", entity_type="schedule",
               entity_id=shift_id)
    return redirect(url_for("staff.schedule"))