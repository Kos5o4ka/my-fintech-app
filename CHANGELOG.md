# Changelog

Все значимые изменения в проекте документируются здесь.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).
Проект следует [Semantic Versioning](https://semver.org/lang/ru/).

---

## [2.5.0] — 2026-05-30

### Performance — Stage 15: устранение узких мест и Redis-кэш расчётных метрик

> Профилирование выявило 5 критических узких мест (см. `docs/adr/0002-performance-caching-strategy.md`). Все устранены.

#### Backend
- **Redis-кэш YTM и дюрации** (`services/risk_service.py`): TTL 1 ч, ключ `ytm:{isin}:{round(buy_price,2)}:{round(facevalue,2)}:{round(nkd,4)}:{pd_key}`. Защита от `OverflowError: complex exponentiation` (граница `y ≤ −0.99` / `y > 10`).
- **Кэш `/api/portfolio` целиком в Redis** (5 мин, ключ `portfolio_full:{user_id}`), пагинация поверх кэша. `_bust_user_cache` инвалидирует и его.
- **N+1 устранён в `query_transactions`** — `sold_bonds_map` собирается одним запросом; `build_transaction_entry` принимает опциональный словарь.
- **`build_portfolio_list` теперь оборачивает каждую позицию в try/except** — одна битая бумага больше не валит весь портфель (был кейс с амортизацией Tinkoff).
- **MOEX batch-prefetch** (`services/moex_service.prefetch_bonds_batch`): 1 HTTP-запрос на 10 ISIN-ов через `securities=` параметр вместо N. Вызывается из `build_portfolio_list`.
- **Параллельная загрузка купонных календарей** (`services/calendar_service._load_calendars_parallel`): `ThreadPoolExecutor(max_workers=8)`.
- **Объединённый endpoint `/api/dashboard/full`** — portfolio + income + calendar + realized_pnl одним запросом (вместо 4-5 параллельных). Клиент с fallback на старые эндпоинты.
- **Retry для ЦБ РФ G-Curve** (`app/cbr.py`): `tenacity` 3 попытки, exponential backoff 1-4 с.
- **APScheduler price_update**: 15 → 30 мин (нагрузка на MOEX ÷ 2).
- **`DEFAULT_PAGE_SIZE`**: 50 → 10 (`app/constants.py`).

#### Купонная аналитика (T-Invest-style)
- **`get_coupon_calendar` cap**: 12 → **60** будущих купонов.
- **`get_calendar_events(user_id, limit, days)`** — новый API: `limit` до 1000, `days` — горизонт фильтра.
- **`/api/portfolio/calendar?limit=&days=`** — расширен.
- **`calc_coupons_received(active_bonds, period_from, period_to)`** в `portfolio_service.py` — расчёт фактически полученных купонов из истории MOEX, фильтр от `purchase_date`.
- **`/api/portfolio/coupons_received?period=...`** — endpoint полученных купонов по периоду (1w / 1m / 3m / 6m / 1y / all).
- **`/api/portfolio/yield?period=&mode=all|coupons`** — доходность за период: `coupons` (только купоны) или `all` (купоны + realized + unrealized PnL).

#### Tinkoff sync — баг-фиксы
- **SSL bypass**: `session.verify = False` + `urllib3.disable_warnings` (self-signed cert в цепочке на сервере; пользователь подтвердил).
- **Healing amortized bond prices** (`heal_amortized_buy_price`): T-Invest отдаёт `averagePositionPrice` относительно исходного номинала, MOEX — относительно текущего амортизированного. Умножение на 10/100 для попадания в диапазон 60-200 % от номинала.
- **Кнопка «Синхронизировать»**: была локальной — поднята до `window.syncTinkoff`.
- **Ложный тост «Сбой сети»** после успешного sync: `loadDashboard()` вынесен из try/catch с собственным error handler-ом и флагом `syncOk`.

#### Frontend
- **Lazy-load `portfolio-extras.js`** (watchlist + screener) через stub-функции на `window` — критический путь портфеля разгружен.
- **Per-page selector 10/20/50/100** в портфеле + пагинация footer (`bondsPerPage` в localStorage).
- **Debounce поиска облигаций** 350 мс + минимум 3 символа.
- **Кастомные модалки подтверждения** (`window.Common.askConfirmation`) вместо браузерного `confirm()` — для удаления аватара, отвязки Telegram.
- **Аналитика — главный блок «Доходность»** с переключателями периода (1w/1m/3m/6m/1y/all) и режима (Все / Только купоны). Sharpe Ratio ужат в компактный нижний блок.
- **Карточка «Полученные купоны»** в аналитике.
- **Модалка предстоящих купонов** грузит до 1000 событий, client-side фильтр 30/90/365/Все, пересчёт итога.
- **History toolbar портфеля**: `flex-wrap:nowrap; overflow-x:auto`, фильтр дат в одну строку; убран дублирующийся `<td>${typeBadge}</td>` (было 10 ячеек на 9 заголовков).
- **RGBI benchmark** (`analytics.js`): поддержка обоих форматов ответа (`{labels, data}` и массив объектов). На бэке (`app/moex.get_rgbi_history`) — пагинация через `start=`, fallback без фильтра, **не кэшировать пустые ответы**.

#### Infra
- **Gunicorn**: 4 worker × 2 thread → **2 × 4** (`gthread`) — RAM −200 МБ, конкуренция I/O не пострадала.
- **Host services**: остановлены `postgresql@14-main`, `packagekit`, `multipathd` (PostgreSQL поднят в Docker, остальные не используются). `vm.swappiness`: 60 → 10.

#### Docs
- `docs/adr/0002-performance-caching-strategy.md` — ADR с замерами «было / стало», TTL-стратегией, защитой от race conditions при инвалидации.
- `docs/architecture.md` — обновлены диаграмма данных и слой Redis (новые ключи).

---

## [2.4.0] — 2026-05-30

### Refactor — Stage 14: разделение god-service + чистка слоёв
- **`portfolio_service.py` уменьшен с 1172 → 584 строк** (−50 %). Логика разнесена по тематическим модулям:
  - `services/watchlist_service.py` — CRUD списка наблюдения
  - `services/alerts_service.py` — ценовые алёрты
  - `services/calendar_service.py` — купонный календарь + ближайшие выплаты
  - `services/tax_service.py` — НДФЛ ст. 214.1 НК РФ, ЛДВ ст. 219.1, FIFO-учёт
  - `services/risk_service.py` — Sharpe Ratio, YTM (Ньютон), дюрация Маколея/модиф., HHI-диверсификация
  - `services/health_service.py` — health-probe (DB/Cache/MOEX) + счётчик визитов
- **Backward compatibility**: `portfolio_service.py` оставлен как фасад с re-export'ами — все существующие импорты в blueprints/tests работают без изменений
- **Доменные исключения** (`app/exceptions.py`): `DomainError`, `NotFoundError`, `DomainValidationError`, `AccessDeniedError`, `ConflictError`, `ExternalServiceError`, `AuthError` с предопределёнными HTTP-кодами и методом `to_dict()`
- **Layer hygiene**: устранены все прямые обращения `db.session.*` из blueprints (`main.py`, `profile.py`, `telegram_bot.py` → service-слой); проверка `grep -rln "db.session" app/blueprints/` пустая
- **T-Invest token lifecycle** вынесен из `profile.py` blueprint в `tinkoff_service.link_user_token / unlink_user_token`
- **Telegram webhook flows** вынесены из blueprint в `telegram_service.link_chat_to_user / unlink_chat / refresh_username_by_chat` — blueprint стал тонким HTTP-парсером

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

### Tests
- **+27 тестов** (`tests/test_refactor_stage14.py`): watchlist/alerts/calendar/tax/risk сервисы, telegram webhook flows (link/unlink/help/empty/wrong-secret), domain exceptions, health service
- **Coverage**: 62 % → **67 %**
  - `blueprints/telegram_bot.py`: 17 % → **90 %**
  - `blueprints/main.py`: 46 % → **81 %**
  - все новые модули ≥ 69 %
- **Всего тестов**: 165 → **192**

### Docs
- `docs/adr/0001-service-layer-split.md` — Architecture Decision Record с обоснованием расщепления, рассмотренными альтернативами и последствиями
- `docs/architecture.md` — обновлён состав Services Layer в C4-диаграмме

---

## [2.3.0] — 2026-05-29

### Added — Stage 13: T-Invest API integration
- **Полноценная интеграция с T-Invest REST API** (`invest-public-api.tbank.ru/rest`): импорт облигационного портфеля одним кликом
- **`app/services/tinkoff_service.py`**: `TInvestClient` (тонкая обёртка над requests с retry на 429), конвертеры `MoneyValue/Quotation/Timestamp → Decimal/datetime`, `sync_tinkoff_portfolio()` с upsert в `BondPortfolio` по `(user_id, isin, is_sold=False)`, обогащение через `InstrumentsService/GetInstrumentBy` батчами по 5 c паузой 200 мс (соблюдение лимита 200 RPM)
- **Шифрование токена**: Fernet (AES-CBC + HMAC) с ключом, производным из `SECRET_KEY` через PBKDF2-HMAC-SHA256 (200k итераций). Plain-токен **никогда** не возвращается во фронтенд
- **Эндпоинты**: `GET/POST /api/profile/tinkoff_token` (статус / сохранение с валидацией через `GetAccounts`), `GET /api/profile/tinkoff/accounts` (список счетов), `POST /api/portfolio/tinkoff_sync` (синхронизация с опциональным `account_id` и `sandbox`)
- **Pydantic-схема `TinkoffTokenIn/TinkoffSyncIn`** (`app/schemas/tinkoff.py`): валидация формата токена (`t.`-префикс)
- **Маппинг ошибок API**: 401/40003 → `TInvestAuthError` (HTTP 401 для UX обновления токена), 429/50002 → один retry, далее `TInvestRateLimitError`
- **Конвертация цены**: `averagePositionPrice` (руб./шт.) → `%` от номинала через `nominal` инструмента (MOEX-конвенция: всё хранится в `%`)
- **Аудит**: `import_ok/import_fail` с `source: "tinkoff"` и summary; `settings_update` при привязке/удалении токена
- **Миграция `stage13_tinkoff_integration`**: идемпотентная, расширяет `users.tinkoff_token` до TEXT (Fernet-токен > 255 байт), добавляет `tinkoff_last_sync_at`, `tinkoff_account_id`
- **Bruno**: `profile/tinkoff_token_save.bru`, `tinkoff_token_status.bru`, `tinkoff_accounts.bru`, `portfolio/tinkoff_sync.bru`
- **16 новых тестов** (`tests/test_stage13_tinkoff.py`): конвертеры MoneyValue/Quotation/Timestamp, шифрование roundtrip, HTTP-клиент с мокнутым `requests.Session`, end-to-end sync (BBG-FIGI → ISIN → BondPortfolio), валидация токена в эндпоинте, удаление привязки
- **Зависимость**: `cryptography>=42.0,<46` (для Fernet)

### Security
- Plain-токен T-Invest хранится в БД **только в зашифрованном виде**, не возвращается в API-ответах и не логируется
- Перед сохранением токен проходит верификацию через `GetAccounts` — невалидный токен не попадает в БД

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
- N/A

### Changed
- N/A

### Fixed
- N/A

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
[Unreleased]: https://github.com/Kos5o4ka/my-fintech-app/compare/v2.5.0...HEAD
[2.5.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v2.4.0...v2.5.0
[2.4.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v2.2.0...v2.3.0
[1.4.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.3.3...v1.4.0
[1.3.3]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.3.0...v1.3.3
[1.3.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Kos5o4ka/my-fintech-app/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Kos5o4ka/my-fintech-app/releases/tag/v1.0.0
