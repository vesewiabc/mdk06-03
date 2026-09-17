"""Подсистема учёта персонала: сотрудники и график работы."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from database import get_db
from utils import roles_required, log_action

bp = Blueprint("staff", __name__, url_prefix="/staff")


@bp.route("/")
@roles_required("admin", "accountant")
def list_employees():
    db = get_db()
    rows = db.execute("SELECT * FROM employees ORDER BY full_name").fetchall()
    total_fund = sum(e["salary"] for e in rows if e["is_active"])
    return render_template("staff/list.html", employees=rows, total_fund=total_fund)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin")
def new_employee():
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        position = request.form["position"].strip()
        phone = request.form.get("phone", "").strip()
        hired_at = request.form.get("hired_at", "")
        salary = request.form.get("salary", 0, type=float)
        db = get_db()
        if not full_name or not position:
            flash("Укажите ФИО и должность.", "error")
        else:
            db.execute(
                "INSERT INTO employees (full_name, position, phone, hired_at, salary) "
                "VALUES (?, ?, ?, ?, ?)",
                (full_name, position, phone or None, hired_at or None, salary),
            )
            db.commit()
            log_action(f"Принят сотрудник «{full_name}» ({position})")
            flash("Сотрудник добавлен.", "success")
            return redirect(url_for("staff.list_employees"))
    return render_template("staff/employee_form.html")


@bp.route("/<int:employee_id>/toggle", methods=("POST",))
@roles_required("admin")
def toggle_employee(employee_id):
    """Увольнение / восстановление сотрудника."""
    db = get_db()
    db.execute(
        "UPDATE employees SET is_active = 1 - is_active WHERE id = ?", (employee_id,)
    )
    db.commit()
    log_action(f"Изменён статус занятости сотрудника #{employee_id}")
    return redirect(url_for("staff.list_employees"))


@bp.route("/schedule")
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
    return render_template("staff/schedule.html", schedule=rows, employees=employees)


@bp.route("/schedule/new", methods=("POST",))
@roles_required("admin")
def new_shift():
    db = get_db()
    employee_id = request.form.get("employee_id", type=int)
    work_date = request.form.get("work_date")
    shift_start = request.form.get("shift_start")
    shift_end = request.form.get("shift_end")
    if employee_id and work_date and shift_start and shift_end:
        db.execute(
            "INSERT INTO schedule (employee_id, work_date, shift_start, shift_end) "
            "VALUES (?, ?, ?, ?)",
            (employee_id, work_date, shift_start, shift_end),
        )
        db.commit()
        log_action(f"Добавлена смена для сотрудника #{employee_id} на {work_date}")
    return redirect(url_for("staff.schedule"))


@bp.route("/schedule/<int:shift_id>/remove", methods=("POST",))
@roles_required("admin")
def remove_shift(shift_id):
    db = get_db()
    db.execute("DELETE FROM schedule WHERE id = ?", (shift_id,))
    db.commit()
    return redirect(url_for("staff.schedule"))
