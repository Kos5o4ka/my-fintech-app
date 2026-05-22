# Production Readiness Roadmap

Полный список улучшений для вывода проекта на уровень production-продукта, пригодного для публичной презентации. Сгруппировано по направлениям, приоритизировано по спринтам.

---

## 1. Рефакторинг

### 1.1 Типизация и структура кода

- [ ] Добавить Python type hints во все функции (`blueprints/`, `moex.py`, `models.py`)
- [ ] Создать `schemas/` с Pydantic/marshmallow схемами для валидации входящих запросов вместо ручных проверок в каждом роуте
- [ ] Вынести константы (лимиты, TTL кэша, разрешённые расширения) в `constants.py`
- [ ] Заменить все `print()` в `moex.py` на `logging.getLogger(__name__)`

### 1.2 Слой сервисов

- [ ] Создать `services/` директорию:
  - `portfolio_service.py` — бизнес-логика P&L, расчёты доходности
  - `moex_service.py` — всё взаимодействие с MOEX ISS API
  - `user_service.py` — создание/удаление/управление пользователями
- [ ] Вынести бизнес-логику из `blueprints/portfolio.py` (сейчас 400+ строк смешанного кода)
- [ ] Blueprints должны содержать только HTTP-слой: парсинг запроса → вызов сервиса → ответ

### 1.3 База данных

- [ ] Переключиться на Alembic-миграции вместо `db.create_all()` (`flask-migrate` уже установлен, но не используется)
- [ ] Добавить `updated_at` (timestamp) в `BondPortfolio`
- [ ] Добавить поле `currency` в `BondPortfolio` (RUB/USD/EUR) для поддержки валютных облигаций
- [ ] Добавить модель `Transaction` для хранения детальной истории покупок/продаж частей позиций
- [ ] Добавить индекс на `BondPortfolio.isin`

### 1.4 Конфигурация

- [ ] Разделить `config.py` на `DevelopmentConfig`, `TestingConfig`, `ProductionConfig`
- [ ] Добавить валидацию обязательных переменных окружения при старте (если `SECRET_KEY` не задан — падать, не стартовать)
- [ ] Убрать fallback `'change-me-before-production'` для `SECRET_KEY`
- [ ] Добавить `.env.production.example` с production-специфичными переменными

---

## 2. Оптимизация

### 2.1 База данных

- [ ] Добавить пагинацию в `/api/portfolio` и `/api/portfolio/history` (параметры `page`, `per_page`)
- [ ] Заменить цикл N отдельных UPDATE в APScheduler на `db.session.bulk_update_mappings()` (1 запрос вместо N)
- [ ] Добавить connection pooling в `config.py`: `SQLALCHEMY_POOL_SIZE`, `SQLALCHEMY_MAX_OVERFLOW`, `SQLALCHEMY_POOL_TIMEOUT`
- [ ] Добавить `db.session.expire_on_commit = False` где нужно избежать lazy load после commit

### 2.2 Кэширование

- [ ] Переключиться с `SimpleCache` на Redis (shared cache между воркерами Gunicorn)
- [ ] Кэшировать `/api/portfolio_stats` (пересчёт ежесекундно не нужен — TTL 5 минут достаточно)
- [ ] Добавить `ETag` + `Cache-Control` заголовки для read-only API ответов
- [ ] Инвалидировать кэш портфеля при добавлении/продаже облигации

### 2.3 Внешний API (MOEX)

- [ ] Добавить retry-логику с exponential backoff через `tenacity` (3 попытки, backoff 1/2/4 сек)
- [ ] Добавить явный `timeout` на все `requests.get()` вызовы (сейчас может зависнуть навсегда)
- [ ] Ограничить параллельные исходящие запросы к MOEX в APScheduler через `asyncio.Semaphore` или очередь
- [ ] Добавить circuit breaker: если MOEX API недоступен N раз подряд — прекратить попытки на T минут

### 2.4 Frontend

- [ ] Добавить debounce 300ms для поиска облигаций (сейчас может спамить `/api/search_bond` на каждый символ)
- [ ] Lazy-load Chart.js только при открытии модального окна с графиком
- [ ] Использовать `IntersectionObserver` для подгрузки истории торгов по скроллу
- [ ] Перенести Bootstrap/Chart.js на локальные копии или bundle (убрать CDN из CSP)
- [ ] Добавить `rel="preload"` для критических шрифтов и стилей

---

## 3. Безопасность

### 3.1 Аутентификация

- [ ] Добавить 2FA через TOTP (`pyotp` + Google Authenticator) — критично для финансового приложения
- [ ] Добавить audit log таблицу: каждый вход/выход/смена пароля записывается с IP, user-agent и timestamp

### 3.2 Сессии

- [ ] Установить `PERMANENT_SESSION_LIFETIME` (сейчас сессии не истекают)
- [ ] Реализовать ротацию session ID после логина (защита от session fixation)
- [ ] Добавить idle timeout: автоматический logout после N минут неактивности

### 3.3 HTTP-заголовки

- [ ] Добавить `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HSTS)
- [ ] Добавить `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- [ ] Убрать `Server: Werkzeug/...` / `Server: gunicorn` заголовок (утечка версий)
- [ ] Ужесточить CSP: убрать CDN из `script-src`, перейти на `nonce` или `hash`

### 3.4 Файлы и загрузки

- [ ] Хранить аватары вне `static/` — отдавать через роут с `@login_required` (сейчас доступны по прямому URL)
- [ ] Пропускать загружаемые изображения через `Pillow` (`Image.open().save()`) — ре-энкодинг убивает embedded payloads
- [ ] Rate limit на загрузку файлов: максимум 5 загрузок в час на пользователя
- [ ] Хранить аватары с непредсказуемыми именами (UUID, не `user_1_photo.jpg`)

---

## 4. UX / UI

### 4.1 Навигация и страницы

- [ ] Добавить страницу `/dashboard` — главный экран после логина:
  - Общая стоимость портфеля
  - Доходность (день/месяц/всё время)
  - Ближайшие купоны (список на 30 дней)
  - Карточка "Лучшая и худшая позиция"
- [ ] Вынести admin-панель на отдельный роут `/admin` с отдельным шаблоном
- [ ] Добавить боковое меню / navbar с навигацией (Dashboard / Portfolio / Profile / Admin)
- [ ] Добавить хлебные крошки на всех страницах кроме главной

### 4.2 Таблицы и данные

- [ ] Серверная сортировка (параметр `sort=field&order=asc|desc` в API)
- [ ] Фильтрация истории торгов по дате (date picker from/to)
- [ ] Поиск/фильтр по названию внутри активного портфеля
- [ ] Skeleton screens при загрузке данных (вместо пустой таблицы)
- [ ] Empty state с CTA при пустом портфеле ("Добавьте первую облигацию")

### 4.3 Форма добавления облигации

- [ ] Live-preview данных облигации при вводе ISIN: название, эмитент, купон %, дата погашения
- [ ] Автозаполнение `buy_price` текущей рыночной ценой (с возможностью изменить)
- [ ] Предупреждение при добавлении дублирующегося ISIN в портфель
- [ ] Показывать YTM и следующий купон в превью перед добавлением

### 4.4 Аналитика портфеля

- [ ] Средневзвешенный YTM по всему портфелю
- [ ] Виджет купонного дохода: сколько рублей придёт в следующие 30/90/365 дней
- [ ] Круговая диаграмма: распределение по эмитентам и секторам
- [ ] Бенчмарк: доходность портфеля vs индекс RGBI (Московская биржа)
- [ ] Sharpe Ratio и стандартное отклонение доходности (для продвинутых пользователей)

### 4.5 Адаптивность

- [ ] Мобильная версия таблиц (горизонтальный скролл или card view на маленьких экранах)
- [ ] Touch-friendly элементы управления (кнопки минимум 44x44px)
- [ ] Проверить работу на iOS Safari (особенно CSRF cookies и modals)

---

## 5. Новые функции

### 5.1 Уведомления

- [ ] Email-уведомления через `flask-mail` + SMTP/SendGrid:
  - За 1 день до выплаты купона (с суммой в рублях)
  - При погашении облигации
  - При больших изменениях цены (>5% за день)
- [ ] Настройки уведомлений в профиле (вкл/выкл каждый тип)
- [ ] In-app notification bell (уведомления внутри приложения без email)

### 5.2 Расширение модели данных

- [ ] Модель `Transaction`: докупка/продажа частей позиции с сохранением истории
- [ ] Поле `broker_commission` при продаже для точного P&L (сейчас комиссия не учитывается)
- [ ] Поддержка валютных облигаций (курс ЦБ РФ через API `cbr.ru`)
- [ ] Поле `notes` — текстовые заметки к каждой позиции

### 5.3 Скринер и поиск

- [ ] Скринер облигаций с фильтрами: YTM, дюрация, эмитент, тип купона, рейтинг
- [ ] Watchlist — облигации "в избранном" без добавления в портфель
- [ ] Сравнение двух облигаций на одном графике
- [ ] Поиск по эмитенту (все облигации одного эмитента)

### 5.4 Отчётность

- [ ] Экспорт в Excel `.xlsx` с форматированием, формулами, сводной таблицей (`openpyxl`)
- [ ] Налоговый отчёт: расчёт НДФЛ 13% с купонного дохода и прибыли от продаж
- [ ] PDF-отчёт по портфелю через `weasyprint` или `reportlab`


---

## 6. Тестирование

### 6.1 Покрытие

- [ ] Подключить `pytest-cov`, установить цель ≥ 85% покрытия
- [ ] Написать интеграционные тесты с реальной PostgreSQL через `testcontainers`
- [ ] E2E тесты через Playwright: ключевые сценарии (логин, добавить облигацию, продать, экспорт CSV)

### 6.2 Качество кода

- [ ] Настроить `pre-commit` хуки:
  - `ruff` — линтер + автоформатирование
  - `mypy` — статическая типизация
  - `bandit` — SAST (поиск уязвимостей в коде)
- [ ] Property-based тестирование P&L расчётов через `hypothesis`
- [ ] Нагрузочное тестирование через `locust` для MOEX API роутов

### 6.3 CI/CD

- [ ] GitHub Actions workflow: `lint → typecheck → test → build → deploy`
- [ ] Автоматический запуск тестов на каждый PR
- [ ] Проверка зависимостей на CVE через `safety` или GitHub Dependabot
- [ ] Code coverage badge в README

---

## 7. DevOps и деплой

### 7.1 Контейнеризация

- [ ] `Dockerfile` (multi-stage: builder установка зависимостей + slim runtime образ)
- [ ] `docker-compose.yml`: app + PostgreSQL + Redis + Nginx
- [ ] `.dockerignore` для исключения `.env`, `__pycache__`, тестов из образа
- [ ] Health check в Dockerfile: `HEALTHCHECK CMD curl -f http://localhost:5000/health`

### 7.2 Production окружение

- [ ] Nginx как reverse proxy перед Gunicorn (SSL termination, gzip, static files)
- [ ] Gunicorn с несколькими воркерами: `--workers 4 --threads 2 --worker-class gthread`
- [ ] Systemd unit или supervisord для автозапуска и автоперезапуска
- [ ] Let's Encrypt + certbot для SSL сертификата

### 7.3 Мониторинг

- [ ] Sentry для отслеживания ошибок (ловить исключения с контекстом запроса)
- [ ] Prometheus метрики через `prometheus-flask-exporter`
- [ ] Grafana dashboard: API latency, error rate, active users, MOEX API availability
- [ ] Healthcheck endpoint `GET /health`:
  ```json
  { "status": "ok", "db": "ok", "moex": "ok", "cache": "ok" }
  ```
- [ ] Uptime monitoring (UptimeRobot или аналог)

### 7.4 Логирование

- [ ] Структурированные JSON-логи через `structlog` или `python-json-logger`
- [ ] Ротация логов: `TimedRotatingFileHandler` (ежедневно, хранить 30 дней)
- [ ] Единый root logger в `app.py` вместо разрозненных логгеров в каждом файле
- [ ] Логировать медленные запросы (>500ms) и ошибки MOEX API

---

## 8. Документация

- [ ] `README.md` — Features, Quick Start, Configuration, Architecture, API Reference
- [ ] `CONTRIBUTING.md` — как запустить локально, как писать тесты, code style
- [ ] `CHANGELOG.md` в формате [Keep a Changelog](https://keepachangelog.com)
- [ ] Docstrings для публичных функций в `moex.py` и `services/`
- [ ] Postman / Bruno collection для ручного тестирования API
- [ ] Architecture diagram (C4 Level 2) в `/docs/architecture.md`

---

## Роадмап по спринтам

### Sprint 1 — Технический долг (1-2 недели)
> Фундамент, без которого нельзя двигаться дальше

- [ ] Переключить БД на Alembic-миграции
- [ ] Убрать fallback для `SECRET_KEY`
- [ ] Добавить retry + таймауты для MOEX API
- [ ] Заменить `print()` на `logging` в `moex.py`
- [ ] Разделить `config.py` на Dev/Test/Prod классы
- [ ] Добавить `pytest-cov`, довести покрытие до 85%
- [ ] Добавить `ruff` + `mypy` в pre-commit

### Sprint 2 — Безопасность и стабильность (2-3 недели)
> Обязательно перед любым production-деплоем

- [ ] Audit log (IP, действие, timestamp)
- [ ] `PERMANENT_SESSION_LIFETIME` + ротация session ID
- [ ] HSTS, Permissions-Policy заголовки
- [ ] Убрать `Server` заголовок с версией
- [ ] Аватары вне `static/` с авторизацией доступа
- [ ] Debounce для поиска облигаций
- [ ] Dockerfile + docker-compose

### Sprint 3 — UX и аналитика (3-4 недели)
> Делает продукт презентабельным

- [ ] Страница `/dashboard` с обзором портфеля
- [ ] Средневзвешенный YTM по портфелю
- [ ] Виджет купонного дохода (30/90/365 дней)
- [ ] Live-preview облигации при вводе ISIN
- [ ] Skeleton screens при загрузке
- [ ] Мобильная адаптация таблиц
- [ ] Email-уведомления о купонах (flask-mail)

### Sprint 4 — Новые функции (4-6 недель)
> Расширение ценности продукта

- [ ] Скринер облигаций с фильтрами
- [ ] Watchlist (избранные без добавления в портфель)
- [ ] Экспорт в Excel `.xlsx`
- [ ] Налоговый отчёт НДФЛ 13%
- [ ] Модель `Transaction` (частичные покупки/продажи)
- [ ] Бенчмарк: портфель vs RGBI индекс

### Sprint 5 — DevOps и мониторинг (1-2 недели)
> Production-ready деплой

- [ ] Nginx + SSL (Let's Encrypt)
- [ ] `GET /health` endpoint
- [ ] Sentry интеграция
- [ ] Prometheus + Grafana dashboard
- [ ] GitHub Actions CI/CD pipeline
- [ ] README (EN) + OpenAPI документация

### Sprint 6 — Масштабирование (по необходимости)
> Когда есть реальная нагрузка

- [ ] Redis вместо SimpleCache
- [ ] Bulk update в APScheduler
- [ ] Публичный REST API с JWT
- [ ] WebSocket для live-обновления цен
- [ ] Расширение на акции (MOEX stock engine)
- [ ] 2FA через TOTP

---

## Таблица приоритетов по файлам

| Приоритет | Файл | Изменение |
|-----------|------|-----------|
| 🔴 Высокий | `config.py` | Убрать fallback SECRET_KEY, разделить на окружения |
| 🔴 Высокий | `moex.py` | Retry, таймауты, logging вместо print |
| 🔴 Высокий | `blueprints/portfolio.py` | Вынести бизнес-логику в `services/` |
| 🟡 Средний | `models.py` | Transaction модель, `updated_at`, `currency` |
| 🟡 Средний | `app.py` | Bulk update в APScheduler, `/health` роут |
| 🟡 Средний | `static/js/portfolio.js` | Debounce для search, skeleton loaders |
| 🟢 Низкий | `templates/*.html` | Мобильная адаптация, dashboard шаблон |
| 🟢 Низкий | `tests/test_app.py` | pytest-cov, интеграционные тесты |

---

## Чеклист для проверки production-готовности

```bash
# Тесты и покрытие
python -m pytest tests/ --cov=. --cov-report=term-missing
# Цель: ≥ 85% coverage, 0 failed tests

# Статический анализ
ruff check .
mypy .
bandit -r . -ll
# Цель: 0 ошибок, 0 критических уязвимостей

# Docker запуск
docker-compose up --build
curl http://localhost:5000/health
# Цель: {"status": "ok", "db": "ok", "moex": "ok"}

# Нагрузочный тест
locust -f locustfile.py --headless -u 50 -r 10 --run-time 60s
# Цель: p99 latency < 200ms, error rate < 0.1%

# Безопасность зависимостей
safety check
# Цель: 0 known vulnerabilities
```
