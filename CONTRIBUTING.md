# Contributing to InvestTrack

Добро пожаловать! Это руководство поможет вам быстро начать разработку.

---

## Содержание

- [Требования](#требования)
- [Локальный запуск](#локальный-запуск)
- [Переменные окружения](#переменные-окружения)
- [Структура проекта](#структура-проекта)
- [Работа со static-ресурсами](#работа-со-static-ресурсами)
- [Запуск тестов](#запуск-тестов)
- [Code Style](#code-style)
- [Pre-commit хуки](#pre-commit-хуки)
- [Pull Request Flow](#pull-request-flow)
- [Архитектурные принципы](#архитектурные-принципы)

---

## Требования

| Инструмент | Версия |
|-----------|--------|
| Python | ≥ 3.10 |
| pip | актуальная |
| Git | любая современная |
| (опционально) Docker + Compose | ≥ v2 |

---

## Локальный запуск

```bash
# 1. Клонировать репозиторий
git clone https://github.com/Kos5o4ka/my-fintech-app.git
cd my-fintech-app

# 2. Создать виртуальное окружение
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Установить зависимости
pip install -r requirements-dev.txt

# 4. Создать файл окружения
cp .env.production.example .env
# Отредактировать .env: задать SECRET_KEY, опционально TELEGRAM_BOT_TOKEN и MAIL_SERVER

# 5. Применить миграции БД (SQLite создаётся автоматически)
flask db upgrade

# 6. Запустить dev-сервер
python app.py
# → http://localhost:5000
```

### Создание тестового пользователя

Войдите на `/` и используйте форму входа. Первый пользователь создаётся вручную через
Flask shell или через панель `/admin` (если уже есть admin-аккаунт).

```bash
flask shell
>>> from models import User
>>> from extensions import db
>>> u = User(username='admin', is_admin=True)
>>> u.set_password('password123')
>>> db.session.add(u); db.session.commit()
```

### Docker (альтернатива)

```bash
echo "SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" > .env
docker compose up -d
# → http://localhost (через Nginx)
docker compose logs -f app
```

---

## Переменные окружения

Минимальный `.env` для разработки:

```dotenv
SECRET_KEY=dev-secret-change-in-production-32chars-min
FLASK_ENV=development
```

Полный список с описанием — в `.env.production.example`.

| Переменная | Обязательна | Описание |
|-----------|-------------|---------|
| `SECRET_KEY` | **да** | Секрет для подписи сессий и CSRF-токенов |
| `FLASK_ENV` | нет | `development` / `production` |
| `DATABASE_URL` | нет | PostgreSQL DSN (по умолчанию SQLite) |
| `REDIS_URL` | нет | Redis DSN для кэша (по умолчанию FileSystemCache) |
| `TELEGRAM_BOT_TOKEN` | нет | Токен бота для 2FA и уведомлений |
| `TELEGRAM_BOT_USERNAME` | нет | Username бота без @ |
| `SENTRY_DSN` | нет | DSN для Sentry error tracking |

---

## Структура проекта

```
my-fintech-app/
├── app.py                      # Точка входа, create_app(), APScheduler jobs
├── config.py                   # Dev / Test / Prod конфиги через классы
├── constants.py                # Все магические числа (NDFL_RATE, TTLs и т.д.)
├── extensions.py               # db, login_manager, cache, limiter, mail
├── models.py                   # SQLAlchemy ORM: User, BondPortfolio, WatchlistItem, AuditLog
├── moex.py                     # Прямой доступ к MOEX ISS API + circuit breaker
├── build_assets.py             # Минификация CSS/JS → .min.*
│
├── blueprints/
│   ├── auth.py                 # /api/auth/*
│   ├── portfolio.py            # /api/portfolio/*, /portfolio/*
│   ├── profile.py              # /api/profile/*, /profile/*
│   ├── main.py                 # /, /dashboard, /api/init, /api/portfolio/chart_data
│   ├── admin.py                # /admin, /api/admin/*
│   └── telegram_bot.py         # /api/telegram/webhook
│
├── services/
│   ├── portfolio_service.py    # Бизнес-логика: P&L, YTM, Sharpe, налоги, купоны
│   ├── moex_service.py         # Кэшированный доступ к MOEX
│   ├── user_service.py         # Аватары, telegram-настройки
│   └── telegram_service.py     # OTP, привязка, deep-link
│
├── schemas/
│   ├── portfolio.py            # AddBondRequest, SellBondRequest, ScreenerRequest
│   └── auth.py                 # LoginRequest, ChangePasswordRequest
│
├── templates/                  # Jinja2 HTML-шаблоны (без inline CSS/JS!)
│   ├── base.html               # Авторизованный лейаут (sidebar, bell, theme)
│   ├── base_public.html        # Публичный лейаут (лендинг)
│   ├── index.html              # Лендинг + форма входа
│   ├── dashboard.html          # Дашборд
│   ├── portfolio.html          # Управление портфелем
│   ├── profile.html            # Профиль пользователя
│   ├── admin.html              # Панель администратора
│   └── pdf_report.html         # Печатный PDF-отчёт
│
├── static/
│   ├── css/
│   │   ├── variables.css       # Design tokens (цвета, радиусы, тени, анимации)
│   │   ├── animations.css      # Глобальные keyframes
│   │   ├── sidebar.css         # Навигация sidebar + mobile bottom bar
│   │   ├── portfolio.css       # Переиспользуемые компоненты (metric-card, skeleton…)
│   │   ├── base.css            # Стили авторизованного лейаута
│   │   ├── dashboard.css       # Стили страницы дашборда
│   │   ├── profile.css         # Стили страницы профиля
│   │   ├── landing.css         # Стили лендинговой страницы
│   │   └── portfolio-page.css  # Стили страницы управления портфелем
│   │
│   └── js/
│       ├── common.js           # window.Common: toast, modal, csrfFetch, countUp, theme
│       ├── sidebar.js          # Collapsed sidebar, bottom bar, tooltips
│       ├── portfolio.js        # Логика таблицы портфеля, drawer, sell modal, screener
│       ├── base.js             # Page transitions, bell dropdown, form shake
│       ├── dashboard.js        # P&L chart, donut chart, loadDashboard()
│       ├── profile.js          # Tabs, Telegram, activity feed
│       ├── landing.js          # Login form, 2FA form, visit counter
│       ├── portfolio-page.js   # Compare, benchmark, tax, Sharpe, note drawer
│       └── admin.js            # Users list, create/delete user
│
├── migrations/                 # Alembic миграции
├── tests/
│   ├── test_app.py             # 36 интеграционных тестов
│   └── test_properties.py      # 17 Hypothesis property-based тестов
│
├── nginx/                      # Nginx конфиги (для Docker)
├── bruno/                      # Bruno REST-клиент коллекция (API requests)
├── docs/
│   └── architecture.md         # C4 Level 2 диаграмма архитектуры
│
├── docker-compose.yml
├── Dockerfile
├── gunicorn.conf.py
├── requirements.txt
├── requirements-dev.txt
├── setup.cfg                   # pytest + coverage конфиг
├── .pre-commit-config.yaml
└── .env.production.example
```

---

## Работа со static-ресурсами

**Правило:** HTML-шаблоны не содержат inline `<style>` и `<script>`. Весь CSS и JS — в `static/`.

После любых изменений в `static/css/*.css` или `static/js/*.js` нужно перегенерировать минифицированные файлы:

```bash
python build_assets.py
```

Это создаст/обновит соответствующие `*.min.css` и `*.min.js` файлы.

> **Важно:** коммитить нужно и исходные файлы (`*.css`, `*.js`), и минифицированные (`*.min.*`).

---

## Запуск тестов

```bash
# Все тесты + отчёт покрытия
python -m pytest tests/ -q --tb=short

# Только интеграционные
python -m pytest tests/test_app.py -v

# Только property-based
python -m pytest tests/test_properties.py -v

# С HTML-отчётом покрытия
python -m pytest tests/ --cov=. --cov-report=html
open htmlcov/index.html
```

---

## Code Style

Проект использует **ruff** для линтинга и форматирования, **bandit** для security-проверок.

```bash
# Проверить стиль
ruff check .

# Авто-fix
ruff check --fix .

# Форматирование
ruff format .

# Security scan
bandit -r . -ll --exclude tests/
```

Конфигурация ruff — в `pyproject.toml` или `setup.cfg`. Основные правила:
- Максимальная длина строки: **120 символов**
- Кавычки: **одинарные** (`'...'`)
- Импорты: сортируются автоматически

---

## Pre-commit хуки

```bash
# Установить хуки (однократно)
pre-commit install

# Запустить на всех файлах вручную
pre-commit run --all-files
```

Хуки запускаются автоматически перед каждым `git commit`:
- `ruff` — линтинг с авто-фиксом
- `ruff-format` — форматирование
- `bandit` — поиск уязвимостей (`-ll`, исключая тесты)
- `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`
- `check-added-large-files` (лимит 500 КБ)
- `debug-statements` — запрет `print()` / `breakpoint()` в коммитах

---

## Pull Request Flow

1. **Создать ветку** от `main`:
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feat/my-feature
   ```

2. **Написать код**, соблюдая архитектурные принципы ниже.

3. **Обновить static** если трогали CSS/JS:
   ```bash
   python build_assets.py
   git add static/css/*.css static/css/*.min.css static/js/*.js static/js/*.min.js
   ```

4. **Запустить тесты:**
   ```bash
   python -m pytest tests/ -q --tb=short
   ```

5. **Создать миграцию** если изменились модели:
   ```bash
   flask db migrate -m "describe the change"
   flask db upgrade
   git add migrations/
   ```

6. **Проверить pre-commit:**
   ```bash
   pre-commit run --all-files
   ```

7. **Создать Pull Request** на `update-fr`, описав:
   - Что изменилось и зачем
   - Как проверить (шаги воспроизведения)
   - Связанные issues / задачи

---

## Архитектурные принципы

### Разделение ответственности

```
HTTP (Blueprint) → Validation (Pydantic Schema) → Business Logic (Service) → Data (Model / moex.py)
```

- **Blueprints** — только парсинг запроса, вызов сервиса, возврат JSON/HTML. Никакой логики.
- **Services** — вся бизнес-логика. Нет Flask-контекста, нет `request`. Можно тестировать без HTTP.
- **Models** — только схема данных. Нет бизнес-логики.
- **Schemas** — Pydantic v2 для валидации входящих данных. `model_validate()` бросает `ValidationError`.

### Работа с MOEX API

- Всегда через `services/moex_service.py` (кэш) или `moex.py` (прямой запрос).
- `moex.py` имеет circuit breaker: 5 ошибок подряд → пауза 10 мин. Не обходить!
- Данные кэшируются 5 мин (`BOND_CACHE_TTL`). При изменении портфеля вызывать `_bust_user_cache(user_id)`.

### Шаблоны

- **Никакого inline CSS и JS** в HTML-файлах. Всё — в `static/`.
- Исключение: `pdf_report.html` (standalone print-шаблон, нет base.html).
- Исключение: anti-FOUC script в `<head>` базового шаблона (должен выполниться до рендера).
- Jinja2-переменные передаются в JS через `data-*` атрибуты (например, `body.data-user-id`), не через `{{ }}` в `.js`-файлах.

### Безопасность

- Все POST/PATCH/DELETE запросы идут через `window.Common.csrfFetch()` (CSRF-токен из cookie).
- Пароли хешируются через `werkzeug.generate_password_hash` (pbkdf2:sha256).
- Аватары: ре-кодируются через Pillow (RGB JPEG, max 400×400), EXIF удаляется, имя — UUID.
- XSS: все пользовательские данные в JS-шаблонах экранируются через `window.Common.escapeHtml()`.
