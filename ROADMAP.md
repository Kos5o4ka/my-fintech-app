# InvestTrack — Полный Roadmap

> **Ветка активной разработки:** `update-fr`
> Последнее обновление: 2026-05-22

---

## Статус по этапам

| Этап | Тема | Статус |
|------|------|--------|
| 0 | Premium Редизайн (UI/UX) | 🔲 В плане |
| 1 | Архитектурный рефакторинг | 🔲 В плане |
| 2 | Оптимизация и кэш | 🔲 В плане |
| 3 | Безопасность | 🔲 В плане |
| 4 | Новые фичи | 🔲 В плане |
| 5 | Тестирование | 🔲 В плане |
| 6 | DevOps и деплой | 🔲 В плане |
| 7 | Документация | 🔲 В плане |

---

## Этап 0 — Premium Редизайн ⭐ ПРИОРИТЕТ

> Цель: UI, который выглядит как продукт лучшей дизайн-студии уровня Linear, Vercel, Stripe Dashboard.
> Всё делается в ветке `update-fr`, каждый пункт — отдельный коммит.

### 0.1 Дизайн-система — фундамент

- [ ] **Типографика**: подключить `Inter` через `@font-face` (локальная копия, не Google CDN) с вариативным начертанием
- [ ] **Полная замена CSS-переменных** в `variables.css`:
  - Новая палитра: `--color-*` (10 ступеней для каждого цвета: slate, blue, emerald, violet, amber)
  - Семантические токены: `--surface-1..4`, `--text-primary`, `--text-secondary`, `--text-tertiary`
  - Тени: `--shadow-xs`, `--shadow-sm`, `--shadow-md`, `--shadow-lg`, `--shadow-xl`, `--glow-blue`, `--glow-green`
  - Анимации: `--duration-fast: 120ms`, `--duration-base: 200ms`, `--duration-slow: 350ms`, `--ease-spring`
  - Радиусы: `--radius-xs: 4px` до `--radius-2xl: 20px`
- [ ] **Базовые компоненты** в `static/css/design-system.css`:
  - Badge, Pill, Tag — 3 варианта с иконкой слева
  - Avatar — круглый, с инициалами как fallback
  - Tooltip — кастомный, без Bootstrap (pure CSS + JS)
  - Divider, Separator
  - Progress bar — анимированный gradient
  - Chip/Tag с кнопкой удаления

### 0.2 Навигация — полный редизайн

- [ ] **Убрать текущий navbar** — заменить на `sidebar` (desktop) + `bottom-bar` (mobile):
  - Desktop: фиксированная левая панель 220px с логотипом, иконками + подписями, разделителями
  - Mobile: нижняя панель с 4 иконками (Home, Portfolio, Profile, Admin)
  - Micro-animation: активный пункт подсвечивается с `transform: scale(1.02)` и `glow`-эффектом
- [ ] **Логотип**: заменить emoji `📈` → SVG логотип с `IT` монограммой + трендовая линия вверх
- [ ] **User widget** в sidebar: аватар + имя + роль (admin / user), клик → /profile
- [ ] **Быстрые действия** в sidebar: кнопка "Добавить облигацию" + "Экспорт CSV"
- [ ] **Collapsed sidebar** на 1280px: иконки без текста + tooltip при hover

### 0.3 Лендинг (`/`) — полный редизайн

- [ ] **Hero секция** — full-viewport с animated gradient mesh background:
  - CSS-анимированные gradient blobs (3 слоя: синий, фиолетовый, cyan) без JavaScript
  - Заголовок с `letter-spacing` и word-by-word `fadeInUp` анимацией при загрузке
  - Подзаголовок + CTA-кнопки в одну строку: "Войти" (primary) + "Посмотреть демо" (ghost)
  - Floating mockup: карточка-превью дашборда с shimmer-эффектом (CSS only)
- [ ] **Форма входа** справа:
  - Glassmorphism-карточка (`backdrop-filter: blur(20px)`, `background: rgba(..., .08)`)
  - Floating labels вместо обычных (`<label>` анимируется вверх при фокусе)
  - Кнопка "Войти" — gradient с shimmer на hover, loading spinner при сабмите
  - Transition между состояниями (login → loading → success) через CSS classes
- [ ] **Feature grid** под hero — 3 колонки:
  - Иконка (SVG, не emoji), заголовок, описание
  - Hover: карточка поднимается (`translateY(-4px)`) с усиленной тенью
- [ ] **Статистика** в строку: "N облигаций" / "N пользователей" / "Данные MOEX real-time" — с count-up анимацией
- [ ] **Footer**: логотип, ссылки, версия, "Данные: MOEX ISS API"

### 0.4 Dashboard — полный редизайн

- [ ] **Metric cards** — кардинальный редизайн:
  - Размер: высота 120px, padding 24px
  - Иконка: SVG в цветном круге 40px (`background: linear-gradient(...)`)
  - Главное значение: `font-size: 2rem; font-weight: 800; font-variant-numeric: tabular-nums`
  - Дельта под значением: `▲ +2.4%` зелёным / `▼ -1.2%` красным с `font-size: 0.75rem`
  - Тонкая полоска-акцент снизу (4px) вместо текущих 3px сверху
  - Micro-animation: значение "считает" (`countUp`) при каждой загрузке
  - `will-change: transform` + `transform: translateZ(0)` для GPU-ускорения
- [ ] **График P&L** на дашборде:
  - Area chart (Chart.js) с gradient fill (от accent-цвета к прозрачному)
  - Кастомный tooltip-попап (тёмный, с blur)
  - Анимация рисования линии при появлении (`clip-path` reveal)
  - Переключатель периода: 7д / 30д / 90д / YTD
- [ ] **Купонный календарь** — редизайн:
  - Timeline-стиль: вертикальная линия, события с датой слева
  - Цветовая кодировка: ближайшие 7 дней — зелёный, 8-30 — синий, дальше — серый
  - Пустое состояние: красивый SVG illustration + текст
- [ ] **Best/Worst позиции** — horizontal bar chart вместо текста:
  - Top 3 лучших и Top 3 худших позиций
  - Animated bars при загрузке
- [ ] **Widget карта распределения** — donut chart (без текста в центре, подписи снаружи):
  - По эмитентам (топ-5 + "Остальные")
  - Hover: сегмент увеличивается, показывает % и сумму

### 0.5 Страница портфеля — редизайн

- [ ] **Sidebar слева** — редизайн виджетов:
  - Карточка стоимости: огромное число, YTM и P&L в строку под ним
  - Купонный доход: кнопки периода → tabbed (underline-стиль), значение с анимацией
  - Форма добавления → вынести в `drawer` (боковая панель, slide-in слева), не в sidebar
- [ ] **Таблица позиций** — полный редизайн:
  - Sticky header с `backdrop-filter: blur(8px)`
  - Hover строки: left-border 2px синий + лёгкий background
  - Статус-иконки: зелёная точка (active) / серая (погашена)
  - Sprkline мини-график (7 дней, inline SVG) в колонке "Цена"
  - Сортировка по клику на заголовок с анимированными стрелками
  - Drag-to-reorder строки (опционально)
  - Виртуальный скролл при 100+ строках
- [ ] **Поиск и фильтры** — top bar над таблицей:
  - Инлайн поиск с иконкой лупы и кнопкой очистки
  - Dropdown фильтры: "Только активные" / "Проданные" / "Все"
  - Chip-теги для активных фильтров с кнопкой ✕
- [ ] **Drawer "Добавить облигацию"**:
  - Slide-in с правой стороны (400px), backdrop blur
  - Step 1: Поиск ISIN с live-autocomplete и превью карточки
  - Step 2: Заполнение деталей (кол-во, цена покупки, дата)
  - Анимация перехода между шагами: `slide + fade`
  - Confirm button с loading state → success animation (checkmark)
- [ ] **Модал продажи** — редизайн:
  - Двухколоночный layout: слева — детали позиции, справа — форма
  - P&L preview: меняется в реальном времени при вводе цены продажи
  - Цветовой индикатор: зелёный (прибыль) / красный (убыток)

### 0.6 Страница профиля — редизайн

- [ ] **Hero секция** профиля:
  - Аватар большой (96px) с gradient border + кнопка замены (overlay при hover)
  - Имя пользователя, роль-badge, дата регистрации
  - Quick stats: "В портфеле X облигаций", "Стоимость: Y ₽", "Участник с: Z"
- [ ] **Секции** в виде аккордеона или tabbed:
  - "Личные данные" — форма редактирования
  - "Безопасность" — смена пароля + 2FA (заглушка)
  - "Уведомления" — toggles
  - "Опасная зона" — удаление аккаунта (красный раздел)
- [ ] **Activity feed** — последние 10 действий (покупки/продажи) в timeline-стиле

### 0.7 Тёмная тема — доработка

- [ ] Проверить каждый новый компонент в dark mode — никакого "белого на белом"
- [ ] Новые CSS-переменные для dark: `--surface-1: #0d1117`, `--surface-2: #161b22`, `--surface-3: #1c2128`
- [ ] Glow-эффекты в тёмной теме: `box-shadow: 0 0 20px rgba(var(--accent-rgb), .15)`
- [ ] Переключатель темы: анимация sun↔moon SVG иконки (rotate + scale)
- [ ] Сохранение предпочтения + respect `prefers-color-scheme` при первом визите

### 0.8 Micro-interactions и анимации

- [ ] **Page transitions**: `fade` при навигации (CSS class toggle)
- [ ] **Button states**: pressed (`scale(.97)`), loading (spinner), success (checkmark), error (shake)
- [ ] **Form validation**: shake-анимация при ошибке, зелёная галочка при успехе
- [ ] **Toast notifications**: slide-in снизу-справа, auto-dismiss с progress bar
- [ ] **Skeleton loaders**: анимированные placeholder блоки (shimmer) для каждого компонента
- [ ] **Number animations**: `countUp` для всех числовых значений при загрузке страницы
- [ ] **Hover states**: каждый интерактивный элемент должен иметь заметный hover (cursor: pointer, transition)
- [ ] **Focus states**: красивый focus ring (`outline: 2px solid var(--accent); outline-offset: 2px`) для a11y
- [ ] **Empty states**: кастомные SVG иллюстрации для: пустой портфель, нет купонов, ошибка загрузки

### 0.9 Производительность дизайна

- [ ] CSS `contain: layout style` для карточек — изоляция reflow
- [ ] `will-change` только на анимируемые свойства, убирать после завершения
- [ ] `font-display: swap` для кастомных шрифтов
- [ ] Critical CSS inline в `<head>` (navbar + hero fold)
- [ ] Убрать Bootstrap с CDN → собрать только нужные модули локально (50% меньше CSS)
- [ ] SVG-спрайт для иконок вместо emoji
- [ ] CSS Houdini `@property` для анимированных CSS-переменных (gradient transitions)

### 0.10 Адаптивность (Mobile-first)

- [ ] Breakpoints: 320px / 480px / 768px / 1024px / 1280px / 1536px
- [ ] Sidebar → bottom bar на < 768px
- [ ] Metric cards: 2 колонки на mobile, 4 на desktop
- [ ] Таблица портфеля: card-view на mobile (каждая строка → карточка)
- [ ] Drawer (форма добавления) → full-screen modal на mobile
- [ ] Touch targets минимум 44×44px для всех кнопок
- [ ] Swipe-to-dismiss для toast и модалок

---

## Этап 1 — Архитектурный рефакторинг

### 1.1 Сервисный слой

- [ ] Создать `services/` директорию:
  - `portfolio_service.py` — P&L, расчёт доходности, купонный доход
  - `moex_service.py` — все обращения к MOEX ISS API
  - `user_service.py` — CRUD пользователей, аватары, смена пароля
- [ ] Blueprints = только HTTP-слой: parse → call service → respond
- [ ] Вынести бизнес-логику из `blueprints/portfolio.py` (сейчас 400+ строк)

### 1.2 Типизация

- [ ] Python type hints во всех функциях (`blueprints/`, `moex.py`, `models.py`, `services/`)
- [ ] Pydantic схемы валидации в `schemas/` для входящих JSON-запросов
- [ ] `constants.py` — все магические числа (лимиты, TTL, размеры файлов)

### 1.3 База данных

- [ ] Alembic-миграции вместо `db.create_all()` (flask-migrate уже установлен)
- [ ] Поле `updated_at` в `BondPortfolio`
- [ ] Поле `currency` (RUB/USD/EUR) для валютных облигаций
- [ ] Модель `Transaction` для истории покупок/продаж
- [ ] Индекс на `BondPortfolio.isin`

### 1.4 Конфигурация

- [ ] `DevelopmentConfig`, `TestingConfig`, `ProductionConfig` в `config.py`
- [ ] Валидация обязательных env-vars при старте (если нет `SECRET_KEY` — падать)
- [ ] Убрать fallback `'change-me-before-production'`
- [ ] `.env.production.example`

---

## Этап 2 — Оптимизация

### 2.1 База данных

- [ ] Пагинация в `/api/portfolio` и `/api/portfolio/history`
- [ ] `bulk_update_mappings()` вместо N отдельных UPDATE в APScheduler
- [ ] Connection pooling: `SQLALCHEMY_POOL_SIZE`, `SQLALCHEMY_MAX_OVERFLOW`

### 2.2 Кэширование

- [ ] Redis вместо SimpleCache (shared между воркерами Gunicorn)
- [ ] TTL 5 мин для `/api/portfolio_stats`
- [ ] `ETag` + `Cache-Control` для read-only API ответов
- [ ] Инвалидация кэша при изменении портфеля

### 2.3 MOEX API

- [ ] Retry с exponential backoff через `tenacity` (3 попытки: 1/2/4 сек)
- [ ] Явный `timeout=10` на все `requests.get()` (сейчас может зависнуть)
- [ ] Circuit breaker: если MOEX недоступен 5 раз подряд — пауза 10 мин
- [ ] Ограничение параллельных запросов в APScheduler через Semaphore

### 2.4 Frontend

- [ ] Debounce 300ms для поиска облигаций
- [ ] `IntersectionObserver` для lazy-load истории торгов
- [ ] Bootstrap → только нужные модули, без CDN
- [ ] `rel="preload"` для Inter шрифта и critical CSS

---

## Этап 3 — Безопасность

### 3.1 Аутентификация

- [ ] Страница смены пароля (`/profile` → форма)
- [ ] 2FA через TOTP (`pyotp` + Google Authenticator) — финтех требует
- [ ] Audit log: каждый login/logout/смена пароля → таблица с IP, UA, timestamp

### 3.2 Сессии

- [ ] `PERMANENT_SESSION_LIFETIME = timedelta(days=7)`
- [ ] Ротация session ID после логина (защита от session fixation)
- [ ] Idle timeout: автологаут через 30 мин неактивности

### 3.3 HTTP-заголовки

- [ ] `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- [ ] `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- [ ] Убрать заголовок `Server: Werkzeug/...`
- [ ] CSP: убрать CDN из `script-src`, перейти на `nonce`

### 3.4 Файлы

- [ ] Аватары → хранить вне `static/`, отдавать через `@login_required`
- [ ] Ре-энкод изображений через `Pillow` (убивает embedded payloads)
- [ ] Rate limit на загрузку файлов: 5/час на пользователя
- [ ] UUID-имена для аватаров

---

## Этап 4 — Новые функции

### 4.1 Аналитика портфеля

- [ ] Средневзвешенный YTM по всему портфелю
- [ ] Виджет купонного дохода: 30/90/365 дней
- [ ] Donut chart: распределение по эмитентам и секторам
- [ ] Бенчмарк: доходность портфеля vs RGBI индекс
- [ ] Sharpe Ratio и стандартное отклонение (продвинутый режим)

### 4.2 Скринер и поиск

- [ ] Полнотекстовый поиск по ISIN, названию, эмитенту с debounce
- [ ] Скринер облигаций: фильтры YTM, дюрация, эмитент, тип купона, рейтинг
- [ ] Watchlist — избранные бумаги без добавления в портфель
- [ ] Сравнение двух облигаций на одном графике

### 4.3 Уведомления

- [ ] Email-уведомления через `flask-mail`:
  - За 1 день до купона (с суммой ₽)
  - При погашении облигации
  - При изменении цены > 5% за день
- [ ] In-app notification bell
- [ ] Настройки уведомлений в профиле

### 4.4 Расширенные данные

- [ ] `Transaction` модель: частичные покупки/продажи
- [ ] `broker_commission` при продаже для точного P&L
- [ ] Поддержка валютных облигаций (курс ЦБ РФ через `cbr.ru`)
- [ ] Поле `notes` — заметки к каждой позиции

### 4.5 Отчётность

- [ ] Excel `.xlsx` с форматированием, формулами, сводной таблицей (`openpyxl`)
- [ ] Налоговый отчёт: НДФЛ 13% с купонов и прибыли от продаж
- [ ] PDF-отчёт через `weasyprint` или `reportlab`

---

## Этап 5 — Тестирование

### 5.1 Покрытие

- [ ] `pytest-cov` → цель ≥ 85%
- [ ] Интеграционные тесты с реальной PostgreSQL через `testcontainers`
- [ ] E2E тесты через Playwright: логин, добавить/продать облигацию, экспорт

### 5.2 Качество кода

- [ ] `pre-commit` хуки: `ruff` + `mypy` + `bandit`
- [ ] Property-based тесты P&L через `hypothesis`
- [ ] Нагрузочное тестирование через `locust`

### 5.3 CI/CD

- [ ] GitHub Actions: `lint → typecheck → test → build → deploy`
- [ ] Тесты на каждый PR
- [ ] `safety check` (CVE в зависимостях)
- [ ] Coverage badge в README

---

## Этап 6 — DevOps и деплой

### 6.1 Контейнеризация

- [ ] Multi-stage `Dockerfile` (builder + slim runtime)
- [ ] `docker-compose.yml`: app + PostgreSQL + Redis + Nginx
- [ ] `HEALTHCHECK CMD curl -f http://localhost:5000/health`

### 6.2 Production

- [ ] Nginx как reverse proxy (SSL termination, gzip, static files)
- [ ] Gunicorn: `--workers 4 --threads 2 --worker-class gthread`
- [ ] Systemd unit для автозапуска
- [ ] Let's Encrypt + certbot

### 6.3 Мониторинг

- [ ] `GET /health` → `{"status":"ok","db":"ok","moex":"ok","cache":"ok"}`
- [ ] Sentry для отслеживания ошибок
- [ ] Prometheus метрики + Grafana dashboard
- [ ] Uptime monitoring

### 6.4 Логирование

- [ ] Структурированные JSON-логи через `structlog`
- [ ] `TimedRotatingFileHandler` (ежедневно, 30 дней)
- [ ] Логировать медленные запросы (> 500ms)

---

## Этап 7 — Документация

- [ ] `README.md` — Features, Quick Start, Architecture, API Reference
- [ ] `CONTRIBUTING.md` — как запустить локально, code style
- [ ] `CHANGELOG.md` — формат Keep a Changelog
- [ ] Docstrings в `moex.py` и `services/`
- [ ] Bruno/Postman collection для API
- [ ] Architecture diagram (C4 Level 2) в `/docs/architecture.md`

---

## Roadmap по спринтам

### Sprint 0 — Premium Редизайн (текущий, ветка `update-fr`)
> Цель: визуально безупречный продукт класса Linear/Vercel

**Неделя 1:**
- [ ] Дизайн-система: Inter шрифт + полная замена CSS-переменных
- [ ] SVG-логотип + SVG-спрайт для иконок
- [ ] Новый sidebar + bottom-bar для mobile
- [ ] Лендинг: gradient mesh background + glassmorphism форма

**Неделя 2:**
- [ ] Dashboard: новые metric cards + countUp + Area chart P&L
- [ ] Купонный timeline + доnut chart распределения
- [ ] Toast redesign + skeleton loaders redesign

**Неделя 3:**
- [ ] Portfolio: sticky header таблицы + hover states + sparklines
- [ ] Drawer "Добавить облигацию" (step-by-step)
- [ ] Модал продажи с live P&L preview

**Неделя 4:**
- [ ] Profile page redesign
- [ ] Dark mode доработка + switch анимация
- [ ] Micro-interactions: countUp, button states, form validation
- [ ] Mobile адаптация card-view для таблицы
- [ ] Финальный audit: lighthouse score ≥ 90 по всем метрикам

### Sprint 1 — Технический долг (2 нед.)
- Alembic миграции, SECRET_KEY валидация, retry MOEX, разделение конфига, тесты ≥ 85%

### Sprint 2 — Безопасность (2-3 нед.)
- Audit log, session lifetime, HSTS, аватары в защищённое место, Dockerfile

### Sprint 3 — UX-функции (3-4 нед.)
- Transaction модель, скринер, watchlist, email-уведомления, Excel-экспорт

### Sprint 4 — DevOps (1-2 нед.)
- Nginx + SSL, /health, Sentry, Prometheus, CI/CD pipeline

---

## Дизайн-референсы (вдохновение)

| Продукт | Что взять |
|---------|-----------|
| **Linear.app** | Sidebar, typography, micro-animations |
| **Vercel Dashboard** | Metric cards, dark theme, spacing |
| **Stripe Dashboard** | Data tables, charts, color system |
| **Liveblocks** | Landing gradient, glassmorphism |
| **Resend** | Minimalist forms, toast notifications |
| **Clerk** | Profile page, auth forms |
| **Raycast** | Color palette, icon style |
| **Notion** | Empty states, sidebar collapse |

---

## Принципы дизайна InvestTrack

1. **Данные — главное.** UI служит данным, не наоборот. Числа читаются с первого взгляда.
2. **Единая сетка.** Spacing = множители 4px (4, 8, 12, 16, 24, 32, 48, 64). Никаких случайных отступов.
3. **Тёмная тема первична.** Финансовые дашборды используются вечером. Dark mode должен быть безупречен.
4. **Motion = информация.** Анимации показывают изменение состояния, не развлекают. Всегда `prefers-reduced-motion: reduce`.
5. **Accessibility.** WCAG 2.1 AA: контраст ≥ 4.5:1, focus видим, aria-label на иконках.
6. **Производительность.** LCP < 1.5s, CLS < 0.1, FID < 100ms. Красивый UI не должен быть медленным.

---

## Файлы для редизайна (checklist для code review)

```
static/
  css/
    design-system.css    ← НОВЫЙ: токены + базовые компоненты
    variables.css        ← ПЕРЕПИСАТЬ: новая палитра + токены
    portfolio.css        ← ОБНОВИТЬ: использовать новые токены
    sidebar.css          ← НОВЫЙ: sidebar + bottom-bar
    animations.css       ← НОВЫЙ: keyframes + transition utilities
  js/
    sidebar.js           ← НОВЫЙ: collapse логика + mobile bottom-bar
    animations.js        ← НОВЫЙ: countUp + intersection observer
  fonts/
    inter/               ← НОВЫЙ: Inter Variable woff2
  icons/
    sprite.svg           ← НОВЫЙ: SVG спрайт

templates/
  base.html              ← sidebar вместо navbar, Inter подключение
  index.html             ← gradient mesh hero + glassmorphism form
  dashboard.html         ← новые cards + Area chart + timeline
  portfolio.html         ← sticky table + drawer + sparklines
  profile.html           ← hero section + tabs + activity feed
```
