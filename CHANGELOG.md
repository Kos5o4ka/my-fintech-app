# Changelog

Все значимые изменения в проекте документируются здесь.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).
Проект следует [Semantic Versioning](https://semver.org/lang/ru/).

---

## [Unreleased]

### Added
- **Импорт отчётов Tinkoff/Т-Банк**: поддержка брокерских `.xlsx`-отчётов — сделки с облигациями, дедупликация OTC-операций, купонный доход

### Changed
- **Performance**: кэширование купонного календаря на 12 часов — ликвидация N+1 HTTP-запросов к MOEX ISS
- **Performance**: перенос Circuit Breaker в Redis — предотвращение сплит-брейна в Gunicorn воркерах
- **Architecture**: вынос фонового планировщика APScheduler из процесса Flask — исключение дублирования задач при multi-worker деплое
- **Refactor**: устранение дублирования кода, вынос вспомогательных функций и именованных констант

### Fixed
- **Security**: строгий одноразовый сброс OTP в `verify_otp` при любой попытке верификации — исключение brute-force
- **Security**: аутентификация вебхука Telegram секретным ключом в URL — защита от спуфинга
- Коррекция расчёта налоговой базы (`calc_tax_report`) — учёт купонных доходов по проданным за год бумагам
- Математическая формула средневзвешенного YTM портфеля — знаменатель теперь включает только бумаги с валидным YTM
- Баг «Limit before Filter» в скринере облигаций

---

## [1.3.3] — 2026-05-24

### Added
- **Импорт брокерских отчётов Excel**: поддержка загрузки `.xlsx`-файлов на вкладке «Импорт» — автоматическое распознавание столбцов (ISIN, Количество, Цена, Дата, Заметка) в форматах разных брокеров
- `CONTRIBUTING.md` — руководство для разработчиков: локальный запуск, code style, PR flow
- `CHANGELOG.md` — история изменений в формате Keep a Changelog
- `bruno/` — коллекция REST-запросов для Bruno API-клиента (42 эндпоинта)
- `docs/architecture.md` — C4 Level 2 диаграммы (Mermaid): container, layers, ER, sequence (2FA, MOEX)

### Fixed
- **Скринер**: опечатка `"МУНИЦИN"` (латинская N) в фильтре муниципальных облигаций — фильтр по типу «Муниципальные» теперь работает корректно
- **Сравнение облигаций**: легенда `compareLegend` всегда отображалась из-за конфликта `display:none` и `display:flex` в одном атрибуте style — теперь скрывается до первого запроса
- **Таблица портфеля**: пустое состояние рендерилось с `colspan="8"` при 9 столбцах — исправлено на `colspan="9"`
- **Импорт брокерских отчётов**: ошибки частичного импорта (не найденные ISIN, некорректные данные) не отображались в UI из-за чтения поля `data.skipped` вместо `data.errors` — исправлено

---

## [1.3.0] — 2026-05-23

### Added (Рефакторинг — вынос CSS/JS)
- 5 новых CSS-файлов: `base.css`, `dashboard.css`, `profile.css`, `landing.css`, `portfolio-page.css`
- 6 новых JS-файлов: `base.js`, `dashboard.js`, `profile.js`, `landing.js`, `portfolio-page.js`, `admin.js`
- Атрибут `data-user-id` на `<body>` в `base.html` для передачи user ID в JS без Jinja в static-файлах
- `build_assets.py` расширен: 10 JS-файлов + 9 CSS-файлов, генерирует 19 `.min.*` файлов

### Changed
- Все HTML-шаблоны (`dashboard.html`, `profile.html`, `index.html`, `portfolio.html`, `admin.html`) освобождены от inline `<style>` и `<script>` блоков
- Шаблоны загружают только внешние `.min.css` и `.min.js` через `<link>` и `<script src>`

### Fixed
- `admin.js` теперь читает user ID из `document.body.dataset.userId` вместо Jinja-интерполяции в статическом файле

---

## [1.2.0] — 2026-05-20

### Added (Stage 6 — DevOps и деплой)
- `Dockerfile` — multi-stage сборка: builder (gcc + psycopg2 + Pillow) + runtime (~200 МБ меньше), непривилегированный `appuser uid=1000`
- `docker-compose.yml` — 4 сервиса: Flask-приложение + PostgreSQL 16 + Redis 7 + Nginx 1.27
- `gunicorn.conf.py` — авто-workers (`2×CPU+1`, min 2, max 8), threads, timeouts, security limits
- `nginx/nginx.conf` + `nginx/conf.d/app.conf` — gzip, rate limiting, статика напрямую (30d кэш), HTTPS блок готов
- `.dockerignore` — исключает .env, venv, тесты, .git
- `.github/workflows/ci.yml` — CI/CD: lint → test → docker build + smoke test; deploy job (шаблон)
- Sentry интеграция: `FlaskIntegration + SqlalchemyIntegration`, `traces_sample_rate=0.1`, graceful fallback
- `HEALTHCHECK` в Dockerfile — `curl -f /health` каждые 30с
- `.env.production.example` — шаблон с документацией всех переменных

### Changed
- `config.py`: `ProductionConfig` использует PostgreSQL (DATABASE_URL), Redis (REDIS_URL); валидация обязательных env-переменных при старте

---

## [1.1.0] — 2026-05-15

### Added (Stage 4 — Новые функции)
- **Sharpe Ratio**: `calc_sharpe_ratio()` в `portfolio_service.py`, rf=16%/12, карточка в stats strip, `GET /api/portfolio/sharpe`
- **Бенчмарк RGBI**: вкладка "Бенчмарк" на странице портфеля, Chart.js линейный чарт, переключатели периода, `GET /api/portfolio/benchmark?range=`
- **Сравнение облигаций**: вкладка "Сравнение", два ISIN, нормализация к 100, `GET /api/portfolio/compare?isin1=&isin2=&range=`
- **Скринер**: фильтры YTM / тип эмитента / дюрация, `GET /api/portfolio/screener`
- **Вотчлист**: `GET/POST /api/watchlist` — избранные бумаги
- **Заметки к позиции**: поле `notes` в `BondPortfolio`, кнопка 📝, `PATCH /api/portfolio/<id>/notes`
- **PDF-отчёт**: `/portfolio/report` → `pdf_report.html`, `window.print()`, `@media print { @page { size: A4 } }`
- **Налоговый отчёт UI**: вкладка "Налоги", выбор года, НДФЛ 13%, таблица сделок, `GET /api/portfolio/tax?year=`
- **Excel экспорт**: `GET /api/portfolio/export/xlsx` с форматированием через openpyxl
- **In-app notification bell**: колокольчик в sidebar, `GET /api/notifications/upcoming?days=7`
- **Activity feed**: вкладка "Активность" в профиле, `GET /api/profile/activity?page=`
- **Quick stats в профиле**: `GET /api/profile/stats`

### Changed
- Страница портфеля: добавлены вкладки "Бенчмарк", "Налоги", "Сравнение"
- Stats strip: 5 карточек вместо 4 (добавлен Sharpe Ratio)

---

## [1.0.0] — 2026-05-10

### Added (Stage 0–3 — Базовая функциональность)

#### UI/UX (Stage 0)
- Полный редизайн: Inter, CSS design tokens, dark/light тема с anti-FOUC
- Sidebar 220px (desktop) + bottom bar 64px (mobile); collapsed-режим с tooltips
- Лендинг: animated gradient blobs, glassmorphism login card, floating labels
- Dashboard: metric cards с SVG-иконками и countUp-анимацией, P&L Area chart, Donut chart
- Страница портфеля: sticky header, slide-in drawer, ISIN autocomplete, FAB, sell modal с live P&L, mobile card-view
- Страница профиля: gradient hero, tabbed layout, activity feed
- `build_assets.py` — минификация CSS/JS
- `animations.css` — fadeInUp/Down, scaleIn, blobFloat, pulse-dot, shimmer, formShake, toastProgress

#### Архитектура (Stage 1)
- Сервисный слой: `portfolio_service.py`, `moex_service.py`, `user_service.py`, `telegram_service.py`
- Pydantic v2 схемы: `AddBondRequest`, `SellBondRequest`, `ScreenerRequest`, `LoginRequest`, `ChangePasswordRequest`, `EmailSettingsRequest`
- `constants.py`: NDFL_RATE, BOND_CACHE_TTL, STATS_CACHE_TTL, MIN_PASSWORD_LEN и т.д.
- Alembic-миграции: `currency`, `updated_at`, `notes`, индекс `ix_bp_isin`, `AuditLog`

#### Оптимизация (Stage 2)
- Пагинация для `/api/portfolio` и `/api/portfolio/history`
- FileSystemCache (TTL 5 мин для данных MOEX, 15 мин для stats)
- ETag + Cache-Control для `/api/portfolio`
- Circuit breaker в `moex.py`: 5 ошибок → пауза 10 мин
- Retry с exponential backoff через tenacity
- `bulk_update_mappings()` в APScheduler (один SQL вместо N UPDATE)

#### Безопасность + Telegram (Stage 3)
- 2FA через Telegram: OTP-код (6 цифр, TTL 5 мин), pending-токен для шага верификации
- Telegram-бот: webhook, `/start` (привязка через deep-link), `/stop`, `/help`
- AuditLog: login_ok/fail, 2fa_sent/fail, logout, change_password, tg_link/unlink/notif
- Email-уведомления за 1 день до купона (APScheduler)
- Аватары: Pillow RGB JPEG 400×400, strip EXIF, UUID-имена
- HTTP-заголовки: HSTS (prod), Permissions-Policy, убран `Server:`

#### Тестирование (Stage 5)
- `tests/test_app.py` — 36 интеграционных тестов (auth, portfolio CRUD, MOEX mock, profile, 2FA, watchlist, export)
- `tests/test_properties.py` — 17 Hypothesis property-based тестов (P&L, Sharpe, YTM)
- Pre-commit: ruff, ruff-format, bandit, trailing-whitespace, check-yaml, debug-statements

### Changed
- N/A (первый релиз)

### Fixed
- N/A (первый релиз)

---

[Unreleased]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.3.3...bugfix/v1.4.0-ui-data
[1.3.3]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.3.0...v1.3.3
[1.3.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Kos5o4ka/my-fintech-app/releases/tag/v1.0.0
