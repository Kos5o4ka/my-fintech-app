<div align="center">

# 📈 InvestTrack

**Персональный трекер облигационного портфеля с данными Московской Биржи**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![CI](https://img.shields.io/github/actions/workflow/status/Kos5o4ka/my-fintech-app/ci.yml?style=flat-square&label=CI)](https://github.com/Kos5o4ka/my-fintech-app/actions)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)

Добавляй облигации → следи за P&L и купонами → получай данные с MOEX в реальном времени

</div>

---

## ✨ Возможности

| Функция | Описание |
|---|---|
| 📊 **Портфель** | Учёт активных/закрытых позиций, дюрация и текущие цены MOEX в реальном времени |
| 📈 **Аналитика** | Нереализованный и реализованный P&L, Sharpe Ratio, бенчмарк RGBI |
| 💸 **Купонный календарь** | Предстоящие выплаты на 60 дней вперёд, in-app уведомления |
| 🔎 **Скринер MOEX** | Фильтрация по YTM, дюрации, типу эмитента (ОФЗ / корпоративные / муниципальные) |
| ⚖️ **Сравнение облигаций** | Нормализованный price chart по двум бумагам за выбранный период |
| 🧾 **Налоговый отчёт** | НДФЛ 13% по всем реализованным сделкам (с учётом купонов проданных бумаг) |
| 📥 **Экспорт / Импорт** | Экспорт портфеля в Excel (XLSX) и CSV; импорт брокерских отчётов `.xlsx`/`.csv` с автоопределением столбцов |
| ⭐ **Вотчлист** | Список наблюдения с актуальными ценами и YTM с MOEX |
| 🔐 **2FA через Telegram** | Двухфакторная аутентификация — OTP-код в личный бот с мгновенным сгоранием при попытке |
| 🔔 **Уведомления** | Telegram-уведомления за день до купонной выплаты |
| 🌓 **Тёмная тема** | Переключение с View Transitions API (сглаженное перетекание) и сохранением в localStorage |
| 🖨️ **PDF-отчёт** | Отчёт портфеля с Sharpe и налогами через `window.print()` |
| 🍕 **Частичная продажа** | Поддержка дробного уменьшения лотов с авто-разделением сделок и пересчётом P&L |
| 📝 **Заметки к позициям** | Возможность добавлять и сохранять подробные текстовые комментарии для каждого лота |

---

## 🏗️ Стек технологий

**Backend**
- [Flask 3.1](https://flask.palletsprojects.com) + Blueprints + сервисный слой
- [SQLAlchemy 2](https://sqlalchemy.org) + [Flask-Migrate](https://flask-migrate.readthedocs.io) — ORM и Alembic-миграции
- [Pydantic v2](https://docs.pydantic.dev) — валидация входящих данных
- [Flask-Login](https://flask-login.readthedocs.io) — сессии и аутентификация
- [Flask-WTF](https://flask-wtf.readthedocs.io) — CSRF-защита
- [Flask-Limiter](https://flask-limiter.readthedocs.io) — rate limiting
- [APScheduler](https://apscheduler.readthedocs.io) — обновление цен + купонные уведомления
- [Gunicorn](https://gunicorn.org) — WSGI production сервер

**Frontend**
- [Bootstrap 5.3](https://getbootstrap.com) + CSS-переменные (design tokens)
- [Chart.js](https://chartjs.org) — P&L chart, donut, бенчмарк, сравнение
- Vanilla JS (ES2020), no framework — все скрипты минифицируются через `build_assets.py`

**Инфраструктура**
- [PostgreSQL 16](https://postgresql.org) — основная БД (SQLite для локальной разработки)
- [Redis 7](https://redis.io) — кэш цен MOEX (опционально, FileSystemCache по умолчанию)
- [Nginx 1.27](https://nginx.org) — статика, rate limit, reverse proxy
- [Docker](https://docker.com) + docker-compose — 4 сервиса: app + db + redis + nginx
- [GitHub Actions](https://github.com/features/actions) — CI: lint → test → docker smoke test

---

## 🚀 Быстрый старт

### Требования
- Python 3.10+
- PostgreSQL 16 (или SQLite для разработки)

### Локальный запуск

```bash
# 1. Клонировать репозиторий
git clone https://github.com/Kos5o4ka/my-fintech-app.git
cd my-fintech-app

# 2. Виртуальное окружение
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Зависимости
pip install -r requirements.txt

# 4. Переменные окружения
cp .env.example .env
# Открой .env и задай SECRET_KEY (обязательно)

# 5. Применить миграции и создать первого пользователя
flask db upgrade
flask shell
>>> from extensions import db
>>> from models import User
>>> from werkzeug.security import generate_password_hash
>>> db.session.add(User(username="admin", password_hash=generate_password_hash("password"), is_admin=True))
>>> db.session.commit()

# 6. Пересобрать статику
python build_assets.py

# 7. Запустить
flask run
```

Открой [http://localhost:5000](http://localhost:5000) — войди с `admin` / `password`.

### Docker (production)

```bash
cp .env.production.example .env
# Задай SECRET_KEY, DATABASE_URL и другие переменные

docker compose up -d
```

Сервис поднимает app + PostgreSQL + Redis + Nginx. Порт 80 (и 443 при наличии сертификата).

---

## ⚙️ Конфигурация

Все настройки через переменные окружения в `.env`:

| Переменная | Обязательна | Описание |
|---|---|---|
| `SECRET_KEY` | ✅ | Секрет Flask — `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | ✅ prod | `postgresql://user:pass@host/db` (SQLite по умолчанию для dev) |
| `REDIS_URL` | — | `redis://localhost:6379/0` (FileSystemCache если не задан) |
| `TELEGRAM_BOT_TOKEN` | — | Токен бота для 2FA и уведомлений |
| `TELEGRAM_BOT_USERNAME` | — | `@username` бота без `@` |
| `SENTRY_DSN` | — | DSN для Sentry error tracking |

Полный список: [`.env.production.example`](.env.production.example)

---

## 📁 Структура проекта

```
my-fintech-app/
├── app.py                   # Фабрика приложения, APScheduler, Sentry
├── config.py                # Dev / Test / Production конфиги
├── models.py                # User, BondPortfolio, WatchlistItem, AuditLog
├── extensions.py            # db, login_manager, cache, limiter, mail
├── moex.py                  # MOEX ISS API: цены, купоны, история, RGBI
├── constants.py             # Магические числа (TTL, NDFL_RATE, …)
│
├── blueprints/
│   ├── auth.py              # Вход, 2FA, смена пароля, AuditLog
│   ├── portfolio.py         # CRUD портфеля, скринер, экспорт, watchlist
│   ├── profile.py           # Профиль, Telegram, activity feed
│   ├── admin.py             # Управление пользователями
│   ├── main.py              # Лендинг, дашборд, dashboard API
│   └── telegram_bot.py      # Telegram webhook: /start, OTP
│
├── services/
│   ├── portfolio_service.py # P&L, YTM, Sharpe, Tax, купонный доход
│   ├── moex_service.py      # Кэшированный доступ к MOEX
│   ├── user_service.py      # Аватары (Pillow), telegram settings
│   └── telegram_service.py  # Bot API, OTP, deep-link
│
├── schemas/
│   ├── portfolio.py         # AddBondRequest, SellBondRequest, ScreenerRequest
│   └── auth.py              # LoginRequest, ChangePasswordRequest
│
├── templates/               # Jinja2: base, index, dashboard, portfolio, profile, admin
├── static/
│   ├── css/                 # Исходники + *.min.css (10 файлов)
│   └── js/                  # Исходники + *.min.js (10 файлов)
│
├── migrations/              # Alembic-миграции (8 ревизий)
├── tests/
│   ├── test_app.py          # 36 интеграционных тестов
│   └── test_properties.py   # 17 Hypothesis property-based тестов
│
├── bruno/                   # API коллекция Bruno (41 запрос)
│   ├── auth/                # login, verify_2fa, logout, change_password
│   ├── portfolio/           # 26 эндпоинтов: CRUD, export, screener, …
│   ├── profile/             # 6 эндпоинтов: stats, telegram, activity
│   ├── admin/               # get_users, add_user, delete_user
│   └── misc/                # health, init
│
├── docs/
│   └── architecture.md      # C4 Level 2 диаграммы (Mermaid)
│
├── nginx/
│   ├── nginx.conf           # Gzip, rate-limit zones, security
│   └── conf.d/app.conf      # Статика, proxy, HTTPS-блок
│
├── .github/workflows/ci.yml # CI: lint → test → docker smoke test
├── build_assets.py          # Минификация CSS/JS → *.min.*
├── gunicorn.conf.py         # Auto workers, timeouts, logging
├── Dockerfile               # Multi-stage build (~200 МБ меньше)
├── docker-compose.yml       # app + db + redis + nginx
├── CONTRIBUTING.md          # Гайд разработчика
├── CHANGELOG.md             # История версий
└── ROADMAP.md               # Полный план разработки
```

---

## 🔒 Безопасность

- CSRF-защита на всех POST-запросах (Flask-WTF + `XSRF-TOKEN` cookie)
- **2FA через Telegram** — OTP-код в личный бот при входе
- Rate limiting: `/api/auth/login` — 5 req/min, API — 60 req/min
- Pydantic v2 — строгая валидация всех входящих данных
- HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Permissions-Policy`
- Аватары: Pillow re-encode + strip EXIF, UUID-имена, проверка MIME
- AuditLog — полный журнал входов, 2FA, смены пароля, Telegram
- `.env` и `instance/` исключены из git

---

## 🧪 Тесты

```bash
# Запустить все тесты
python -m pytest tests/ -v

# С отчётом о покрытии
python -m pytest tests/ --cov=. --cov-report=term-missing

# Только property-based тесты
python -m pytest tests/test_properties.py -v
```

**53 теста:** 36 интеграционных + 17 Hypothesis property-based.
MOEX API мокируется через `@patch` — тесты не требуют сети.

---

## 📖 Документация

| Файл | Описание |
|---|---|
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Локальный запуск, code style, PR flow |
| [`CHANGELOG.md`](CHANGELOG.md) | История версий (Keep a Changelog) |
| [`docs/architecture.md`](docs/architecture.md) | C4 Level 2 диаграммы |
| [`bruno/`](bruno/) | Bruno API коллекция — 42 запроса |
| [`.env.production.example`](.env.production.example) | Все переменные окружения |

---

## 📄 Лицензия

MIT © 2026 [Kos5o4ka](https://github.com/Kos5o4ka)
