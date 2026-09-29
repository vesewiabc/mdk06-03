"""
Rate limiter для защиты от перебора паролей.

Состояние хранится в SQLite (общая БД приложения), поэтому лимит
работает корректно при запуске нескольких воркеров (gunicorn -w N,
uwsgi) и сохраняется между рестартами процесса.

Замечания по безопасности:
- Таблица живёт в той же БД, что и данные приложения. Размер таблиц
  ограничен окном и интервалом очистки (см. cleanup_interval).
- Все операции идемпотентны и безопасны при параллельных запросах:
  SQLite сериализует записи в режиме WAL, поэтому два воркера не
  могут «пропустить» блокировку друг друга.
"""
import threading
import time

from db import get_db


class LoginRateLimiter:
    def __init__(self, max_attempts=5, window=300, block=900,
                 ip_max_attempts=20, cleanup_interval=300):
        self.max_attempts = max_attempts
        self.ip_max_attempts = ip_max_attempts
        self.window = window
        self.block = block
        self.cleanup_interval = cleanup_interval
        self._last_cleanup = 0.0
        self._schema_ready = False
        # Лок на DDL, чтобы два потока одновременно не пытались CREATE TABLE.
        self._ddl_lock = threading.Lock()

    # ---------- ключи ----------
    def _key(self, ip, username):
        return f"u|{ip}|{(username or '').lower()}"

    def _ip_key(self, ip):
        return f"i|{ip}"

    # ---------- схема ----------
    def _ensure_schema(self, db):
        if self._schema_ready:
            return
        with self._ddl_lock:
            if self._schema_ready:
                return
            db.execute(
                "CREATE TABLE IF NOT EXISTS rate_limit_attempts ("
                "  key TEXT NOT NULL, ts REAL NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_rl_attempts_key "
                "ON rate_limit_attempts(key, ts)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS rate_limit_blocks ("
                "  key TEXT PRIMARY KEY, until REAL NOT NULL)"
            )
            self._schema_ready = True

    def _cleanup(self, db, now):
        if now - self._last_cleanup < self.cleanup_interval:
            return
        self._last_cleanup = now
        db.execute("DELETE FROM rate_limit_attempts WHERE ts < ?",
                   (now - self.window,))
        db.execute("DELETE FROM rate_limit_blocks WHERE until < ?", (now,))

    # ---------- API ----------
    def is_blocked(self, ip, username):
        now = time.time()
        db = get_db()
        self._ensure_schema(db)
        self._cleanup(db, now)
        keys = (self._key(ip, username), self._ip_key(ip))
        qmarks = ",".join("?" * len(keys))
        row = db.execute(
            f"SELECT 1 FROM rate_limit_blocks "
            f"WHERE key IN ({qmarks}) AND until > ? LIMIT 1",
            (*keys, now),
        ).fetchone()
        return row is not None

    def register_failure(self, ip, username) -> bool:
        """
        Регистрирует неудачную попытку.
        Возвращает True, если именно эта попытка привела к блокировке
        (переход из «не заблокирован» в «заблокирован»). Нужно для
        однократного логирования блокировки в audit_log.
        """
        now = time.time()
        db = get_db()
        self._ensure_schema(db)
        self._cleanup(db, now)

        just_blocked = False
        for k, limit in ((self._key(ip, username), self.max_attempts),
                         (self._ip_key(ip), self.ip_max_attempts)):
            if db.execute(
                "SELECT 1 FROM rate_limit_blocks WHERE key = ? AND until > ?",
                (k, now),
            ).fetchone():
                continue

            db.execute(
                "DELETE FROM rate_limit_attempts WHERE key = ? AND ts < ?",
                (k, now - self.window),
            )
            db.execute(
                "INSERT INTO rate_limit_attempts (key, ts) VALUES (?, ?)",
                (k, now),
            )
            cnt = db.execute(
                "SELECT COUNT(*) AS c FROM rate_limit_attempts WHERE key = ?",
                (k,),
            ).fetchone()["c"]

            if cnt >= limit:
                db.execute(
                    "INSERT INTO rate_limit_blocks (key, until) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET until = excluded.until",
                    (k, now + self.block),
                )
                db.execute("DELETE FROM rate_limit_attempts WHERE key = ?", (k,))
                just_blocked = True

        return just_blocked

    def reset(self, ip, username):
        db = get_db()
        self._ensure_schema(db)
        k = self._key(ip, username)
        db.execute("DELETE FROM rate_limit_attempts WHERE key = ?", (k,))
        db.execute("DELETE FROM rate_limit_blocks WHERE key = ?", (k,))


# FIX A06: отдельные лимитеры для логина и смены пароля.
# Раньше оба использовали один инстанс с общим IP-ключом, из-за чего
# серия опечаток при смене пароля блокировала вход с того же IP.
login_limiter = LoginRateLimiter(
    max_attempts=5,
    window=300,
    block=900,
    ip_max_attempts=20,
)

password_change_limiter = LoginRateLimiter(
    max_attempts=5,
    window=300,
    block=900,
    # Смена пароля — редкая операция; при случайной серии опечаток
    # не хотим блокировать весь IP (там может быть NAT офиса).
    ip_max_attempts=50,
)