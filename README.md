# 🍽 АИС ресторана «Гурман»

**Автоматизированная информационная система управления рестораном**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.0-green.svg)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/sqlite-3-lightgrey.svg)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](#-лицензия)

[Возможности](#-возможности) •
[Быстрый старт](#-быстрый-старт) •
[Роли](#-роли-и-доступы) •
[Архитектура](#-архитектура) •
[Безопасность](#-безопасность) •
[Развёртывание](#-развёртывание)

---

## 📖 О проекте

**АИС «Гурман»** — self-hosted веб-приложение для управления рестораном.
Закрывает полный операционный цикл: от приёма заказа официантом до списания
ингредиентов со склада, ведения техкарт, графика смен персонала и
финансовой отчётности.

Одна организация, свой сервер, простой стек (Flask + SQLite), работа
в браузере без внешних зависимостей и CDN — CSP-friendly.

---

## ✨ Возможности

### 🍽 Заказы и зал
- Схема зала (12 столов), автообновление статусов
- Открытие заказа на столе, добавление блюд с поиском
- Отправка на кухню/бар с **автоматическим списанием ингредиентов** по техкартам
- Контроль остатков перед отправкой (нельзя отправить, если ингредиентов не хватает)
- Статусы позиций: `new → cooking → ready → served`
- Оплата и закрытие заказа, отмена с возвратом ингредиентов на склад
- Официант видит и редактирует **только свои** заказы

### 👨‍🍳 Кухня и бар
- Отдельные экраны для повара и бармена (фильтрация по станции)
- Автообновление каждые 15 секунд
- Переключение позиции в статус «Готово» одним кликом

### 📖 Меню и техкарты
- Категории блюд, цены, станция приготовления (кухня / бар)
- Скрытие/показ блюда без удаления
- **Технологические карты**: состав на 1 порцию по ингредиентам
- Автоматическое списание склада при отправке заказа

### 📦 Склад
- Остатки ингредиентов, минимальный порог
- Операции: приход, списание, инвентаризация (с обязательным обоснованием)
- Журнал движений (последние 200 операций)
- Подсветка позиций ниже минимума
- **Заявки на пополнение**: от создания кладовщиком до выполнения с автоматическим приходом на склад

### 👥 Персонал
- Список сотрудников, оклады, ФОТ (фонд оплаты труда)
- Приём/увольнение (toggle), защита от потери данных
- **График смен** с проверкой пересечений по времени

### 📊 Отчётность
- Выручка за период, средний чек, количество заказов
- Топ блюд по выручке
- **Диаграммы на Canvas 2D** (без сторонних библиотек):
  - Круговая (топ блюд) с интерактивной легендой
  - Столбчатая (выручка по дням)
- Товары ниже минимума
- Произвольный период (date-from / date-to)

### 🔐 Администрирование
- Управление пользователями и ролями
- **Журнал аудита** (все действия с IP-адресом)
- **SQL-консоль** — только `SELECT`/`WITH`, read-only соединение
- Просмотр таблиц БД с пагинацией

### 🎨 Интерфейс
- Тёмно-синий сайдбар, холодная голубая палитра
- CSS-переменные (единый источник правды)
- Адаптивная вёрстка (мобильное меню-бургер)
- Тосты вместо flash-сообщений
- Живые часы в топбаре
- Скелетон-лоадер на кнопках при отправке форм
- Отдельная тема для страницы входа

---

## 🚀 Быстрый старт

### Требования

- Python **3.10+**
- pip

### Установка

```bash
# 1. Клонирование
git clone <repo-url> gurman
cd gurman

# 2. Виртуальное окружение
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate

# 3. Зависимости
pip install flask flask-wtf werkzeug

# 4. SECRET_KEY (обязательно)
python -c "import secrets; print(secrets.token_hex(32))"
# → положить в переменную окружения SECRET_KEY

# 5. Запуск
python app.py
```

Приложение откроется на **http://127.0.0.1:5067**

При первом запуске автоматически создаётся `restaurant.db`, применяется
схема и выполняется сидирование справочников (столы, категории,
ингредиенты, блюда, техкарты).

### Демо-доступы

Включаются переменной `SHOW_DEMO_ACCOUNTS=1` (в production запрещено):

| Логин | Пароль | Роль |
|---|---|---|
| `admin` | `admin123456` | Администратор |
| `waiter1` | `waiter12345` | Официант |
| `cook1` | `cook123456` | Повар |
| `bartender1` | `bar1234567` | Бармен |
| `storekeeper1` | `store123456` | Кладовщик |
| `accountant1` | `acc1234567` | Бухгалтер |

Если `SHOW_DEMO_ACCOUNTS` не задан — создаётся **единственный администратор**
со случайным паролем. Пароль записывается в
`instance/admin_bootstrap_password.txt` с правами `0600`. Смените пароль
при первом входе и удалите файл.

---

## 👥 Роли и доступы

| Роль | Разделы |
|---|---|
| `admin` | Всё, включая пользователей, аудит и SQL-консоль |
| `waiter` | Столы и заказы, меню (просмотр) |
| `cook` | Кухня, меню и техкарты, категории |
| `bartender` | Бар, меню (просмотр) |
| `storekeeper` | Склад, заявки на пополнение |
| `accountant` | Отчётность, персонал, график, склад (просмотр) |

Администратор имеет доступ ко всем разделам независимо от роли.

---

## 🏗 Архитектура

```
app.py                      Фабрика приложения + строгие проверки ENV
  ↓
blueprints/                 8 blueprint'ов (auth, orders, warehouse,
                            dishes, staff, reports, admin, dashboard)
  ↓
db.py                       SQLite: get_db(), схема, миграции, seed
  ↓
utils.py                    Безопасный парсинг, пароли, аудит, декораторы
security.py                 Заголовки безопасности + обработчики ошибок
rate_limit.py               Rate limiter (SQLite, общий для воркеров)
```

### Backend (Python)

| Файл | Назначение |
|---|---|
| `app.py` | Фабрика, регистрация blueprint'ов, проверки production |
| `config.py` | Конфигурация из ENV, роли, регулярки, политика паролей |
| `db.py` | Соединение, схема (13 таблиц), миграции, seed, CLI-команды |
| `utils.py` | `safe_float`, `safe_int`, `password_ok`, `is_safe_url`, `log_action`, декораторы `login_required` / `roles_required` |
| `security.py` | CSP, HSTS, X-Frame-Options, обработчики 404/405/413/500/CSRF |
| `rate_limit.py` | SQLite-хранилище попыток входа, блокировка по IP и по (IP, username) |
| `extensions.py` | Общие расширения (CSRFProtect) |

### Blueprints

| Blueprint | URL-префикс | Модуль |
|---|---|---|
| `auth` | `/auth` | Вход, пользователи, аудит, смена пароля |
| `orders` | `/orders` | Столы, заказы, кухня/бар |
| `dishes` | `/dishes` | Меню, категории, техкарты |
| `warehouse` | `/warehouse` | Склад, движения, заявки |
| `staff` | `/staff` | Сотрудники, график смен |
| `reports` | `/reports` | Финансовая отчётность |
| `admin` | `/admin` | Просмотр БД, SQL-консоль |
| `dashboard` | `/` | Главная панель + context_processor |

### Frontend (JS / CSS)

- **Шаблоны:** Jinja2, наследование через `base.html`, отдельный
  `auth/login.html` без сайдбара
- **JS:** 5 модулей, без фреймворков
  - `main.js` — тосты, мобильное меню, часы, индикатор загрузки, автообновление
  - `login.js` — подстановка демо-данных
  - `orders.js` — поиск блюд, валидация qty
  - `reports.js` — Canvas-диаграммы, тултипы, легенда
  - `warehouse.js` — подсветка низких остатков
- **CSS:** 3 файла
  - `variables.css` — токены дизайна (единственный источник правды)
  - `style.css` — основная тема
  - `login.css` — отдельная тема страницы входа

### База данных (SQLite)

13 таблиц: `users`, `restaurant_tables`, `categories`, `dishes`,
`ingredients`, `tech_cards`, `orders`, `order_items`, `stock_movements`,
`restock_requests`, `employees`, `schedule`, `audit_log`.

Все внешние ключи включены (`PRAGMA foreign_keys = ON`), режим WAL,
`busy_timeout = 5000`. Есть идемпотентные миграции по белому списку.

---

## 🔒 Безопасность

- **Пароли:** PBKDF2-SHA256, 600 000 итераций
- **Политика паролей:** минимум 12 символов, буква + цифра, отсев
  распространённых, проверка на логин/ФИО, проверка тривиальных
  последовательностей (`abcdef`, `123456`)
- **CSRF:** `Flask-WTF`, время жизни токена — 1 час
- **Rate limiting:** 5 попыток / 5 минут на (IP + username),
  20 попыток на IP. Состояние в SQLite → работает при нескольких
  воркерах gunicorn/uwsgi
- **Timing-attack защита:** при несуществующем логине проверяется
  «dummy hash», время ответа не отличается
- **Session version:** смена пароля / отключение пользователя инвалидирует
  все активные сессии (через `session_version`)
- **Заголовки:** CSP, HSTS (при HTTPS), X-Frame-Options: DENY,
  X-Content-Type-Options, Referrer-Policy, Permissions-Policy,
  Cross-Origin-Opener-Policy, Cross-Origin-Resource-Policy
- **Open redirect:** `is_safe_url()` разрешает только относительные пути,
  блокирует `//evil.com`, `\\`, `..`, `//` внутри, управляющие символы
- **SQL-консоль:** отдельное read-only соединение (`mode=ro` +
  `PRAGMA query_only = ON`) — даже при обходе blacklist'а БД изменить нельзя
- **Проверки production:** приложение не стартует, если
  `SESSION_COOKIE_SECURE=0`, `SHOW_DEMO_ACCOUNTS=1`, `DEBUG=1`
  или `SECRET_KEY` короткий/слабый

---

## ⚙️ Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `SECRET_KEY` | генерируется в dev | Обязательно в production, ≥32 символа |
| `ENVIRONMENT` | — | `production` включает строгие проверки |
| `DEBUG` | `0` | `1` — режим отладки Flask |
| `SESSION_COOKIE_SECURE` | `0` | `1` — только HTTPS, включает HSTS |
| `TRUSTED_PROXIES` | `0` | Количество доверенных прокси (X-Forwarded-For) |
| `TRUSTED_HOSTS` | — | Список через запятую (Flask 3.1+) |
| `SHOW_DEMO_ACCOUNTS` | `0` | Показ демо-учёток на странице входа |

---

## 🖥 Развёртывание

### Gunicorn + Nginx

```bash
# Основное приложение
gunicorn -w 2 --bind 127.0.0.1:5067 'app:app'
```

```nginx
server {
    listen 443 ssl http2;
    server_name gurman.example.com;

    client_max_body_size 2M;

    location / {
        proxy_pass http://127.0.0.1:5067;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /var/www/gurman/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

### Обязательно в production

- [ ] `SECRET_KEY` — задать явно (иначе сессии сбрасываются при рестарте)
- [ ] `ENVIRONMENT=production`
- [ ] `SESSION_COOKIE_SECURE=1` + HTTPS
- [ ] `TRUSTED_PROXIES=1` при работе за nginx (иначе rate limiter и
      аудит будут видеть IP прокси, а не клиента)
- [ ] `TRUSTED_HOSTS=gurman.example.com`
- [ ] `SHOW_DEMO_ACCOUNTS` — не задавать / `0`
- [ ] `DEBUG=0`
- [ ] Регулярный бэкап файла `restaurant.db`

### CLI-команды

```bash
flask --app app init-db        # пересоздать БД (спросит подтверждение)
flask --app app init-db --yes  # без подтверждения
flask --app app seed-db        # заполнить демо-данными
```

---

## 📁 Структура проекта

```
gurman/
├── app.py                     # Фабрика приложения
├── config.py                  # Конфигурация и константы
├── db.py                      # SQLite, схема, миграции, seed
├── extensions.py              # CSRFProtect и др.
├── security.py                # Headers + error handlers
├── rate_limit.py              # Rate limiter (SQLite)
├── utils.py                   # Утилиты, декораторы, аудит
│
├── blueprints/
│   ├── __init__.py
│   ├── auth.py
│   ├── orders.py
│   ├── dishes.py
│   ├── warehouse.py
│   ├── staff.py
│   ├── reports.py
│   ├── admin.py
│   └── dashboard.py
│
├── templates/
│   ├── base.html
│   ├── 404.html / 500.html / error.html
│   ├── index.html             # Дашборд
│   ├── auth/
│   │   ├── login.html
│   │   ├── users.html
│   │   ├── user_form.html
│   │   ├── audit_log.html
│   │   └── change_password.html
│   ├── orders/
│   │   ├── tables.html
│   │   ├── order_detail.html
│   │   └── kitchen.html
│   ├── dishes/
│   │   ├── list.html
│   │   ├── dish_form.html
│   │   ├── techcard.html
│   │   └── categories.html
│   ├── warehouse/
│   │   ├── stock.html
│   │   ├── ingredient_form.html
│   │   ├── movements.html
│   │   └── requests.html
│   ├── staff/
│   │   ├── list.html
│   │   ├── employee_form.html
│   │   └── schedule.html
│   ├── reports/
│   │   └── index.html
│   └── admin/
│       ├── db_tables.html
│       ├── db_view.html
│       └── db_query.html
│
├── static/
│   ├── css/
│   │   ├── variables.css      # Токены дизайна
│   │   ├── style.css          # Основная тема
│   │   └── login.css          # Тема страницы входа
│   └── js/
│       ├── main.js            # Тосты, меню, часы, автообновление
│       ├── login.js           # Подстановка демо-данных
│       ├── orders.js          # Поиск блюд, валидация
│       ├── reports.js         # Canvas-диаграммы
│       └── warehouse.js       # Подсветка низких остатков
│
├── instance/                  # Инстанс-специфичные файлы (bootstrap-пароль)
├── restaurant.db              # SQLite (создаётся автоматически)
└── README.md
```

---

## ⌨️ UX-детали

- **Тосты** — flash-сообщения автоматически превращаются во всплывающие
  уведомления (`window.showToast` доступна из консоли)
- **Мобильное меню** — сайдбар выезжает по бургеру, закрывается по Esc,
  клику вне, или при переходе на десктопную ширину
- **Автообновление** — задаётся атрибутом `data-autorefresh="15"` на `<body>`;
  не срабатывает, если фокус в поле ввода или вкладка неактивна
- **Лоадер форм** — при submit кнопка переходит в `.is-loading` и
  блокируется на 8 секунд (страховка от зависших запросов)
- **Подтверждения** — `data-confirm="Текст?"` на форме
- **Живые часы** — в топбаре, обновляются раз в 20 секунд

---

## 📄 Лицензия

Внутренний проект. Все права защищены. © 2026
