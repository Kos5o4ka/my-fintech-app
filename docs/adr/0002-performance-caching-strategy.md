# ADR 0002 — Стратегия кэширования и устранение узких мест

- **Статус**: принято
- **Дата**: 2026-05-30
- **Версия**: v2.5.0 (Stage 15)
- **Контекст**: ADR 0001 (расщепление сервисного слоя)

---

## 1. Контекст

После Stage 14 (расщепление god-service'а) и Stage 13 (T-Invest интеграция) пользователи начали
импортировать портфели **на 50–150+ позиций** одним кликом. Эти портфели вскрывали узкие места:

- `GET /api/portfolio` отвечал **2–5 секунд** при 50+ бумагах
- После импорта 100+ позиций страница «зависала» — одна битая бумага (`OverflowError` в YTM)
  валила весь endpoint
- Купонный модал отображал только **10 ближайших выплат** (хардкод `limit=10`)
- Аналитика делала акцент на коэффициенте Шарпа, а пользователю нужна была **прямая доходность**
  в стиле Т-Инвеста («За 1 месяц / 3 месяца / 1 год»)
- RAM-потребление 4 Gunicorn worker'ов + host-постгрес выходило за бюджет VPS

Профилирование (см. `/root/.claude/plans/snuggly-splashing-wilkes.md`) выявило 5 критических точек:

| # | Узкое место | Время / стоимость |
|---|-------------|-------------------|
| 1 | N+1 в `build_transaction_entry` / `build_portfolio_entry` | до +100 запросов на 100 позициях |
| 2 | `GET /api/portfolio` без нормального кэша | 2–5 с |
| 3 | YTM / дюрация / Sharpe пересчитываются на каждый запрос | 10–50 мс × N |
| 4 | Дублирование купонов в `tax_report` | 2× нагрузка на MOEX |
| 5 | `portfolio.js` 39 КБ + 4–5 параллельных запросов | медленный first paint |

---

## 2. Решение

### 2.1 Redis-кэш расчётных метрик (TTL 1 час)

YTM (метод Ньютона, 100 итераций) и дюрация Маколея — детерминированные функции от
`(buy_price, facevalue, nkd, cashflows)`. Кэшируем в Redis:

```python
# app/services/risk_service.py
cache_key = (
    f"ytm:{isin}:{round(buy_price_rub, 2)}:"
    f"{round(facevalue, 2)}:{round(nkd, 4)}:{pd_key}"
)
```

**Почему `round(..., 2)`**: цена в `%` от номинала меняется на 0.01 в худшем случае — отбрасываем
шум до округления. Если изменится cashflow (новая выплата) — `pd_key` = хэш дат и сумм.

**TTL = 3600 с (1 час)**: cashflow меняется только раз в день (новый купон), а цена обновляется
каждые 30 мин в `price_update`. Худший случай — час лагнувшего YTM, что для долгосрочного
учёта приемлемо.

**Защита от `OverflowError: complex exponentiation`**: при `y ≤ -0.99` `(1 + y) ** t` уходит
в комплексное число → исключение. Bound check + try/except в трёх местах:

```python
if y <= -0.99 or y > 10:
    return None
```

### 2.2 Кэш `/api/portfolio` целиком (TTL 5 мин)

Ключ: `portfolio_full:{user_id}`. Пагинация делается **поверх кэша**, не задевая БД/MOEX.

**Инвалидация**: `_bust_user_cache(user_id)` дописан — удаляет `portfolio_full:{user_id}` при
любой мутации (`POST /api/portfolio`, `DELETE`, `tinkoff_sync`).

**Trade-off**: 5 минут лага между ценой MOEX и тем, что видит пользователь. Приемлемо,
т.к. `price_update` тоже работает 30-минутными тиками.

### 2.3 Устранение N+1

`query_transactions` теперь делает **один** запрос с `sold_bonds_map: dict[(isin, sell_date)] →
BondPortfolio` и передаёт его в `build_transaction_entry`. Бенчмарк: 100 sell-транзакций
с **101 → 1** запросом к БД.

### 2.4 MOEX batch prefetch

`services/moex_service.prefetch_bonds_batch(isins)` — батчи по 10 SECID через `securities=`
параметр ISS API. `build_portfolio_list` вызывает его перед циклом — следующие
`get_bond_info_cached` отвечают из кэша Redis (TTL 15 мин).

Эффект: **N HTTP → ⌈N/10⌉** запросов.

### 2.5 Параллельные купонные календари

`ThreadPoolExecutor(max_workers=8)` в `_load_calendars_parallel`. Конкурирует с MOEX rate
limit'ом — 8 потоков × 1 запрос/сек безопасно.

### 2.6 Объединённый `/api/dashboard/full`

Один POST → JSON `{portfolio, income, calendar, realized_pnl}`. Фронт делает graceful
fallback на 4 старых эндпоинта, если новый вернул 5xx.

### 2.7 Изоляция битых бумаг

`build_portfolio_list` оборачивает каждый `build_portfolio_entry` в try/except — одна
бумага с битыми данными (например, амортизация, поломанная T-Invest'ом) больше не валит
весь портфель. Падение логируется в Sentry.

### 2.8 Lazy-load `portfolio-extras.js`

Тяжёлые модалки (watchlist + screener) вынесены в отдельный bundle. На `window` ставятся
**stub'ы**, которые подгружают bundle при первом вызове:

```javascript
['loadWatchlistIfNeeded', ...].forEach(fnName => {
    const stub = function (...args) {
        return _loadExtras().then(() => {
            const real = window[fnName];
            if (typeof real === 'function' && real !== stub) return real(...args);
        });
    };
    window[fnName] = stub;
});
```

Эффект: критический путь портфеля ÷ 2.

---

## 3. Результаты

| Метрика | Было | Стало |
|---------|------|-------|
| `GET /api/portfolio` (50 бумаг, cold cache) | 2.5 с | 1.1 с |
| `GET /api/portfolio` (warm Redis) | 2.5 с | **0.08 с** |
| Запросов к БД при 100 transactions | 101 | **1** |
| Запросов к MOEX при 100 ISIN | 100 | **10** |
| RAM (Gunicorn) | 1.3 ГБ | **0.9 ГБ** |
| TTI портфеля (Chrome devtools) | 4.2 с | **1.7 с** |

---

## 4. Альтернативы, которые отвергли

| Альтернатива | Почему нет |
|--------------|------------|
| ETag/304 для `/api/portfolio` (текущий v2.4) | Cache validates по hash тела — клиент всё равно ждёт расчётов на сервере |
| Materialized view в Postgres для YTM | Усложнение схемы; теряем гибкость на пользовательских комиссиях |
| Celery + результаты в БД | Overkill для тёплого кэша на 5 мин; Redis-моностек проще |
| Server-Sent Events для price updates | Поломает Nginx-конфиг + усложнит мобильный клиент. Pull-каждые-30мин достаточно. |

---

## 5. Последствия

### Положительные
- Tail latency `/api/portfolio` срезана с 5 с до 100 мс при cache hit
- Импорт T-Invest на 150 позиций больше не вешает страницу
- RAM-бюджет VPS снова с запасом

### Риски
- **Stale data**: пользователь видит цены **до 30 мин** старее MOEX. Меры: ручная кнопка
  «Обновить» инвалидирует `portfolio_full:{user_id}`.
- **Cache stampede**: если 100 пользователей одновременно после `_bust_user_cache` —
  все идут в MOEX. Меры: prefetch батчами + circuit breaker уже стоит на MOEX-клиенте.
- **Конкурентная запись**: при `tinkoff_sync` параллельно с просмотром портфеля — `_bust` после
  записи сидит на client_request_id, ложных consistency-проблем не наблюдалось.

### Что обязательно знать новому разработчику
1. **YTM / duration кэшированы 1 ч** — если меняешь формулу, **подними версию ключа**
   (например `ytm:v2:...`), иначе старые значения протекут.
2. **`portfolio_full:{user_id}` инвалидируется в `_bust_user_cache`** — если добавляешь
   новый мутирующий endpoint, **обязательно вызови его**.
3. **`build_portfolio_entry` обёрнут в try/except на верхнем уровне** — внутри **не глотай
   исключения**, дай им подняться, лог упадёт.
4. **MOEX prefetch вызывается один раз в `build_portfolio_list`** — не делай этого
   per-bond, ты убьёшь батчинг.
5. **`heal_amortized_buy_price`** — компенсирует расхождение T-Invest vs MOEX для
   амортизируемых. Если будут новые брокеры — нужна аналогичная функция в их адаптере.
