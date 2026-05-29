# Changelog

Все значимые изменения в проекте документируются здесь.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).
Проект следует [Semantic Versioning](https://semver.org/lang/ru/).

---

## [2.2.0] — 2026-05-29

### Added
- **Вкладка «Настройки» в профиле**: тема оформления (системная/светлая/тёмная), время уведомлений с авто-определением часового пояса (`Intl.DateTimeFormat`), срок уведомлений об офертах (7/14/30 дней)
- **Разделение активности на категории**: фильтры «Аккаунт» / «Портфель» в журнале действий; колонка `category` в `AuditLog` с индексом `ix_audit_user_category`
- **Site Notifications**: модель `SiteNotification`, эндпоинты `GET /api/notifications/unread_count`, `GET /api/notifications`, `POST /api/notifications/read`; polling каждые 60с, синий badge в sidebar
- **Admin Broadcast**: `POST /api/admin/broadcast` — рассылка уведомлений (сайт / Telegram / оба), выбор получателей (все или список)
- **2FA toggle**: эндпоинты `POST /api/profile/2fa/enable`, `/2fa/disable`, `/2fa/send-otp`; отключение через OTP или пароль; модалка с двумя методами
- **OTP copy button**: `copy_text` inline keyboard (Telegram Bot API 6.7+) для одного нажатия копирования кода
- **Bot settings** (`/settings`): inline keyboard для toggle уведомлений, выбора времени и дней оферт
- **Pydantic-схема `SettingsUpdate`**: валидация настроек через `app/schemas/profile.py`
- **`audit_service.py`**: централизованный сервис аудит-лога
- **`notification_service.py`**: сервис рассылки и CRUD site notifications
- **Flatpickr date picker**: красивый кастомный календарь и time picker вместо стандартных браузерных; русская локализация, тёмная тема через CSS-переменные; `flatpickr-init.js` с авто-инициализацией и MutationObserver
- **45 новых тестов** (`tests/test_stage12.py`): settings, activity categories, 2FA toggle, site notifications, admin broadcast, audit service, notification service, Pydantic schema validation
- **Миграция `stage12_settings_notif_activity`**: идемпотентная (IF NOT EXISTS); user settings columns, audit_log.category, site_notifications table

### Changed
- **Рефакторинг profile.py**: убраны все `db.session.commit()` из blueprint (было 3); 2FA enable/disable, settings audit → перенесены в `user_service.py`; валидация через Pydantic вместо inline regex; все импорты подняты на уровень модуля
- **profile.js**: устранена двойная привязка tab handlers; `window.prfTab` → единая функция `switchTab()`
- **portfolio.js**: даты работают через flatpickr API (`fpSet`/`fpClear`) при программном сбросе
- **base.html**: тема кнопка убрана из sidebar; theme init script поддерживает `system`; flatpickr CSS/JS подключены

---

## [Unreleased]

### Added
- **Интеграция T-Bank API**: добавлено поле `tinkoff_token` в `User`, возможность сохранения токена в профиле и кнопка «Синхронизировать» на главной странице портфеля (заглушка в `tinkoff_service.py`).
- **Виджет «Предстоящие купоны»**: перенесен на главную страницу портфеля и вкладку аналитики, удален из модалки добавления облигации.
- **Налоговый отчет**: группировка одинаковых сделок в один день по одной цене; детали сделок (комиссии и точное время) открываются в выпадающем списке.
- **Админ-панель**: добавлен удобный поиск пользователей по списку при рассылке уведомлений (фильтрация по логину и ID).
- **Логирование**: добавлено логирование действий `log_action` при добавлении, продаже и удалении облигаций.

### Changed
- **Избранное (Watchlist)**: полный редизайн вкладки, добавление происходит через встроенное поле ввода (inline), а не через модальное окно. Окно с настройками уведомлений теперь неактивно, если сами уведомления выключены.
- **Подтягивание цены**: исправлено и перепроверено автоматическое подтягивание цены в форму при успешном поиске облигации.

### Fixed
- Исправлена ошибка 500 (Internal Server Error) при сбросе портфеля (использовалась неверная функция проверки пароля, заменена на `check_password_hash`).
- Исправлено отображение JSON в логах активности (Activity feed), методы (например, `2fa_telegram`) теперь парсятся и отображаются корректно. Окно Activity теперь правильно реагирует на события добавления/удаления облигации.

---

## [2.1.0] — 2026-05-29

### Added
- **Страница аналитики** `/analytics` — отдельный blueprint `analytics.py`; вкладки Tax / Sharpe / Charts / Compare / RGBI вынесены из portfolio
- **Страница импорта** `/import` — отдельный blueprint `imports.py`; все парсеры брокерских XLSX, CSV-экспорт, дедупликация
- **`normalize_bond_price()`** — авто-определение и конвертация процентных цен в рубли (сравнение гипотез % vs ₽ по номиналу)
- **Bond price healing** — при обнаружении процентной цены исправляет `buy_price` в `BondPortfolio` и синхронизирует связанные транзакции
- **`Transaction.deal_no`** — поле для дедупликации при импорте брокерских отчётов
- **CI: проверка миграций** — шаг `upgrade → downgrade base → upgrade` ловит неидемпотентные ревизии до деплоя
- **`defusedxml`** — парсинг XML ЦБ РФ через защищённую библиотеку вместо stdlib `xml.etree`

### Fixed
- **`TAX_TTL` / `SHARPE_TTL` не импортированы** в `analytics.py` — `cache.set()` выбрасывал `NameError`, который глотался `except Exception: pass`; кэш налогового отчёта и Sharpe фактически не работал
- **Тест-изоляция**: `FileSystemCache` протекал между тестами — теперь `NullCache` при `FLASK_TESTING=1`
- **НДФЛ ставки для ЦБ** (ст. 214.1 НК РФ, ФЗ-176 от 12.07.2024): исправлены с 5-ступенчатой общей шкалы (до 22%) на корректные 13% / 15%. Ставки 18/20/22% применяются к зарплате, но НЕ к доходам от ценных бумаг
- **`apply_ldv`** (пп. 1 п. 1 ст. 219.1 НК РФ): вычет теперь 3 млн × полных лет владения (`days_held // 365`), а не фиксированный 1 год. При 5 годах вычет 15 млн ₽, а не 3 млн ₽
- **Убытки по ЦБ** (ст. 214.1 НК РФ): убыток по одной позиции теперь уменьшает суммарную налоговую базу за год; ранее `max(pnl, 0)` обнулял убытки
- **`calc_fifo_pnl`**: валюта определяется из транзакций покупки, не хардкодится как RUB
- **Bandit High/Medium** — все high/medium bandit-предупреждения устранены: `hashlib.md5(usedforsecurity=False)`, `defusedxml`, `assert` заменён на `if/raise`

### Changed
- **Структура проекта**: модули перенесены в пакет `app/`, build-скрипты в `scripts/`
- **Слои архитектуры**: DB-доступ вынесен из blueprints в services (было ~97 прямых обращений к `BondPortfolio.query` / `db.session` в blueprint'ах, стало 0 в portfolio, admin, auth, analytics, profile); создан `admin_service.py`, `auth_service.py`; `portfolio_service.py` расширен CRUD-операциями
- **Форматирование**: `ruff format` применён ко всей кодовой базе; все `ruff check` ошибки устранены
- `blueprints/portfolio.py` декомпозирован: аналитика → `analytics.py`, импорт/экспорт → `imports.py`; portfolio.py содержит только CRUD портфеля

---

## [1.4.0] — 2026-05-25

### Added
- **Bootstrap локально**: `bootstrap.min.css` и `bootstrap.bundle.min.js` перенесены в `static/vendor/` — нет CDN-зависимости, офлайн-работа
- **Авто-определение брокера**: `_detect_broker(all_rows)` по сигнатурам XLSX; чип «Авто» теперь реально определяет ВТБ / Т-Инвестиции и подставляет нужный парсер
- **Анимация sun ↔ moon**: при переключении темы иконка в сайдбаре сменяется с анимацией `rotate + scale` (CSS `@keyframes themeIconSpin`); иконка отражает *целевой* режим (луна → нажать для тёмной темы)
- **Валютные облигации**: `cbr.py` — клиент курсов ЦБ РФ (XML API, кэш 4 ч); CBR используется как фолбэк в `get_currency_rates()` вместо хардкода; в таблице портфеля для не-рублёвых облигаций отображается "≈ X ₽" под ценой
- **Брокер ВТБ**: импорт отчётов ВТБ — `_parse_vtb_xlsx()`, чип «ВТБ» в форме, хинт-текст

### Fixed
- **T-Investments XLSX**: убран `read_only=True` из `openpyxl.load_workbook()` — исправлено чтение файлов с `<dimension ref="A1"/>` (только 1 строка вместо 3709)

### Changed
- Частичная продажа позиции — поле количества в sell-модале, валидация, split-запись в `BondPortfolio`; функциональность уже присутствовала в бэкенде (`SellBondRequest.amount`)

---

## [1.3.4] — 2026-05-25

### Added
- **Удаление аватара**: кнопка «Удалить аватар» на странице профиля + `DELETE /api/profile/avatar` + `delete_avatar()` в `user_service.py`; кнопка показывается только при наличии аватара
- **Bell mark-as-read**: кнопка «✓ Прочитано» в дропдауне уведомлений; бадж скрывается через `localStorage.bellReadCount` и не появляется повторно до прихода новых событий
- **Импорт отчётов Tinkoff/Т-Банк**: поддержка брокерских `.xlsx`-отчётов — сделки с облигациями, дедупликация OTC-операций, купонный доход

### Changed
- **Bell dropdown**: `max-height` увеличен с 280px до 360px для лучшей читаемости длинных списков уведомлений
- **Performance**: кэширование купонного календаря на 12 часов — ликвидация N+1 HTTP-запросов к MOEX ISS
- **Performance**: перенос Circuit Breaker в Redis — предотвращение сплит-брейна в Gunicorn воркерах
- **Architecture**: вынос фонового планировщика APScheduler из процесса Flask — исключение дублирования задач при multi-worker деплое
- **Refactor**: устранение дублирования кода, вынос вспомогательных функций и именованных констант

### Fixed
- **Logout**: кнопка «Выйти из аккаунта» на странице профиля — перенесена из inline `onclick` в `addEventListener` (DOMContentLoaded), устранён defer race-condition; `profile.min.js` пересобран
- **Sidebar**: удалена дублирующая кнопка «Экспорт Excel» из сайдбара; кнопка остаётся на странице `/portfolio`
- **ISIN modal**: `#bondChartModal` перемещён из `{% block content %}` в `{% block extra_modals %}` — вне `.app-main`, Bootstrap stacking context восстановлен (экран больше не затемняется без модала)
- **Broker report CPU**: `openpyxl read_only=True` + `iter_rows(values_only=True)` — SAX streaming вместо DOM-дерева, памяти ×5–10 меньше, CPU ×3–5 быстрее при импорте годовых отчётов
- **Admin**: `#changePwModal` перемещён из `{% block content %}` в `{% block extra_modals %}` для корректного Bootstrap stacking context
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

[2.2.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.4.0...v2.1.0
[Unreleased]: https://github.com/Kos5o4ka/my-fintech-app/compare/v2.2.0...HEAD
[1.4.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.3.3...v1.4.0
[1.3.3]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.3.0...v1.3.3
[1.3.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Kos5o4ka/my-fintech-app/releases/tag/v1.0.0
