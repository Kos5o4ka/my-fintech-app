# ADR-001: Расщепление god-service `portfolio_service.py`

- **Дата:** 2026-05-30
- **Статус:** Принято
- **Этап:** 14 (рефакторинг v2.4.0)

## Контекст

К концу этапа 12 `app/services/portfolio_service.py` разросся до **1172 строк** и
содержал около 40 публичных функций, покрывающих несвязные домены:

- CRUD `BondPortfolio`/`Transaction`
- Watchlist (`Watchlist`)
- Price alerts (`PriceAlert`)
- Купонный календарь
- Сериализация (`build_portfolio_entry`, `build_trade_entry`, ...)
- Аналитика: P&L, доходы, доли (allocation)
- Налоги: НДФЛ по ст. 214.1 НК РФ, ЛДВ, FIFO-учёт
- Риск: Sharpe Ratio, YTM, дюрация Маколея, HHI-диверсификация

Это нарушает SRP, делает покрытие тестами на уровне модуля бесполезной метрикой
(один тест на YTM «прокачивает» десятки строк CRUD) и провоцирует круговые
импорты при попытке использовать «горячие» сервисы из других мест.

## Решение

Разделить `portfolio_service.py` на тематические модули. Сохранить старые
импорты через **re-export** в `portfolio_service.py`, чтобы не ломать blueprint'ы
и legacy-тесты.

| Новый модуль                       | Ответственность                                                |
|------------------------------------|----------------------------------------------------------------|
| `services/watchlist_service.py`    | CRUD списка наблюдения, обогащение MOEX-ценой/YTM/НКД          |
| `services/alerts_service.py`       | CRUD ценовых алёртов                                           |
| `services/calendar_service.py`     | Купонный календарь и ближайшие выплаты                         |
| `services/tax_service.py`          | НДФЛ ст. 214.1, ЛДВ ст. 219.1, FIFO-учёт, налоговый отчёт      |
| `services/risk_service.py`         | Sharpe Ratio, YTM (Ньютон), дюрация Маколея/модиф., HHI        |
| `services/health_service.py`       | Health-probe DB/Cache/MOEX + счётчик визитов                   |
| `services/portfolio_service.py`    | **Только** CRUD облигаций + view-builders + facade re-exports  |

Новый код **должен** импортировать напрямую из тематических модулей.
`portfolio_service.py` остаётся точкой входа только для обратной совместимости.

## Доменные исключения

Появился модуль `app/exceptions.py` с иерархией:

```
DomainError
├── NotFoundError          → HTTP 404
├── DomainValidationError  → HTTP 400
├── AccessDeniedError      → HTTP 403
├── ConflictError          → HTTP 409
└── ExternalServiceError   → HTTP 502
    └── AuthError          → HTTP 401
```

Сервисы бросают эти исключения вместо возврата dict-ов с `status: "error"`.
Blueprint ловит `DomainError` и переводит в HTTP через `exc.to_dict()` и
`exc.http_status`. Старые сигнатуры (возврат `None`/`bool`/`str`) сохранены
через тонкие legacy-фасады `_legacy_*` для обратной совместимости.

## Layer hygiene

Параллельно устранены прямые обращения к `db.session.*` из blueprints:

| Blueprint              | Куда вынесено                              |
|------------------------|--------------------------------------------|
| `main.py`              | `services/health_service.py`               |
| `profile.py` (tinkoff) | `services/tinkoff_service.link/unlink_user_token` |
| `telegram_bot.py`      | `services/telegram_service.{link_chat_to_user, unlink_chat, refresh_username_by_chat}` |

Финальная проверка: `grep -rln "db.session" app/blueprints/` пустой.

## Последствия

**Плюсы**
- `portfolio_service.py`: 1172 → 584 LOC (-50 %)
- Тесты можно вешать на 7 узких модулей вместо одной свалки
- Coverage по `app/` вырос 62 % → 67 % (+27 новых тестов: 165 → 192)
- Слой Blueprint больше не дёргает ORM напрямую — DRY-нарушения и duplicate
  audit-log'и убираются за один проход в сервисе

**Минусы**
- Legacy-фасады дают шанс новому коду по инерции импортировать из
  `portfolio_service.py`. Mitigation: добавить ruff/flake8-правило позже
- Re-export'ы делают «прыжок» при «Go to Definition» — компромисс за
  обратную совместимость

## Альтернативы

1. **Полный переход без фасада** — отверг: 5 blueprint'ов и 3 теста пришлось бы
   менять в одном PR, риск регресса выше потенциальной выгоды.
2. **Оставить как есть** — отверг: god-service уже мешал добавлять валютные
   облигации (Этап 13) — `calc_tax_basis_per_trade` дублировал валютную
   конвертацию из ещё трёх мест.
3. **Расщепить на пакеты** (`app/services/portfolio/{tax,risk,watchlist}.py`) —
   отверг: добавит namespace overhead без выигрыша, текущий flat-layout
   читается проще.
