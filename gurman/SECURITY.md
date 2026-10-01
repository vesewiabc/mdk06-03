# Модель безопасности

## Границы доверия

- Клиент недоверенный. Всё, что приходит в `request.form/args`, проверяется.
- `X-Forwarded-For` доверяется только при `TRUSTED_PROXIES > 0`.
- `Host` валидируется Flask'ом при заданном `TRUSTED_HOSTS`.

## Аутентификация и сессии

- Пароль хранится как PBKDF2-SHA256, 600 000 итераций.
- `session_version` в `users` инвалидирует все сессии пользователя
  при смене пароля/отключении.
- Куки: `HttpOnly`, `SameSite=Lax`, `Secure` (в prod обязательно).
  Время жизни — 8 часов.
- `must_change_password` форсит редирект на смену пароля до любого
  другого действия.

## Rate limiting

- Логин: 5 попыток на (IP, username) за 5 мин → блок 15 мин; плюс
  20 попыток на IP за то же окно.
- Смена пароля: отдельный лимитер (5 / 5 мин, 50 на IP) — серия
  опечаток не блокирует весь офисный NAT.
- Состояние в SQLite → работает при нескольких воркерах.

## CSRF

- Flask-WTF, `WTF_CSRF_TIME_LIMIT = 3600`.
- Все POST-формы содержат `csrf_token`.
- Обработчик `CSRFError` не редиректит на внешние URL: см.
  `_safe_local_path` в `security.py`.

## SQL-инъекции

- Только параметризованные запросы. `#{}` / `%` — нигде нет.
- Имена таблиц/колонок для админ-страниц берутся из `sqlite_master`
  и валидируются `_IDENT_RE`.
- SQL-консоль:
  1. Разрешены только `SELECT`/`WITH`.
  2. Запрещены `;` и опасные ключевые слова (`insert`, `attach`, `pragma` …).
  3. Выполнение идёт в **read-only соединении** (`file:...?mode=ro` +
     `PRAGMA query_only = ON`). Даже при обходе фильтра запись невозможна.
  4. Ошибки SQL логируются на сервере, в UI отдаётся обобщённая строка.

## XSS

- Jinja2 autoescape включён по умолчанию.
- Никакого `|safe` нет.
- В JS — только `textContent`/`createElement`, никаких `innerHTML` с
  пользовательскими данными (см. `static/js/reports.js`).
- CSP: `default-src 'self'; script-src 'self'; style-src 'self'; ...`
  Inline-скрипты и `onclick=` запрещены.

## Clickjacking / MIME / Referer

- `X-Frame-Options: DENY`, `frame-ancestors 'none'`.
- `X-Content-Type-Options: nosniff`.
- `Referrer-Policy: no-referrer`.
- `Permissions-Policy` — все неиспользуемые API отключены.

## Redirects

`utils.is_safe_url` отклоняет:

- абсолютные URL (`http://`, `https://`, `javascript:`, `data:`),
- `//evil.com`,
- `\` (backslash),
- `..`-сегменты и `//` в пути,
- CR/LF/TAB (header injection),
- длину > 2000.

## Аудит

Таблица `audit_log`: user_id, action, entity_type, entity_id, ip, created_at.
Пишутся входы, отказы доступа, изменения пользователей, все финансовые и
складские операции, запросы SQL-консоли, факты блокировки rate-limit.