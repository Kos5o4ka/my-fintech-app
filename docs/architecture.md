# InvestTrack — Архитектура системы

> C4 Level 2 (Container diagram). Визуализация через [Mermaid](https://mermaid.js.org/).

---

## Обзор контейнеров

```mermaid
graph TB
    %% External actors
    User(["👤 Пользователь\n(Browser)"])
    TelegramUser(["📱 Telegram-пользователь"])

    %% External systems
    MOEX["🏦 MOEX ISS API\nexchange.moex.com\nRESTful JSON API"]
    TelegramAPI["✈️ Telegram Bot API\napi.telegram.org\nWebhook + sendMessage"]
    Sentry["🔍 Sentry\nError tracking\n(опционально)"]

    subgraph Docker["Docker Compose Network"]

        Nginx["🌐 Nginx 1.27\n──────────────\nReverse Proxy\nStatic files (30d cache)\nGzip compression\nRate limiting\nSSL termination"]

        subgraph App["Flask Application (Gunicorn)"]
            direction TB
            Auth["blueprints/auth.py\n──────────────\n/api/auth/login\n/api/auth/verify_2fa\n/api/auth/logout\n/api/auth/change_password"]
            Portfolio["blueprints/portfolio.py\n──────────────\n/api/portfolio/*\n/portfolio/report\n/api/search_bond"]
            Profile["blueprints/profile.py\n──────────────\n/api/profile/*\n/api/profile/avatar (DELETE)\n/profile"]
            Main["blueprints/main.py\n──────────────\n/ (лендинг)\n/dashboard\n/api/init"]
            Admin["blueprints/admin.py\n──────────────\n/admin\n/api/admin/*"]
            TGBot["blueprints/telegram_bot.py\n──────────────\n/api/telegram/webhook"]

            Services["⚙️ Services Layer\n──────────────\nportfolio_service.py\nmoex_service.py\nuser_service.py\ntelegram_service.py\naudit_service.py\nnotification_service.py\nimport_service.py\nadmin_service.py\nauth_service.py"]

            Scheduler["⏰ APScheduler\n──────────────\nЦены каждые 15 мин\nКупоны ежедн. 09:00"]
        end

        DB[("🗄️ PostgreSQL 16\n(SQLite в dev)\n──────────────\nUser\nBondPortfolio\nWatchlist\nTransaction\nAuditLog")]

        Redis[("⚡ Redis 7\n──────────────\nCache (MOEX 15м)\nCache (stats 15м)\nOTP tokens (5м)\nLink tokens (10м)")]

        Static["📁 Static Files\nstatic/css/*.min.css\nstatic/js/*.min.js\nstatic/avatars/"]
    end

    %% User flows
    User -->|"HTTPS 443"| Nginx
    Nginx -->|"proxy_pass :5000"| App
    Nginx -->|"alias /app/static"| Static

    %% Telegram
    TelegramAPI -->|"POST /api/telegram/webhook"| Nginx
    TGBot -->|"sendMessage API"| TelegramAPI
    TelegramUser <-->|"Bot messages"| TelegramAPI

    %% Internal
    Auth & Portfolio & Profile & Main & Admin & TGBot --> Services
    Services --> DB
    Services --> Redis
    Scheduler --> Services

    %% External APIs
    Services -->|"HTTP GET"| MOEX
    App -.->|"errors + traces"| Sentry

    %% Styling
    classDef external fill:#e8f4f8,stroke:#2196F3,color:#0d47a1
    classDef container fill:#fff3e0,stroke:#FF9800,color:#e65100
    classDef db fill:#e8f5e9,stroke:#4CAF50,color:#1b5e20
    classDef service fill:#f3e5f5,stroke:#9C27B0,color:#4a148c
    classDef proxy fill:#fce4ec,stroke:#E91E63,color:#880e4f

    class MOEX,TelegramAPI,Sentry external
    class Auth,Portfolio,Profile,Main,Admin,TGBot,Services,Scheduler container
    class DB,Redis db
    class Nginx proxy
```

---

## Слои приложения

```mermaid
graph LR
    A["HTTP Request"] --> B["Blueprint\n(HTTP Layer)"]
    B --> C["Pydantic Schema\n(Validation)"]
    C --> D["Service\n(Business Logic)"]
    D --> E["Model\n(SQLAlchemy ORM)"]
    D --> F["moex.py\n(MOEX ISS API)"]
    E --> G[("Database")]
    F --> H[("Cache")]

    style A fill:#e3f2fd
    style B fill:#fff9c4
    style C fill:#fce4ec
    style D fill:#e8f5e9
    style E fill:#f3e5f5
    style F fill:#fff3e0
    style G fill:#e0f2f1
    style H fill:#e0f2f1
```

| Слой | Файлы | Ответственность |
|------|-------|----------------|
| HTTP | `blueprints/*.py` | Парсинг запроса → вызов сервиса → возврат JSON/HTML |
| Validation | `schemas/*.py` | Pydantic v2 валидация входящих данных |
| Business Logic | `services/*.py` | Расчёты, внешние API, бизнес-правила |
| Data | `models.py`, `moex.py` | ORM-модели, прямой доступ к MOEX |
| Infrastructure | `extensions.py`, `config.py` | db, cache, limiter |

---

## Модели данных

```mermaid
erDiagram
    USER {
        int id PK
        string username UK
        string password_hash
        string email
        bool is_admin
        string avatar
        bool email_notifications
        int telegram_chat_id
        bool telegram_notifications
        bool two_fa_enabled
        string telegram_username
        string theme
        string notif_time
        string notif_timezone
        int oferta_advance_days
    }

    BOND_PORTFOLIO {
        int id PK
        int user_id FK
        string isin
        string secid
        string name
        int amount
        float buy_price
        float sell_price
        float last_price
        float broker_commission
        date purchase_date
        date sell_date
        bool is_sold
        string currency
        datetime updated_at
        text notes
    }

    WATCHLIST_ITEM {
        int id PK
        int user_id FK
        string isin
        string name
        datetime added_at
    }

    AUDIT_LOG {
        int id PK
        int user_id FK
        string action
        string category
        string ip_address
        string user_agent
        json details
        datetime created_at
    }

    SITE_NOTIFICATION {
        int id PK
        int user_id FK
        string title
        text body
        bool is_read
        datetime created_at
    }

    PRICE_ALERT {
        int id PK
        int user_id FK
        string isin
        string name
        float target_price
        string condition
        bool is_triggered
        datetime created_at
    }

    TRANSACTION {
        int id PK
        int user_id FK
        string isin
        string name
        string tx_type
        int amount
        float price
        float commission
        string currency
        date tx_date
    }

    USER ||--o{ BOND_PORTFOLIO : "has"
    USER ||--o{ WATCHLIST_ITEM : "watches"
    USER ||--o{ AUDIT_LOG : "generates"
    USER ||--o{ TRANSACTION : "logs"
    USER ||--o{ SITE_NOTIFICATION : "receives"
    USER ||--o{ PRICE_ALERT : "sets"
```

---

## Поток аутентификации (с 2FA)

```mermaid
sequenceDiagram
    actor Browser
    participant Flask
    participant Cache
    participant TelegramService
    participant TelegramBot as Telegram Bot API

    Browser->>Flask: POST /api/auth/login {username, password}
    Flask->>Flask: verify password hash

    alt Telegram привязан → 2FA
        Flask->>TelegramService: generate_otp(user_id)
        TelegramService->>Cache: store OTP TTL=5min
        TelegramService->>TelegramBot: sendMessage(chat_id, "Ваш код: XXXXXX")
        Flask-->>Browser: {status: "2fa_required", token: "uuid"}

        Browser->>Flask: POST /api/auth/verify_2fa {token, code}
        Flask->>TelegramService: verify_otp(user_id, code)
        TelegramService->>Cache: check + delete OTP
        Flask->>Flask: login_user() → set session
        Flask-->>Browser: {status: "success"} → redirect /dashboard
    else Telegram не привязан
        Flask->>Flask: login_user() → set session
        Flask-->>Browser: {status: "success"} → redirect /dashboard
    end
```

---

## Поток обновления данных MOEX

```mermaid
sequenceDiagram
    participant Scheduler as APScheduler (15 мин)
    participant Portfolio as portfolio.py
    participant MoexService as moex_service.py
    participant Cache
    participant MOEX as MOEX ISS API
    participant DB

    Scheduler->>Portfolio: update_prices()
    Portfolio->>DB: SELECT active bonds (GROUP BY ISIN)

    loop Для каждого уникального ISIN
        Portfolio->>MoexService: get_bond_cached(isin)
        MoexService->>Cache: GET bond:{isin}

        alt Cache HIT
            Cache-->>MoexService: bond data
        else Cache MISS
            MoexService->>MOEX: GET /iss/engines/bonds/...
            MOEX-->>MoexService: JSON
            MoexService->>Cache: SET bond:{isin} TTL=5min
        end
    end

    Portfolio->>DB: bulk_update_mappings(last_price, updated_at)
```

---

## Кэш-стратегия

| Ключ | TTL | Инвалидация / Описание |
|------|-----|-------------------------|
| `moex_bond:{isin}` | 15 мин | Цены и параметры активных облигаций с MOEX ISS. |
| `moex_coupons:{secid}` | 12 ч | Купонный календарь облигации — ликвидация N+1 HTTP-запросов к MOEX. |
| `bond_preview:{isin}` | 5 мин | Превью цены и деталей облигации для UI добавления. |
| `portfolio_stats:{user_id}` | 15 мин | `_bust_user_cache()` при add/sell bond. Статистика P&L по месяцам. |
| `portfolio_income:{user_id}` | 15 мин | `_bust_user_cache()` при add/sell bond. Прогноз купонов. |
| `bond_chart:{isin}:{range}` | 15 мин / 1 день | История цены для чарта облигации. |
| `tg_otp:{chat_id}` | 5 мин | Одноразовый OTP код 2FA (сгорает при любой первой проверке). |
| `tg_link:{token}` | 10 мин | Временный токен deep-link привязки аккаунта в Telegram. |
| `tg_2fa:{token}` | 5 мин | Pending-сессия входа 2FA. |
| `benchmark:{range}` | 10 мин | Данные сравнения с RGBI индексом. |
| `screener:{filters}` | 1 час | Результаты скрининга облигаций на MOEX. |
| `compare:{isins}:{range}` | 10 мин | Данные нормализованного сравнения двух облигаций. |

Backend: **FileSystemCache** (`.cache/`) по умолчанию, **Redis** при наличии `REDIS_URL`.

---

## Безопасность

```mermaid
graph TD
    A["Входящий запрос"] --> B{"Nginx Rate Limit"}
    B -->|"login: 5 rps"| C["Flask"]
    B -->|"api: 60 rps"| C
    B -->|"general: 120 rps"| C
    B -->|"exceeded"| X["429 Too Many Requests"]

    C --> D{"CSRF Check\n(Flask-WTF)"}
    D -->|"fail"| Y["400 Bad Request"]
    D -->|"pass"| E{"Auth Check\n(@login_required)"}
    E -->|"fail"| Z["401 / redirect /"]
    E -->|"pass"| F["Blueprint Handler"]

    F --> G{"Pydantic Validation"}
    G -->|"fail"| W["400 Validation Error"]
    G -->|"pass"| H["Service → DB"]
```

**Заголовки безопасности (production):**
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Permissions-Policy: geolocation=(), camera=(), microphone=()`
- `Server` заголовок удаляется
- Все cookie: `Secure`, `HttpOnly`, `SameSite=Lax`
