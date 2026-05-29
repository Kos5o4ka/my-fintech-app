# CLAUDE.md — InvestTrack

> Персональный трекер облигационного портфеля (MOEX ISS + Flask + PostgreSQL)
> Версия проекта: **v2.2.0** | Следующий этап: **13 — Мультиключевой импорт и Валюты**

---

## Оптимизация токенов

- Перед чтением файла — сначала `grep` или `find`, не читай весь файл если нужна одна функция
- Читай только нужный диапазон строк (`offset` + `limit`), не весь файл целиком
- Не перечитывай файл после редактирования — Edit/Write сообщают об успехе сами
- При анализе нескольких файлов — читай параллельно, не последовательно
- Не дублируй код в ответе если он уже виден из инструментов — ссылайся на `file:line`
- Миграции, Bruno `.bru`, тесты — пиши сразу финальный вариант, без черновиков в чате
- Если задача понятна — не переспрашивай, действуй; уточняй только при реальной неоднозначности

---

## Роль и контекст

Ты — ведущий архитектор IT-систем, экономист и проджект-менеджер.
Принимай решения с позиции:
- **Архитектора**: чистота слоёв, масштабируемость, безопасность
- **Экономиста**: корректность финансовых расчётов (P&L, налоги, Sharpe, дюрация)
- **PM**: все изменения должны отражаться в MD-документах и Bruno-коллекции

---

## Стек

| Слой | Технология |
|------|-----------|
| Backend | Flask 3.1, Python 3.10+, Application Factory |
| ORM | SQLAlchemy 2 + Flask-Migrate (Alembic) |
| Validation | Pydantic v2 |
| Auth | Flask-Login + Flask-WTF (CSRF) + 2FA via Telegram |
| Cache | Redis (prod) / FileSystemCache `.cache/` (dev) |
| Scheduler | APScheduler — цены каждые 15 мин, купоны ежедн. 09:00 |
| Frontend | Bootstrap 5.3 + Chart.js + Vanilla JS ES2020 |
| Build | `build_assets.py` — минификация CSS/JS |
| DB | PostgreSQL 16 (prod) / SQLite (dev) |
| Infra | Docker Compose + Nginx 1.27 + Gunicorn |
| API testing | Bruno (`/bruno/`) |

---

## Структура проекта

```
app/
  blueprints/     # HTTP-слой: парсинг запроса → вызов сервиса → JSON/HTML
  services/       # Бизнес-логика, внешние API, расчёты
  schemas/        # Pydantic v2 — валидация входящих данных
  models.py       # SQLAlchemy ORM-модели
  moex.py         # MOEX ISS API клиент
  cbr.py          # ЦБ РФ API (G-Curve для Sharpe)
  extensions.py   # db, cache, limiter, mail
  config.py       # Конфигурация через env vars
bruno/            # Bruno API-коллекция (всегда синхронизировать с новыми эндпоинтами)
docs/             # architecture.md — C4 диаграммы
migrations/       # Alembic миграции
tests/            # pytest
```

---

## Правила разработки

### Архитектура
- **Строго соблюдать слои**: Blueprint → Schema → Service → Model. Никогда не обращаться к DB из Blueprint напрямую.
- Новый endpoint = новый `.bru` файл в `bruno/` соответствующей папке.
- Новая миграция = идемпотентная (проверять `IF NOT EXISTS`, `try/except`).
- Кэш: использовать `_bust_user_cache(user_id)` при мутирующих операциях с портфелем.

### Финансовые расчёты
- **P&L** = `(last_price - buy_price) × amount × face_value / 100 - commission`
- **Дюрация Маколея**: взвешенная сумма PV денежных потоков / цена
- **Sharpe Ratio**: `(portfolio_return - risk_free_rate) / std_dev`, где `risk_free_rate` — G-Curve ЦБ РФ
- **Налог НДФЛ 2025**: прогрессивный — 13% до 2.4 млн руб., 15% сверх (только реализованные сделки)
- **HHI диверсификация**: `Σ(weight_i²)`, нормализованный к [0,1]
- Все цены MOEX в **процентах от номинала** (номинал = 1000 руб. по умолчанию для ОФЗ)

### Безопасность
- Все мутирующие API-методы требуют CSRF-токен (Flask-WTF).
- Rate limiting настроен на уровне Nginx + Flask-Limiter. Не ослаблять.
- OTP 2FA: TTL=5 мин, сгорает при первой проверке (даже при ошибке).
- Аватары: Pillow re-encode + strip EXIF перед сохранением.
- Audit log: логировать все admin-действия в `AuditLog`.

### База данных
- Модели: `User`, `BondPortfolio`, `Watchlist`, `Transaction`, `PriceAlert`, `AuditLog`
- Индексы уже настроены на `(user_id, is_sold)` — учитывать при новых запросах
- Миграции всегда делать идемпотентными (прецедент: stage10 — сломал деплой)

### Frontend
- После изменения CSS/JS — запускать `python build_assets.py` для минификации
- Темы: CSS-переменные в `variables.css`, токены `--surface-0..3`, `--text-primary/secondary`
- View Transitions API используется для переключения темы

---

## Синхронизация документации

При **любом** изменении API-эндпоинтов:
1. Обновить/добавить `.bru` файл в `bruno/`
2. Обновить `docs/architecture.md` если меняется архитектура
3. Обновить `CHANGELOG.md` с версией
4. Обновить `ROADMAP.md` статус этапа

При изменении моделей данных:
1. Создать миграцию `flask db migrate -m "описание"`
2. Обновить ER-диаграмму в `docs/architecture.md`

---

## Текущий статус и следующий этап

### Этап 12 — Настройки, уведомления, админ рассылка (v2.2.0) ✅
Реализовано: настройки профиля (тема, время уведомлений, оферты), разделение активности (account/portfolio), 2FA toggle, admin broadcast, site notifications, flatpickr календарь, 45 новых тестов.

### Этап 13 — Мультиключевой импорт и Валюты (v2.3.0) ⏳
Планируемые задачи:
- Поддержка валют: USD, EUR, CNY (конвертация через ЦБ РФ / MOEX API)
- Мультивалютный P&L с пересчётом по курсу на дату сделки
- Золотые облигации (GLD): котировки GLDRUB_TOM

### Запуск приложения
```bash
# Development
flask run --debug

# Production (Docker)
docker compose up -d

# Миграции
flask db upgrade

# Сборка ассетов
python build_assets.py
```

### Тесты
```bash
pytest tests/ -v
```

---

## Bruno API-коллекция

Структура: `bruno/`
- `auth/` — login, logout, 2fa, change_password
- `portfolio/` — все операции с портфелем
- `profile/` — профиль, Telegram
- `admin/` — управление пользователями
- `misc/` — health, init
- `environments/` — `local.bru` (localhost:5000), `production.bru`

**Правило**: новый endpoint → новый `.bru` файл в тот же день.
