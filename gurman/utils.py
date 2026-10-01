"""Общие утилиты: пароли, безопасный парсинг, декораторы, аудит."""
import functools
import math
import re
import threading
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import unquote, urlparse

from flask import current_app, flash, g, redirect, request, url_for
from config import (
    PASSWORD_MIN, PASSWORD_MAX, _COMMON_PASSWORDS, _SEQ_SET,
)
from db import get_db
from passwords import hash_password


# ---------------------------------------------------------------
# Деньги
# ---------------------------------------------------------------
def money(x) -> float:
    """Округление до копеек. NaN/Inf → 0.0."""
    if x is None:
        return 0.0
    try:
        d = Decimal(str(x))
    except Exception:
        return 0.0
    if not d.is_finite():
        return 0.0
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------
# Безопасный парсинг
# ---------------------------------------------------------------
def safe_float(raw, *, min_=None, max_=None, default=None):
    """Безопасный float. None при ошибке/NaN/Inf/выходе за границы."""
    if raw is None:
        return default
    try:
        v = float(str(raw).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if min_ is not None and v < min_:
        return None
    if max_ is not None and v > max_:
        return None
    return v


def safe_int(raw, *, min_=None, max_=None, default=None):
    """Безопасный int. '1e5', '1.5', 'nan' — отсекается."""
    if raw is None:
        return default
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if min_ is not None and v < min_:
        return None
    if max_ is not None and v > max_:
        return None
    return v


# ---------------------------------------------------------------
# Пароли
# ---------------------------------------------------------------
def password_ok(pw: str, *, username: str = "", full_name: str = "") -> str | None:
    """Валидация пароля. Возвращает текст ошибки или None."""
    if not isinstance(pw, str):
        return "Некорректный пароль."
    if len(pw) < PASSWORD_MIN:
        return f"Пароль должен содержать минимум {PASSWORD_MIN} символов."
    if len(pw) > PASSWORD_MAX:
        return f"Пароль слишком длинный (максимум {PASSWORD_MAX})."
    if not re.search(r"[A-Za-z]", pw):
        return "Пароль должен содержать хотя бы одну букву."
    if not re.search(r"\d", pw):
        return "Пароль должен содержать хотя бы одну цифру."

    low = pw.lower()

    if low in _COMMON_PASSWORDS:
        return "Пароль слишком простой (в списке распространённых)."

    if username and username.lower() in low:
        return "Пароль не должен содержать логин."
    if full_name:
        for word in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", full_name.lower()):
            if word in low:
                return "Пароль не должен содержать имя/фамилию."

    for seq in _SEQ_SET:
        if seq in low:
            return "Пароль содержит тривиальную последовательность."

    if len(set(pw)) < 4:
        return "Пароль слишком однообразный."

    return None

# ---------------------------------------------------------------
# Dummy-хэш (защита от timing-атак)
# ---------------------------------------------------------------
_dummy_hash_cache: str | None = None
_dummy_hash_lock = threading.Lock()


def get_dummy_hash() -> str:
    global _dummy_hash_cache
    if _dummy_hash_cache is None:
        with _dummy_hash_lock:
            if _dummy_hash_cache is None:
                _dummy_hash_cache = hash_password(
                    "dummy-password-for-timing-only",
                )
    return _dummy_hash_cache


def warmup_dummy_hash() -> None:
    get_dummy_hash()


# ---------------------------------------------------------------
# Безопасные редиректы
# ---------------------------------------------------------------
def is_safe_url(target: str) -> bool:
    """
    Разрешает только относительные пути вида /path?query.

    Отклоняет:
    - абсолютные URL (со схемой/хостом),
    - protocol-relative (`//evil.com`),
    - обратные слэши (обходы нормализации в некоторых браузерах),
    - управляющие символы (в т.ч. CR/LF/TAB),
    - сегменты `..` (path traversal в редиректе),
    - двойные слэши внутри пути (`/foo//bar` — некоторые парсеры
      трактуют это как начало authority).
    """
    if not target or not isinstance(target, str):
        return False
    if len(target) > 2000:
        return False

    decoded = unquote(target)

    # Управляющие символы (включая CR/LF/TAB) — прямой путь к header injection.
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in decoded):
        return False

    # Backslash — в разных движках трактуется как "/".
    if "\\" in decoded:
        return False

    # Protocol-relative.
    if decoded.startswith("//"):
        return False

    p = urlparse(decoded)

    if p.scheme or p.netloc:
        return False

    if not p.path.startswith("/") or p.path.startswith("//"):
        return False

    # FIX: запрещаем `..`-сегменты и `//` внутри пути.
    segments = p.path.split("/")
    if ".." in segments:
        return False
    if "//" in p.path:
        return False

    return True

# ---------------------------------------------------------------
# Декораторы
# ---------------------------------------------------------------
def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.path))
            if g.user["role"] not in roles and g.user["role"] != "admin":
                log_action(
                    f"Отказ в доступе: {request.endpoint} (роль={g.user['role']})",
                    entity_type="access_denied",
                )
                flash("Недостаточно прав для выполнения этого действия.", "error")
                return redirect(url_for("index"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


# ---------------------------------------------------------------
# Аудит
# ---------------------------------------------------------------
def log_action(action, entity_type=None, entity_id=None):
    """Запись в журнал аудита. Не должна ломать основную операцию."""
    try:
        db = get_db()
        user_id = g.user["id"] if g.user else None
        ip = request.remote_addr if request else None
        db.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id, ip) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, action, entity_type, entity_id, ip),
        )
    except Exception as e:
        try:
            current_app.logger.exception("Ошибка записи в аудит: %s", e)
        except Exception:
            pass
        
def default_landing(role: str | None = None) -> str:
    """
    URL стартовой страницы после входа.

    Все роли попадают на общий дашборд (index), который сам скрывает
    разделы по роли через шаблон.

    Точка расширения: если понадобится развести landing'и по ролям,
    менять надо здесь и только здесь (см. ARCHITECTURE.md → Точки расширения).
    """
    return url_for("index")

