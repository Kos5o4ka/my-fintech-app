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
| 4 | Новые фичи | 🔲 В плане |
| 5 | Тестирование | 🔲 В плане |
| 6 | DevOps и деплой | 🔲 В плане |
| 7 | Документация | 🔲 В плане |

---

## Этап 0 — Premium Редизайн ✅ ВЫПОЛНЕН

> Цель: UI, который выглядит как продукт лучшей дизайн-студии уровня Linear, Vercel, Stripe Dashboard.
> Ветка `update-fr`, каждый пункт — отдельный коммит.

### 0.1 Дизайн-система — фундамент

- [x] **Типографика**: Inter подключён через Google CDN (`font-family: 'Inter'`)
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

### 0.3 Лендинг (`/`) — полный редизайн

- [x] **Hero секция** — CSS animated gradient blobs (3 слоя), тёмный фон #040d1a
- [x] **Glassmorphism login card** — `backdrop-filter: blur(20px)`, floating labels
- [x] **Кнопка входа** — gradient, loading spinner при сабмите
- [ ] Feature grid под hero — 3 колонки с hover-эффектом *(можно добавить позже)*
- [ ] Footer с версией и ссылками *(можно добавить позже)*

### 0.4 Dashboard — полный редизайн

- [x] **Metric cards** — SVG-иконка в градиентном круге, accent-полоска снизу
- [x] **countUp анимации** — все числовые значения считают при загрузке (`Common.countUp`)
- [x] **Купонный календарь** — timeline стиль, badge с датой
- [x] **Best / Worst позиции** — карточки с P&L
- [x] **Summary row** — Позиций / Доход 90д / Доход год
- [ ] Area chart P&L с переключателем 7д/30д/YTD *(на следующий итерацию)*
- [ ] Donut chart распределения по эмитентам *(на следующую итерацию)*

### 0.5 Страница портфеля — редизайн

- [x] **Stats strip** — 4 карточки с tabbed period selector для дохода
- [x] **Sticky table header** с `backdrop-filter: blur(8px)`
- [x] **Hover строки** — лёгкий accent background
- [x] **Поиск с иконкой лупы** над таблицей
- [x] **Drawer "Добавить облигацию"** — slide-in 400px, backdrop blur, телепортируется в `body`
- [x] **ISIN autocomplete** — live поиск `/api/search_bond`, превью карточки
- [x] **FAB кнопка** для mobile
- [x] **Sell modal** с live P&L preview (обновляется при вводе цены/комиссии)
- [x] **Mobile card-view** — таблица → карточки на < 767px с `data-label`
- [ ] Sparklines в колонке цены *(сложно без отдельного API)*
- [ ] Сортировка по клику на заголовок *(добавить в Stage 1)*

### 0.6 Страница профиля — редизайн

- [x] **Hero секция** — gradient banner (#1e3a8a → #2563eb → #7c3aed), аватар 80px
- [x] **Role badge** с SVG-иконкой
- [x] **Tabbed layout** — 3 вкладки: Профиль / Безопасность / Уведомления
- [x] **Upload zone** — drag-to-upload стиль с превью имени файла
- [x] **Info rows** — Логин / Роль / Email
- [x] **Custom toggle switch** для email-уведомлений
- [ ] Activity feed (последние сделки) *(Stage 4)*
- [ ] Quick stats в hero (X облигаций, стоимость) *(Stage 4)*

### 0.7 Тёмная тема — доработка

- [x] Все новые компоненты проверены в dark mode
- [x] CSS-переменные `--surface-0..3` для dark (значения в `[data-bs-theme="dark"]`)
- [x] Переключатель темы в sidebar + mobile bottom bar
- [x] Anti-FOUC inline script в `<head>`
- [x] Сохранение предпочтения в `localStorage`
- [ ] Анимация sun↔moon при переключении *(косметика)*

### 0.8 Micro-interactions и анимации

- [x] **countUp** — `Common.countUp()` с easeOutExpo, ru-RU локаль
- [x] **Toast с progress bar** — 3px полоска, `@keyframes toastProgress`
- [x] **fadeInUp** с задержками — все карточки появляются каскадно
- [x] **Button pressed** — `transform: scale(.985)` через CSS
- [x] **Hover states** на всех интерактивных элементах
- [x] **Empty states** — SVG иллюстрация в пустом портфеле
- [ ] Page transitions fade при навигации *(добавить)*
- [ ] Form validation shake-анимация *(Stage 3)*
- [ ] Skeleton loaders для медленных API *(Stage 2)*

### 0.9 Производительность

- [x] **Build system** — `build_assets.py` минифицирует CSS + JS в `.min.*`
- [x] `prefers-reduced-motion: reduce` — отключает все анимации
- [ ] Bootstrap локально вместо CDN *(Stage 2)*
- [ ] CSS `contain: layout style` для карточек *(Stage 2)*

### 0.10 Адаптивность (Mobile-first)

- [x] Sidebar → bottom bar на `< 768px`
- [x] Metric cards: 2 колонки на mobile, 4 на desktop
- [x] Таблица портфеля: card-view на `< 767px`
- [x] FAB кнопка "Добавить" на mobile
- [ ] Drawer → full-screen на `< 480px` *(добавить)*
- [ ] Swipe-to-dismiss для toast *(Stage 3)*

---

## Этап 1 — Архитектурный рефакторинг ✅ ВЫПОЛНЕН

### 1.1 Сервисный слой

- [x] Создать `services/` директорию:
  - `portfolio_service.py` — P&L, расчёт доходности, купонный доход
  - `moex_service.py` — кэшированные обращения к MOEX ISS API
  - `user_service.py` — аватары, email-настройки пользователей
- [x] Blueprints = только HTTP-слой: parse → call service → respond
- [x] Вынести бизнес-логику из `blueprints/portfolio.py`

### 1.2 Типизация

- [x] Python type hints во всех функциях (`blueprints/`, `moex.py`, `models.py`, `services/`)
- [x] Pydantic схемы валидации в `schemas/` для входящих JSON-запросов
  - `AddBondRequest`, `SellBondRequest`, `ScreenerRequest`
  - `LoginRequest`, `ChangePasswordRequest`
  - `EmailSettingsRequest`
- [x] `constants.py` — все магические числа (TTL, таймауты, налоговые ставки, лимиты)

### 1.3 База данных

- [x] Alembic-миграции (flask-migrate уже был установлен, добавлена новая миграция `stage1_bond_portfolio_fields`)
- [x] Поле `updated_at` в `BondPortfolio`
- [x] Поле `currency` (RUB/USD/EUR) для валютных облигаций
- [x] Индекс `ix_bp_isin` на `BondPortfolio.isin`

### 1.4 Конфигурация

- [x] `DevelopmentConfig`, `TestingConfig`, `ProductionConfig` в `config.py`
- [x] Валидация обязательных env-vars при старте (`ProductionConfig.validate()`)
- [x] Убрать небезопасный fallback `'change-me-before-production'`
- [x] `.env.production.example` с документацией всех переменных

---

## Этап 2 — Оптимизация ✅ ВЫПОЛНЕН

### 2.1 База данных

- [x] Пагинация в `/api/portfolio` и `/api/portfolio/history` (`page`, `per_page`, метаданные)
- [x] `bulk_update_mappings()` вместо N UPDATE в APScheduler (один SQL)
- [x] Connection pooling в `ProductionConfig`: `pool_size=5`, `max_overflow=10`, `pool_recycle=1800`

### 2.2 Кэширование

- [x] **FileSystemCache** вместо SimpleCache — хранит на диске, не расходует RAM,
      работает между воркерами; Redis остаётся опциональным через `REDIS_URL`
- [x] TTL 15 мин для `/api/portfolio_stats` (ключ `portfolio_stats:{user_id}`)
- [x] `ETag` + `Cache-Control: private, max-age=60` для `/api/portfolio`
- [x] Инвалидация кэша `_bust_user_cache()` при add_bond / sell_bond

### 2.3 MOEX API

- [x] Retry с exponential backoff через `tenacity` (3 попытки: 1/2/4 сек) — было в Stage 1
- [x] Явный `timeout=10` — было в Stage 1
- [x] **Circuit breaker**: 5 ошибок подряд → пауза 10 мин (thread-safe, `_fetch_json`)

### 2.4 Frontend

- [x] Debounce 300ms для поиска — уже был в коде
- [ ] Bootstrap локально вместо CDN *(отложено — не критично для 2 ГБ сервера)*
- [ ] `rel="preload"` для Inter *(отложено)*

---

## Этап 3 — Безопасность + Telegram-бот ✅ ВЫПОЛНЕН

### 3.0 Telegram-бот (уведомления + 2FA)

> Поля `telegram_chat_id` и `telegram_notifications` уже в модели User (миграция d4e5f6a7b8c9).

- [x] Создать бота через @BotFather → `TELEGRAM_BOT_TOKEN` в `.env`
- [x] `services/telegram_service.py` — `send_message`, `generate_otp`, `verify_otp`, `generate_link_token`, deep-link
- [x] `blueprints/telegram_bot.py` — вебхук `/api/telegram/webhook` (освобождён от CSRF)
- [x] Привязка аккаунта: Профиль → «Привязать» → deep-link → `/start <token>` в боте
- [x] Уведомления о купонах через бота (APScheduler, параллельно с email)
- [x] **2FA через Telegram**: при входе бот присылает 6-значный OTP-код (pending-токен, TTL 5 мин)
- [x] `/api/auth/verify_2fa` — новый эндпоинт для проверки кода

### 3.1 Аутентификация

- [x] 2FA через Telegram-бот *(см. 3.0)*
- [x] Audit log: `AuditLog` модель (action, user_id, ip, UA, details, created_at) — миграция e5f6a7b8c9d0
- [x] Записи login_ok / login_fail / login_2fa_sent / login_2fa_fail / logout / change_password

### 3.2 Сессии

- [x] `PERMANENT_SESSION_LIFETIME = timedelta(days=7)` в Config
- [x] `session.permanent = True` при логине
- [x] Idle timeout 30 мин — `before_request` проверяет `_last_active`

### 3.3 HTTP-заголовки

- [x] `Strict-Transport-Security: max-age=31536000; includeSubDomains` (только production)
- [x] `Permissions-Policy: geolocation=(), camera=(), microphone=(), payment=()`
- [x] Убрать заголовок `Server: Werkzeug/...` через `response.headers.remove("Server")`

### 3.4 Файлы (аватары)

- [x] Pillow: открытие → `img.verify()` → convert RGB → thumbnail 400×400 → save JPEG (strip EXIF)
- [x] UUID-имена файлов (`uuid4().hex + .jpg`) — нет path traversal, нет привязки к username
- [x] Удаление предыдущего аватара при загрузке нового

---

## Этап 4 — Новые функции

### 4.1 Аналитика портфеля

- [ ] Area chart P&L с переключателем 7д/30д/90д/YTD на дашборде
- [ ] Donut chart: распределение по эмитентам (топ-5 + "Остальные")
- [ ] Бенчмарк: доходность портфеля vs RGBI индекс
- [ ] Sharpe Ratio (продвинутый режим)

### 4.2 Скринер и поиск

- [ ] Скринер облигаций: фильтры YTM, дюрация, эмитент, тип купона
- [ ] Watchlist — избранные бумаги без добавления в портфель *(UI уже есть)*
- [ ] Сравнение двух облигаций на одном графике

### 4.3 Уведомления

- [ ] Email: за 1 день до купона, при погашении, при изменении цены > 5%
- [ ] In-app notification bell
- [ ] Activity feed в профиле (последние 10 действий)

### 4.4 Расширенные данные

- [ ] `Transaction` модель: частичные покупки/продажи
- [ ] Валютные облигации (курс ЦБ РФ)
- [ ] Поле `notes` — заметки к каждой позиции

### 4.5 Отчётность

- [ ] Excel `.xlsx` с форматированием и формулами (`openpyxl`)
- [ ] Налоговый отчёт: НДФЛ 13% с купонов и прибыли
- [ ] PDF-отчёт через `weasyprint`

---

## Этап 5 — Тестирование

- [ ] `pytest-cov` → цель ≥ 85%
- [ ] Интеграционные тесты с реальной PostgreSQL через `testcontainers`
- [ ] E2E через Playwright: логин, добавить/продать, экспорт
- [ ] `pre-commit` хуки: `ruff` + `mypy` + `bandit`
- [ ] Property-based тесты P&L через `hypothesis`

---

## Этап 6 — DevOps и деплой

- [ ] Multi-stage `Dockerfile` (builder + slim runtime)
- [ ] `docker-compose.yml`: app + PostgreSQL + Redis + Nginx
- [ ] `HEALTHCHECK` endpoint `/health`
- [ ] Nginx reverse proxy (SSL, gzip, static files)
- [ ] Gunicorn: `--workers 4 --threads 2`
- [ ] Let's Encrypt + certbot
- [ ] Sentry для ошибок
- [ ] GitHub Actions: lint → test → build → deploy

---

## Этап 7 — Документация

- [ ] `CONTRIBUTING.md` — как запустить локально, code style
- [ ] `CHANGELOG.md` — формат Keep a Changelog
- [ ] Docstrings в `moex.py` и `services/`
- [ ] Bruno/Postman collection для API
- [ ] Architecture diagram (C4 Level 2)

---

## Дизайн-референсы (вдохновение)

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
