# InvestTrack — Полный Roadmap

> **Ветка активной разработки:** `update-fr`
> Последнее обновление: 2026-05-23

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
| 7 | Документация | 🔲 В плане |

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

## Этап 7 — Документация 🔲 В ПЛАНЕ

- [ ] `CONTRIBUTING.md` — как запустить локально, code style
- [ ] `CHANGELOG.md` — формат Keep a Changelog
- [ ] Bruno/Postman collection для всех API эндпоинтов
- [ ] Architecture diagram (C4 Level 2)

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
