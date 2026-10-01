# Архитектура

Описание того, **как устроен код**. В отличие от README, который отвечает
на вопрос «что делает приложение», здесь — правила, которые нельзя
нарушать при доработке, и обоснования принятых решений.

## Слои и правила зависимостей

```
       app.py (create_app)  ── композиция: config → extensions → blueprints → security
                 │
        ┌────────▼────────┐   HTTP    ┌──────────────────┐
        │   blueprints    │ ◄────────►│    templates     │
        │   (routes)      │           │  (Jinja2)        │
        └────────┬────────┘           └──────────────────┘
                 │
        ┌────────┼─────────────────────┐
        ▼        ▼                     ▼
     utils    rate_limit           security
        │        │
        └────┬───┘
             ▼
           db  ──►  SQLite
```

**Правила (обязательны к соблюдению):**

1. `blueprints/*` не выполняют SQL в шаблонах — все запросы в Python-коде.
2. Валидация ввода — на входе в handler, до работы с БД:
   `safe_int`, `safe_float`, `USERNAME_RE`, `DATE_RE`, `PHONE_RE`.
3. Бизнес-инварианты живут в одном месте: списание склада — только в
   `orders.send_to_kitchen`, восстановление — только в `orders.cancel`,
   защита последнего админа — только в `auth.toggle_user`.
4. Слои не «протекают»: `db.py` не знает про HTTP, `utils.py` не знает
   про конкретные blueprint'ы, `templates` не решают, что показывать —
   фильтрация по ролям выполняется в `dashboard.index` (server-side),
   `{% if %}` в шаблоне — только второй слой (defence in depth).
5. Секреты — только из окружения. Никаких констант в коде.

## Транзакционные границы

SQLite работает в режиме `isolation_level=None` (autocommit выключен).
Многошаговые операции обязательно оборачиваются в `BEGIN IMMEDIATE`:

| Операция | Файл | Почему транзакция |
|---|---|---|
| Открытие заказа | `orders.open_order` | INSERT + UPDATE стола — должны быть атомарны |
| Отправка на кухню | `orders.send_to_kitchen` | UPDATE позиций + списание ингредиентов + записи в `stock_movements` |
| Оплата заказа | `orders.pay` | UPDATE заказа + освобождение стола |
| Отмена заказа | `orders.cancel` | Возврат ингредиентов + статусы + освобождение стола |
| Складская операция | `warehouse.movement` | UPDATE остатка + `stock_movements` |
| Выполнение заявки | `warehouse.update_request_status` | UPDATE заявки + приход + `stock_movements` |
| Toggle пользователя | `auth.toggle_user` | Проверка «последний админ» + UPDATE |

`BEGIN IMMEDIATE` (а не `BEGIN`) — чтобы избежать гонки между воркерами:
SQLite берёт write-lock сразу, второй писатель ждёт `busy_timeout`.

## Миграции

Идемпотентные, по белому списку (`db._ALLOWED_MIGRATIONS`):

```python
_ALLOWED_MIGRATIONS = {
    "users":     {"session_version": "...", "must_change_password": "..."},
    "audit_log": {"entity_type": "TEXT", "entity_id": "INTEGER", "ip": "TEXT"},
}
```

**Почему белый список, а не автоматический diff:** SQLite не поддерживает
`ALTER TABLE ... DROP COLUMN` и сложные изменения. Миграция через
`ALTER TABLE ADD COLUMN` безопасна и не требует перезаписи таблицы.
Имена таблиц и колонок проверяются `_IDENT_RE`, чтобы исключить
инъекцию через `PRAGMA`-путь.

**Правило добавления миграции:**

1. Добавить колонку в `SCHEMA_SQL` (для новых БД).
2. Добавить её же в `_ALLOWED_MIGRATIONS` (для существующих).
3. Убедиться, что код устойчив к `NULL` в новой колонке.

## Точки расширения

**Новый раздел:** blueprint в `blueprints/`, регистрация в `app.py`,
шаблоны в `templates/<раздел>/`, ссылки в `base.html` и `index.html`
с проверкой роли.

**Новая роль:** добавить в `ROLE_LABELS` (`config.py`) + CHECK-констрейнт
в `users` + пункты меню в `base.html` + tiles в `index.html`.

**Новый rate limiter:** отдельный экземпляр `LoginRateLimiter` в
`rate_limit.py`. Не переиспользовать `login_limiter` для других целей —
иначе IP-ключи начнут «перекрывать» друг друга.

## Decision log

| Решение | Обоснование |
|---|---|
| SQLite, не PostgreSQL | Одна организация, один сервер, простой бэкап файла |
| CSRF через Flask-WTF | Проверенный механизм; TTL 1 час ограничивает окно атаки |
| PBKDF2, а не bcrypt/argon2 | Встроено в Werkzeug, нет C-зависимостей |
| Rate-limit в SQLite, не в памяти | Работает при `gunicorn -w N` и сохраняется между рестартами |
| Read-only соединение для SQL-консоли | Двойная защита: whitelist + физический запрет записи |
| Никаких JS-фреймворков | CSP `script-src 'self'`, размер проекта |
| Canvas 2D, не Chart.js | CSP-friendly, нет CDN-зависимостей |
| Декораторы `roles_required` вместо ACL-таблицы | Компактнее, роли статичны, читается в коде |