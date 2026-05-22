<div align="center">

# 📈 InvestTrack

**Персональный трекер облигационного портфеля с данными Московской Биржи**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)

Добавляй облигации → следи за P&L и купонами → получай данные с MOEX в реальном времени

</div>

---

## ✨ Возможности

| Функция | Описание |
|---|---|
| 📊 **Портфель** | Учёт активных и закрытых позиций, цена покупки, количество, брокерская комиссия |
| 📈 **P&L в реальном времени** | Нереализованная и зафиксированная прибыль по каждой бумаге |
| 💸 **Купонный календарь** | Предстоящие выплаты с суммой по каждой позиции |
| 🎯 **YTM** | Доходность к погашению (средняя по портфелю) |
| 🔎 **Скринер MOEX** | Поиск облигаций по ISIN или названию прямо из интерфейса |
| ⭐ **Вотчлист** | Список наблюдения — следи за бумагами до покупки |
| 📥 **Экспорт** | Выгрузка портфеля в Excel (CSV и XLSX) одним кликом |
| 🌓 **Тёмная тема** | Переключение с сохранением в localStorage |
| 🔔 **Email-уведомления** | Напоминание о купонных выплатах за день до даты |
| 🔄 **Автообновление цен** | APScheduler обновляет котировки каждые 15 минут |

---

## 🏗️ Стек технологий

**Backend**
- [Flask 3.1](https://flask.palletsprojects.com) — веб-фреймворк
- [SQLAlchemy 2](https://sqlalchemy.org) + [Flask-Migrate](https://flask-migrate.readthedocs.io) — ORM и миграции
- [Flask-Login](https://flask-login.readthedocs.io) — аутентификация
- [Flask-WTF](https://flask-wtf.readthedocs.io) — CSRF-защита
- [APScheduler](https://apscheduler.readthedocs.io) — фоновые задачи
- [Flask-Limiter](https://flask-limiter.readthedocs.io) — rate limiting
- [Gunicorn](https://gunicorn.org) — WSGI-сервер

**Frontend**
- [Bootstrap 5.3](https://getbootstrap.com) — UI-компоненты
- Vanilla JS (ES2020) — без тяжёлых фреймворков
- CSS-переменные — полная поддержка тёмной темы

**База данных**
- [PostgreSQL 16](https://postgresql.org) — основная БД
- SQLite — для локальной разработки

**Данные**
- [MOEX ISS API](https://iss.moex.com) — котировки, купоны, параметры бумаг

---

## 🚀 Быстрый старт

### Требования
- Python 3.10+
- PostgreSQL 16 (или SQLite для разработки)

### Установка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/Kos5o4ka/my-fintech-app.git
cd my-fintech-app

# 2. Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить переменные окружения
cp .env.example .env
# Отредактировать .env — указать DATABASE_URL и SECRET_KEY
```

### Запуск (разработка)

```bash
# Применить миграции
flask db upgrade

# Создать первого администратора (опционально)
python scripts/init_db.py

# Пересобрать минифицированные ассеты
python build_assets.py

# Запустить сервер
flask run
```

Открой [http://localhost:5000](http://localhost:5000)

### Запуск через Docker

```bash
# Скопировать и заполнить .env
cp .env.example .env

# Поднять контейнеры
docker compose up -d
```

Сервис будет доступен на порту `5000`.

---

## ⚙️ Конфигурация

Все настройки через переменные окружения в файле `.env`:

| Переменная | Описание | Пример |
|---|---|---|
| `SECRET_KEY` | Секретный ключ Flask (обязательно!) | `openssl rand -hex 32` |
| `DATABASE_URL` | URL базы данных | `postgresql://user:pass@localhost/db` |
| `REDIS_URL` | URL Redis (опционально, для кэша) | `redis://localhost:6379/0` |
| `MAIL_SERVER` | SMTP-сервер для уведомлений | `smtp.gmail.com` |
| `MAIL_PORT` | Порт SMTP | `587` |
| `MAIL_USERNAME` | Логин почты | `you@gmail.com` |
| `MAIL_PASSWORD` | Пароль / App Password | `••••••••` |
| `CORS_ORIGINS` | Разрешённые источники | `http://localhost:5000` |

---

## 📁 Структура проекта

```
my-fintech-app/
├── app.py                  # Точка входа, инициализация Flask
├── config.py               # Конфигурации (Dev / Test / Prod)
├── models.py               # SQLAlchemy-модели
├── extensions.py           # Инициализация расширений
├── moex.py                 # Интеграция с MOEX ISS API
├── blueprints/
│   ├── auth.py             # Аутентификация
│   ├── main.py             # Главная / dashboard
│   ├── portfolio.py        # Портфель, вотчлист, скринер
│   ├── profile.py          # Профиль пользователя
│   └── admin.py            # Управление пользователями
├── templates/              # Jinja2-шаблоны
├── static/
│   ├── css/                # Стили (с minified-версиями)
│   └── js/                 # Скрипты (с minified-версиями)
├── migrations/             # Alembic-миграции
├── tests/                  # Тесты
├── scripts/                # Утилиты (init_db.py)
├── build_assets.py         # Минификация CSS/JS
├── update.sh               # Скрипт обновления на сервере
├── Dockerfile
└── docker-compose.yml
```

---

## 🔒 Безопасность

- CSRF-защита на всех POST-запросах (Flask-WTF + XSRF-TOKEN cookie)
- Rate limiting на API и форме входа
- Валидация загружаемых файлов (расширение + MIME-тип)
- Security headers: `X-Frame-Options`, `Content-Security-Policy`, `X-Content-Type-Options`
- Пароли — bcrypt/scrypt через Werkzeug
- `.env` исключён из git

---

## 🧪 Тесты

```bash
# Запустить тест-сьют (36 тестов)
python -m pytest tests/ -v

# С отчётом о покрытии
python -m pytest tests/ --cov=. --cov-omit="*/.venv/*,migrations/*" --cov-report=term-missing
```

---

## 🖥️ Деплой на сервер

На сервере используется Gunicorn + systemd. Для обновления после `git push`:

```bash
bash update.sh
```

Скрипт: `git pull` → `pip install` → `flask db upgrade` → `systemctl restart`

---

## 📄 Лицензия

MIT © 2026 [Kos5o4ka](https://github.com/Kos5o4ka)
