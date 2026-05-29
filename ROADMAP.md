# InvestTrack — Полный Roadmap

> **Ветка:** `main`  
> Последнее обновление: 2026-05-29  
> **Версионность:** патч-фиксы поднимают версию на `+0.0.1`, новые фичи — на `+0.1.0`

---

## Статус по этапам

| Этап | Тема | Статус |
|------|------|--------|
| 0 | Premium Редизайн (UI/UX) | ✅ Выполнен |
| 1 | Архитектурный рефакторинг | ✅ Выполнен |
| 2 | Оптимизация и кэш | ✅ Выполнен |
| 3 | Безопасность + Telegram | ✅ Выполнен |
| 4 | Новые фичи | ✅ Выполнен |
| 5 | Тестирование | ✅ Выполнен (базовое) |
| 6 | DevOps и деплой | ✅ Выполнен |
| 7 | Документация | ✅ Выполнен |
| 8 | Архитектура и Безопасность | ✅ Выполнен |
| 9 | Новые возможности и UI (v1.5.0) | ✅ Выполнен |
| 10 | Декомпозиция Blueprint + Tax fixes | ✅ Выполнен |
| 11 | Архитектура, дюрация, алерты, HHI и тесты (v2.1.0) | ✅ Выполнен |
| 12 | Настройки, уведомления, админ рассылка (v2.2.0) | ✅ Выполнен |
| 13 | Мультиключевой импорт и Валюты (v2.3.0) | ⏳ Запланирован |

---

## Этап 0 — Premium Редизайн ✅ ВЫПОЛНЕН

> Цель: UI, который выглядит как продукт лучшей дизайн-студии уровня Linear, Vercel, Stripe Dashboard.

### 0.1 Дизайн-система — фундамент

- [x] **Типографика**: Inter подключён через Google CDN (`font-family: 'Inter'`), `rel="preload"` в base.html
- [x] **Полная замена CSS-переменных** в `variables.css`:
  - Палитра: slate, blue, emerald, violet, amber, cyan (по 4–10 ступеней)
  - Семантические токены: `--surface-0..3`, `--text-primary/secondary/tertiary`
  - Тени: `--shadow-xs` до `--shadow-xl`, `--glow-blue/green/violet`
  - Анимации: `--dur-fast: 120ms`, `--dur-base: 200ms`, `--dur-slow: 350ms`, `--ease-base`
  - Радиусы: `--radius-xs: 4px` до `--radius-2xl: 24px`
- [x] **Базовые компоненты** — badge, metric-card, toggle-switch, upload-zone, info-rows
- [ ] `design-system.css` — отдельный файл с Chip/Tag/Tooltip *(не критично)*

### 0.2 Навигация — полный редизайн

- [x] **Sidebar** 220px (desktop) + **bottom-bar** 64px (mobile) — `sidebar.css` + `sidebar.js`
- [x] **SVG-логотип** — трендовая линия + точка вместо emoji
- [x] **User widget** — аватар с инициалами, имя, роль, клик → /profile
- [x] **Экспорт Excel** в sidebar + кнопка темы
- [x] **Collapsed sidebar** — иконки без текста, tooltip при hover, стрелка разворачивается
- [x] **Notification bell** — колокольчик в sidebar, badge счётчик, dropdown с купонами 7 дней

### 0.3 Лендинг (`/`) — полный редизайн

- [x] **Hero секция** — CSS animated gradient blobs (3 слоя), тёмный фон #040d1a
- [x] **Glassmorphism login card** — `backdrop-filter: blur(20px)`, floating labels
- [x] **Кнопка входа** — gradient, loading spinner при сабмите
- [x] **Feature grid под hero** — 3 карточки с hover-эффектом (аналитика / уведомления / экспорт)
- [x] **Footer** — slim footer с версией v1.0.0 и копирайтом

### 0.4 Dashboard — полный редизайн

- [x] **Metric cards** — SVG-иконка в градиентном круге, accent-полоска снизу
- [x] **countUp анимации** — все числовые значения считают при загрузке (`Common.countUp`)
- [x] **Купонный календарь** — timeline стиль, badge с датой
- [x] **Best / Worst позиции** — карточки с P&L
- [x] **Summary row** — Позиций / Доход 90д / Доход год
- [x] Area chart P&L с переключателем 7д/30д/YTD — кумулятивный реализованный P&L
- [x] Donut chart распределения по эмитентам — топ-5 + "Остальные"

### 0.5 Страница портфеля — редизайн

- [x] **Stats strip** — 5 карточек: стоимость, YTM, P&L, сделки, Sharpe Ratio
- [x] **Sticky table header** с `backdrop-filter: blur(8px)`
- [x] **Drawer "Добавить облигацию"** — slide-in 400px, backdrop blur, телепортируется в `body`
- [x] **ISIN autocomplete** — live поиск `/api/search_bond`, превью карточки
- [x] **FAB кнопка** для mobile
- [x] **Sell modal** с live P&L preview (обновляется при вводе цены/комиссии)
- [x] **Mobile card-view** — таблица → карточки на < 767px с `data-label`
- [x] **Кнопка 📝** — заметки к позиции, PATCH `/api/portfolio/<id>/notes`
- [x] **Кнопка PDF** — ссылка на `/portfolio/report` (новая вкладка)
- [x] **Сортировка** по клику на заголовок столбца
- [x] **Tabs**: Позиции / История / Скринер / Бенчмарк / Налоги / Сравнение
- [ ] Sparklines в колонке цены *(сложно без отдельного API)*

### 0.6 Страница профиля — редизайн

- [x] **Hero секция** — gradient banner, аватар 80px, quick stats (позиции / стоимость / сделки)
- [x] **Tabbed layout** — 4 вкладки: Профиль / Безопасность / Уведомления / Активность
- [x] **Upload zone** — drag-to-upload стиль с превью имени файла
- [x] **Info rows** — Логин / Роль / Email
- [x] **Custom toggle switch** для email-уведомлений
- [x] **Telegram section** — link/unlink/toggle уведомлений
- [x] **Activity feed** — журнал входов/действий из AuditLog, пагинация

### 0.7 Тёмная тема

- [x] Все компоненты проверены в dark mode
- [x] CSS-переменные `--surface-0..3` для dark
- [x] Переключатель в sidebar + mobile bottom bar
- [x] Anti-FOUC inline script в `<head>`
- [ ] Анимация sun↔moon при переключении *(косметика)*

### 0.8 Micro-interactions и анимации

- [x] **countUp** — `Common.countUp()` с easeOutExpo, ru-RU локаль
- [x] **Toast с progress bar** — 3px полоска, `@keyframes toastProgress`
- [x] **Toast swipe-to-dismiss** — свайп вправо ≥80px на мобильных
- [x] **Page transitions fade** — CSS opacity+transform на `.app-main` (170ms)
- [x] **Form shake** — `@keyframes formShake` + `Common.shake(el)` при ошибке
- [x] **fadeInUp каскад** — карточки появляются с задержкой
- [x] **Skeleton loaders** — shimmer на metric cards (dashboard) + skeleton rows в таблице

### 0.9 Производительность

- [x] **Build system** — `build_assets.py` минифицирует CSS + JS в `.min.*`
- [x] `prefers-reduced-motion: reduce` — отключает все анимации
- [x] `rel="preload"` для Inter в base.html
- [x] **CSS `contain: layout style`** на `.pf-stat`, `.dash-card`, `.pf-card`, `.metric-card`
- [ ] Bootstrap локально вместо CDN *(не критично)*

### 0.10 Адаптивность

- [x] Sidebar → bottom bar на `< 768px`
- [x] Metric cards: 2 колонки на mobile, 4 на desktop
- [x] Таблица портфеля: card-view на `< 767px`
- [x] FAB кнопка "Добавить" на mobile
- [x] Drawer → full-screen на `< 480px`

---

## Этап 1 — Архитектурный рефакторинг ✅ ВЫПОЛНЕН

### 1.1 Сервисный слой

- [x] `services/portfolio_service.py` — P&L, расчёт доходности, купонный доход, Sharpe Ratio
- [x] `services/moex_service.py` — кэшированные обращения к MOEX ISS API
- [x] `services/user_service.py` — аватары, email-настройки пользователей
- [x] Blueprints = только HTTP-слой: parse → call service → respond

### 1.2 Типизация

- [x] Python type hints во всех функциях
- [x] Pydantic v2 схемы в `schemas/`: `AddBondRequest`, `SellBondRequest`, `ScreenerRequest`, `LoginRequest`, `ChangePasswordRequest`, `EmailSettingsRequest`
- [x] `constants.py` — все магические числа (TTL, таймауты, NDFL_RATE=0.13, MIN_PASSWORD_LEN=8)

### 1.3 База данных и миграции

- [x] Alembic-миграции через Flask-Migrate
- [x] `BondPortfolio`: `currency`, `updated_at`, `notes`, индекс `ix_bp_isin`
- [x] `User`: `telegram_chat_id`, `telegram_notifications`
- [x] `AuditLog`: `action`, `user_id`, `ip_address`, `user_agent`, `details`, `created_at`

### 1.4 Конфигурация

- [x] `DevelopmentConfig`, `TestingConfig`, `ProductionConfig` в `config.py`
- [x] Валидация обязательных env-vars при старте
- [x] `.env.production.example` с документацией всех переменных

---

## Этап 2 — Оптимизация ✅ ВЫПОЛНЕН

- [x] Пагинация `/api/portfolio` и `/api/portfolio/history`
- [x] `bulk_update_mappings()` в APScheduler (один SQL вместо N UPDATE)
- [x] **FileSystemCache** — хранит на диске, не расходует RAM
- [x] TTL 15 мин для stats, ETag + Cache-Control для `/api/portfolio`
- [x] `_bust_user_cache()` при add_bond / sell_bond
- [x] **Circuit breaker** в MOEX: 5 ошибок → пауза 10 мин
- [x] Retry с exponential backoff через `tenacity`
- [x] Connection pooling: `pool_size=5`, `max_overflow=10`, `pool_recycle=1800`

---

## Этап 3 — Безопасность + Telegram ✅ ВЫПОЛНЕН

- [x] `services/telegram_service.py`: send_message, generate_otp, verify_otp, generate_link_token, deep-link
- [x] `blueprints/telegram_bot.py`: webhook, /start, /stop, /help
- [x] **2FA через Telegram**: OTP-код при входе (pending-токен TTL 5 мин)
- [x] `AuditLog`: login_ok/fail, 2fa_sent/fail, logout, change_password, tg_link/unlink
- [x] Сессии: `session.permanent=True`, idle timeout 30 мин
- [x] HTTP-заголовки: HSTS, Permissions-Policy, убран Server header
- [x] Аватары: Pillow re-encode RGB JPEG 400×400, strip EXIF, UUID-имена

---

## Этап 4 — Новые функции ✅ ВЫПОЛНЕН

### 4.1 Аналитика

- [x] **Sharpe Ratio** — `calc_sharpe_ratio()` в portfolio_service, rf=16%/12, карточка в stats strip, endpoint `GET /api/portfolio/sharpe`
- [x] **Бенчмарк RGBI** — вкладка "Бенчмарк", Chart.js линейный чарт, переключатели 1нед/1мес/3мес/1год/Всё
- [x] **Сравнение двух облигаций** — вкладка "Сравнение", два ISIN, нормализация к 100, endpoint `GET /api/portfolio/compare`

### 4.2 Скринер

- [x] Фильтры: YTM от/до, тип эмитента (ОФЗ/муниципальные/корпоративные), дюрация в годах от/до
- [x] Watchlist — избранные бумаги

### 4.3 Уведомления

- [x] **In-app notification bell** — колокольчик в sidebar, `GET /api/notifications/upcoming?days=7`
- [x] **Activity feed в профиле** — вкладка "Активность", пагинация, AuditLog
- [x] Email за 1 день до купона (APScheduler)

### 4.4 Данные

- [x] **Поле `notes`** — заметки к позиции, кнопка 📝, `PATCH /api/portfolio/<id>/notes`

### 4.5 Отчётность

- [x] **PDF-отчёт** — `/portfolio/report` рендерит `pdf_report.html`, `window.print()` → PDF/бумага
- [x] **Налоговый отчёт UI** — вкладка "Налоги", выбор года, НДФЛ 13%, таблица сделок, endpoint `GET /api/portfolio/tax?year=`
- [x] Excel `.xlsx` с форматированием

### 4.6 Профиль

- [x] **Quick stats** в hero профиля — `GET /api/profile/stats` (позиции / стоимость / сделки)
- [x] **Activity feed** — `GET /api/profile/activity?page=` (пагинация по 20)

---

## Этап 5 — Тестирование ✅ ВЫПОЛНЕН (базовое)

- [x] `tests/test_app.py` — 36 интеграционных тестов: auth, portfolio CRUD, MOEX mock, profile, 2FA, watchlist, export
- [x] `tests/test_properties.py` — 17 property-based тестов (Hypothesis): P&L знак/масштаб/комиссия, Sharpe инварианты, YTM weighted bounds
- [x] `setup.cfg` — pytest-cov конфиг, путь к testpaths, filterwarnings
- [x] `.pre-commit-config.yaml` — ruff (fix + format) + bandit (-ll) + pre-commit-hooks (trailing-whitespace, end-of-file-fixer, check-yaml, debug-statements)
- [x] `requirements-dev.txt` — pytest, pytest-cov, hypothesis, ruff, bandit, pre-commit
- [ ] Интеграционные тесты с реальной PostgreSQL через `testcontainers`
- [ ] E2E через Playwright: логин → добавить → продать → экспорт
- [ ] Покрытие ≥ 85% (текущее ~44%, узкое место: moex.py, telegram_service.py)

---

## Этап 6 — DevOps и деплой ✅ ВЫПОЛНЕН

### 6.1 Docker

- [x] **Multi-stage `Dockerfile`** — builder (gcc + компиляция psycopg2/Pillow) + runtime (~200 МБ меньше), непривилегированный `appuser uid=1000`
- [x] **`.dockerignore`** — исключает .env, venv, тесты, кэш, загрузки
- [x] **`HEALTHCHECK`** в Dockerfile — `curl -f /health` каждые 30с

### 6.2 docker-compose

- [x] **`docker-compose.yml`** — 4 сервиса: app + PostgreSQL 16-alpine + Redis 7-alpine + Nginx 1.27-alpine
- [x] **Изолированная сеть** — app недоступен снаружи, только через Nginx
- [x] **Health checks** на всех сервисах, `depends_on: condition: service_healthy`
- [x] **Именованные volumes**: postgres_data, redis_data, app_avatars, app_uploads, app_cache, nginx_certs
- [x] **`SECRET_KEY` обязателен** — docker compose падает с понятной ошибкой если не задан

### 6.3 Gunicorn

- [x] **`gunicorn.conf.py`** — auto workers (2×CPU+1, мин 2, макс 8), threads, timeouts, access log format, security limits для заголовков
- [x] **Переменные**: GUNICORN_WORKERS, GUNICORN_THREADS, GUNICORN_TIMEOUT, PORT

### 6.4 Nginx

- [x] **`nginx/nginx.conf`** — worker_processes auto, gzip, rate-limit zones, proxy buffering, `server_tokens off`
- [x] **`nginx/conf.d/app.conf`** — статика отдаётся Nginx напрямую (30d кэш + immutable), rate limit на login/api/general, `/health` без лога
- [x] **HTTPS блок** готов (закомментирован), настраивается добавлением сертификатов
- [ ] Let's Encrypt + certbot *(отдельный шаг при деплое на реальный сервер)*

### 6.5 Sentry

- [x] **`sentry-sdk[flask]`** — опциональная инициализация если задан `SENTRY_DSN`
- [x] **FlaskIntegration + SqlalchemyIntegration** — трассировка запросов и SQL
- [x] **`traces_sample_rate=0.1`** (10%), `send_default_pii=False`
- [x] Graceful fallback — если sentry-sdk не установлен, продолжает работу без него

### 6.6 GitHub Actions

- [x] **`.github/workflows/ci.yml`** — 3 джоба: lint → test → docker build + smoke test
- [x] **lint**: ruff check + ruff format + bandit security scan
- [x] **test**: pytest --timeout=60, coverage → Codecov (non-blocking)
- [x] **docker**: build образа, smoke test `/health` в контейнере
- [x] **concurrency**: отмена предыдущего запуска при новом коммите в ту же ветку
- [x] **deploy job** — шаблон (SSH + Docker Hub) закомментирован, готов к раскомментированию

---

## Этап 7 — Документация ✅ ВЫПОЛНЕН

- [x] `CONTRIBUTING.md` — локальный запуск, переменные окружения, директория проекта, static assets workflow, тесты, code style, PR flow
- [x] `CHANGELOG.md` — формат Keep a Changelog, история версий 1.0.0 → 1.3.0 + Unreleased
- [x] Bruno API collection — 35 эндпоинтов в `bruno/` (auth/, portfolio/, profile/, admin/, misc/) + environments (local/production)
- [x] `docs/architecture.md` — C4 Level 2: container diagram, application layers, ER-диаграмма, sequence диаграммы (auth 2FA, MOEX update), cache strategy, security flow

---

## Этап 8 — Архитектура и Безопасность ✅ ВЫПОЛНЕН

> Цель: Оптимизация стабильности работы в Production, исправление скрытых багов расчётов и закрытие уязвимостей 2FA / Webhook.

### 8.1 Безопасность и Бизнес-логика
- [x] **Инвалидация OTP при ошибке** (`verify_otp` сгорает при любой первой попытке для защиты от brute-force)
- [x] **Проверка подлинности вебхука Telegram** (секретный токен в URL для защиты от спуфинга)
- [x] **Исправление купонов в Налоговом Отчёте** (учет купонов по проданным бумагам `sold_bonds`)

### 8.2 Архитектурный рефакторинг и Произвидительность
- [x] **Выделенный планировщик** (вынос APScheduler из процесса Flask/Gunicorn во избежание дублирования)
- [x] **Кэширование Купонного Календаря** (кэш на 12 часов в `moex_service.py` для устранения N+1 HTTP-запросов к MOEX)
- [x] **Исправление средневзвешенного YTM** (корректная формула расчета без учета бумаг с пустым YTM)
- [x] **Redis для Circuit Breaker** (перенос состояния предохранителя из памяти процесса в общий кэш во избежание сплит-брейна)
- [x] **Пагинация в скринере** (устранение логической ошибки "Limit before Filter")

---

## Этап 9 — Новые возможности и улучшения UI (v1.5.0) ✅ ВЫПОЛНЕН

> Цель: Повышение удобства работы с активами, отображение аватарок и плавность переключения тем.

### 9.1 Функционал портфеля
- [x] **Столбец «Текущая цена»**: Добавлен в основную таблицу имеющихся активов на странице `/portfolio` (как в HTML, так и в динамическом рендеринге в JS).
- [x] **Частичная продажа облигаций**: Возможность указать объем при продаже. Авто-разделение лота, корректный пересчет P&L и комиссии в реальном времени, а также ведение раздельных записей в архиве сделок.
- [x] **Заметки к позициям**: Сохранение детальных заметок для каждого лота в портфеле через модальное окно.

### 9.2 Обновление UI/UX
- [x] **Аватарка в сайдбаре**: Рендеринг загруженной аватарки пользователя (`<img>` c `object-fit: cover`) в нижнем левом углу панели навигации вместо стандартных текстовых инициалов.
- [x] **Анимация смены тем**: Внедрение View Transitions API в `toggleTheme` (сглаженное перетекание) и плавные CSS-переходы (250мс fallback) для всех ключевых элементов интерфейса.

---

## Этап 11 — Архитектура, дюрация, алерты, HHI и тесты (v2.1.0) ✅ ВЫПОЛНЕН

> Цель: Архитектурная миграция на паттерн Application Factory, повышение безопасности CSP, вынос логики разбора в сервисы, реализация расширенной аналитики и алертов, расширение покрытия тестами до 100+ автотестов.

### 11.1 Архитектурный рефакторинг и безопасность
- [x] **Application Factory**: Flask приложение переведено на паттерн `create_app()`.
- [x] **Кроссплатформенность Windows**: Изолирован APScheduler и убран `fcntl` для корректного запуска на Windows.
- [x] **Разделение логики импорта**: Логика парсинга отчетов Excel/CSV полностью вынесена в `services/import_service.py`.
- [x] **Nonce-based CSP**: Реализована динамическая CSP (`style-src 'self' 'nonce-{nonce}'`), исключающая уязвимости `'unsafe-inline'`.
- [x] **Чистые ORM функции**: Функция `build_portfolio_entry` избавлена от побочных эффектов вызова `db.session.commit()`.
- [x] **TTL кэширование Sharpe/Tax**: Реализовано кэширование в `blueprints/analytics.py` с инвалидацией кэша при операциях с портфелем.

### 11.2 Новые финансовые и технические фичи
- [x] **Дюрация облигаций**: Добавлен расчет дюрации Маколея и модифицированной дюрации.
- [x] **Индекс HHI**: Анализ концентрации/диверсификации портфеля по активам, эмитентам и валютам по формуле Херфиндаля-Хиршмана.
- [x] **SVG Sparklines**: Pure-python легковесный генератор SVG микро-графиков цен за 30 дней.
- [x] **Ценовые алерты (Price Alerts)**: Система CRUD (БД-модель + API + фоновая проверка котировок).
- [x] **Прометеус-метрики**: Реализован эндпоинт `/metrics` для экспорта системных и бизнес-показателей.

### 11.3 Тестирование и автосборка
- [x] **101 автотест**: Добавлены тесты на все новые фичи.
- [x] **Circuit Breaker Mock**: Написан интеграционный тест с имитацией кэша для надежной проверки переключения предохранителя при сбоях.
- [x] **Минификация статики**: Перегенерация минимизированных JS/CSS ресурсов через `build_assets.py`.

---

## Этап 12 — Настройки, уведомления, админ рассылка (v2.2.0) ✅ ВЫПОЛНЕН

> Цель: Пользовательские настройки, управление уведомлениями, административная рассылка, улучшение UX.

### 12.1 Разделение активности
- [x] **Категории**: `AuditLog.category` (account / portfolio), индекс `ix_audit_user_category`
- [x] **Фильтры в UI**: кнопки «Все / Аккаунт / Портфель» в журнале действий
- [x] **Расширенные метки**: bond_add, bond_sell, bond_delete, import_ok/fail, alert_triggered, portfolio_reset, settings_update

### 12.2 Вкладка «Настройки» в профиле
- [x] **Тема оформления**: system / light / dark с instant preview и сохранением на сервере
- [x] **Время уведомлений**: `<input type="time">` с авто-определением часового пояса через `Intl.DateTimeFormat`
- [x] **Оферты**: за 7 / 14 / 30 дней / не присылать
- [x] **Pydantic-валидация**: `SettingsUpdate` в `schemas/profile.py`

### 12.3 Bot settings (inline keyboard)
- [x] **`/settings`** — inline keyboard с toggle уведомлений, выбором времени, дней оферт, навигацией «Назад»
- [x] **`bot/db.py`** — `get_user_settings()`, `update_user_setting()`, колонки `notif_time`, `oferta_advance_days`

### 12.4 OTP copy button
- [x] **`copy_text`** inline keyboard button (Telegram Bot API 6.7+)
- [x] **`<code>` блок** вместо plain text для кода подтверждения

### 12.5 Admin broadcast
- [x] **`POST /api/admin/broadcast`** — рассылка на сайт и/или Telegram, выбор получателей
- [x] **`SiteNotification`** модель, polling `unread_count` каждые 60с, синий badge
- [x] **Admin UI**: вкладка «Рассылка» с формой получателей/каналов

### 12.6 Flatpickr date picker
- [x] **Flatpickr 4.6.13** с русской локализацией вместо стандартных `<input type="date/time">`
- [x] **Кастомная тема** (`flatpickr-theme.css`) на CSS-переменных, автоматическая тёмная тема
- [x] **Авто-инициализация** через MutationObserver, хелперы `fpSet()` / `fpClear()`

### 12.7 Тестирование
- [x] **45 новых тестов** в `tests/test_stage12.py` (итого 149)
- [x] **Рефакторинг**: profile.py — 0 прямых обращений к DB, 2FA enable/disable → сервис

### 12.8 Миграция
- [x] **`stage12_settings_notif_activity`** — идемпотентная (`IF NOT EXISTS`); user settings, audit_log.category, site_notifications

---

## Этап 13 — Мультиключевой импорт и Валюты (v2.3.0) ⏳ ЗАПЛАНИРОВАН

> Цель: Поддержка замещающих валютных облигаций, золотых бумаг и максимальное упрощение ввода активов.

### 13.1 Валютные облигации (CNY, USD, EUR)
- [ ] **Мультивалютная БД**: поддержка разных валют номинала
- [ ] **Замещающие CNY-облигации**: юаневые бумаги (Роснефть, Полюс, Металлоинвест)
- [ ] **Динамическая конвертация**: курсы USDRUB / CNYRUB с валютной секции MOEX
- [ ] **Валютная переоценка**: пересчёт P&L в RUB по актуальному курсу

### 13.2 «Золотые» облигации (GLD)
- [ ] **Золотой номинал**: котировки `GLDRUB_TOM` для облигаций в золоте
- [ ] **Амортизация в золоте**: пересчёт купонов с привязкой к весу драгметалла

### 13.3 Интеграция с брокерскими отчетами
- [ ] **Парсинг PDF**: импорт отчётов Сбер, Финам

---

## Дизайн-референсы

| Продукт | Что взяли |
|---------|-----------|
| **Linear.app** | Sidebar, typography, micro-animations |
| **Vercel Dashboard** | Metric cards, dark theme, spacing |
| **Stripe Dashboard** | Data tables, charts, color system |
| **Liveblocks** | Landing gradient, glassmorphism |
| **Resend** | Minimalist forms, toast notifications |
| **Clerk** | Profile page, auth forms |

---

## Принципы дизайна InvestTrack

1. **Данные — главное.** UI служит данным, не наоборот.
2. **Единая сетка.** Spacing = множители 4px. Никаких случайных отступов.
3. **Тёмная тема первична.** Финансовые дашборды используются вечером.
4. **Motion = информация.** Анимации показывают изменение состояния, не развлекают.
5. **Accessibility.** WCAG 2.1 AA: контраст ≥ 4.5:1, focus видим.
6. **Производительность.** LCP < 1.5s, CLS < 0.1.
