# InvestTrack — Технический обзор и рекомендации

> **Дата:** 2026-05-27  
> **Версия:** v1.4.0  
> **Автор:** Lead Developer Review  
> **Охват:** backend, frontend, тесты, безопасность, новые фичи

---

## Содержание

1. [Общая оценка](#1-общая-оценка)
2. [Что уже сделано хорошо](#2-что-уже-сделано-хорошо)
3. [Критические проблемы](#3-критические-проблемы)
4. [Производительность](#4-производительность)
5. [Безопасность](#5-безопасность)
6. [Финансовая логика](#6-финансовая-логика)
7. [Тестирование](#7-тестирование)
8. [Архитектура — рефакторинг](#8-архитектура--рефакторинг)
9. [Новые фичи](#9-новые-фичи-приоритизированно)
10. [Мелкие code smells](#10-мелкие-code-smells)
11. [Приоритетный план](#11-приоритетный-план)

---

## 1. Общая оценка

Проект находится на хорошем уровне для pet-проекта, который вырос до production-ready приложения.
Архитектура с Blueprint → Service → Schema → Model правильная, разделение ответственности соблюдено почти везде.

**Итоговая оценка по слоям:**

| Слой | Оценка | Примечание |
|------|--------|------------|
| Архитектура | ⭐⭐⭐⭐ | Чистое разделение слоёв, хорошие абстракции |
| Безопасность | ⭐⭐⭐ | Есть CSP, CSRF, rate-limit, но `unsafe-inline` ослабляет защиту |
| Производительность | ⭐⭐⭐ | N+1 в ключевом пути, отсутствие параллелизма MOEX |
| Тестирование | ⭐⭐ | 45% — мало для финтех-данных |
| Финансовая логика | ⭐⭐⭐ | Есть неточности в Sharpe и налоговом расчёте |
| DevOps | ⭐⭐⭐⭐ | CI/CD, Docker multi-stage, Nginx, Sentry |
| Frontend | ⭐⭐⭐⭐ | Чистый код, build pipeline, dark mode |

---

## 2. Что уже сделано хорошо

### Архитектура
- **Application Factory** — правильный паттерн Flask, тесты изолированы.
- **Pydantic v2 валидация** на входе всех POST/PATCH — ни одна невалидная структура не доходит до логики.
- **Circuit breaker** для MOEX с fallback на кэш — при недоступности биржи приложение не падает.
- **ETag + Cache-Control** на `/api/portfolio` — браузер не перекачивает данные если портфель не изменился.

### DevOps
- **Multi-stage Docker build** — образ ~200 МБ меньше благодаря отделению builder от runtime.
- **APScheduler с file lock** (`fcntl.flock`) — планировщик в одном процессе, нет дублирования уведомлений.
- **Bulk UPDATE** в `_update_bond_prices` — один SQL вместо N.
- **GitHub Actions**: lint → test → docker smoke test.

### Безопасность
- CSRF через Flask-WTF + cookie XSRF-TOKEN + JS wrapper `csrfFetch`.
- Rate limiting на 3 зоны (login 5r/m, api 60r/m, general 120r/m).
- Убирается заголовок `Server:`, `send_default_pii=False` в Sentry.

---
## 3. Критические проблемы

### 3.1 `fcntl` — сломан запуск на Windows

**Файл:** `app.py:2`

```python
import fcntl  # ← модуль существует только на Unix/Linux/macOS
```

На Windows падает с `ModuleNotFoundError` при старте `python app.py`.
Каждый разработчик на Windows получит падение на старте — не из-за конфигурации,
а из-за системно-специфичного импорта.

**Исправление:**

```python
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False  # Windows

def _try_acquire_scheduler_lock() -> bool:
    if not _HAS_FCNTL:
        return True  # на Windows lock не нужен — Gunicorn там не используется
    try:
        import tempfile, os
        lock_path = os.path.join(tempfile.gettempdir(), "investtrack_scheduler.lock")
        _fd = open(lock_path, "w")
        fcntl.flock(_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        atexit.register(lambda: _fd.close())
        return True
    except OSError:
        return False
```

---

### 3.2 Побочный эффект внутри «чистой» функции

**Файл:** `services/portfolio_service.py:29`

```python
def build_portfolio_entry(bond: BondPortfolio) -> dict:
    ...
    if bond.last_price is None or abs(float(bond.last_price) - last_p) > 0.005:
        bond.last_price = last_p  # ← МУТИРУЕТ ORM-объект без коммита!
```

Функция `build_*` должна создавать данные, а не изменять входной объект.
SQLAlchemy отслеживает это изменение — при следующем коммите цена запишется в БД.
Фоновый job `_update_bond_prices` уже делает bulk UPDATE — двойная запись не нужна.

**Исправление:**

```python
def build_portfolio_entry(bond: BondPortfolio, *, update_price: bool = False) -> dict:
    ...
    if moex_price is not None:
        last_p = float(moex_price)
        if update_price:  # явный флаг — только тот, кто знает зачем
            bond.last_price = last_p
```

---

### 3.3 Импорт приватной функции

**Файл:** `blueprints/portfolio.py:26`

```python
from moex import _fetch_json  # ← underscore = приватное API
```

Blueprint не должен знать о низкоуровневом `_fetch_json`.
Нужно создать публичную высокоуровневую функцию в `moex.py`.

---

## 4. Производительность

### 4.1 N+1: курсы валют запрашиваются для каждой облигации

**Файл:** `services/portfolio_service.py:17-66`

```python
def build_portfolio_entry(bond):
    rates = get_currency_rates()  # ← вызывается для КАЖДОЙ облигации в цикле!
```

При 30 позициях — 30 одинаковых cache lookups вместо одного.

**Исправление — поднять наверх:**

```python
def build_portfolio_list(active_bonds):
    rates = get_currency_rates()  # ← один раз
    for bond in active_bonds:
        entry = build_portfolio_entry(bond, rates=rates)  # ← передаём
```

---

### 4.2 MOEX API — последовательные вызовы вместо параллельных

`calc_coupon_income` для 10 облигаций: 10 запросов × 1–2 сек = до 20 секунд ожидания.

**Исправление через ThreadPoolExecutor:**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=8) as executor:
    futures = {
        executor.submit(get_coupon_calendar_cached, target): target
        for target in targets
    }
    for future in as_completed(futures):
        calendars[futures[future]] = future.result()
```

Эффект: 10 секунд → 1–2 секунды (ограничено самым медленным запросом, не суммой).

---

### 4.3 Нет кэша для Sharpe и Tax

Добавить в `constants.py`:

```python
SHARPE_TTL: int = 3600  # 1 час
TAX_TTL: int = 3600     # 1 час
```

Обернуть вычисления в `@cache.memoize(timeout=SHARPE_TTL)`.

---
## 5. Безопасность

### 5.1 `unsafe-inline` в CSP обнуляет защиту от XSS

**Файл:** `app.py:169`

```python
"script-src 'self' cdn.jsdelivr.net 'unsafe-inline'; "  # ← опасно
```

`unsafe-inline` позволяет выполнять любой инлайн-скрипт, включая XSS-нагрузку.
CSP с этим флагом защищает только от внешних скриптов, но не от инъекции внутри страницы.

**Причина проблемы:** anti-FOUC скрипт для тёмной темы в `<head>` нельзя вынести
в файл (иначе мигание). Из-за него добавили `unsafe-inline` для всего.

**Правильное решение — nonce-based CSP:**

```python
import secrets

@app.before_request
def generate_csp_nonce():
    g.csp_nonce = secrets.token_urlsafe(16)

@app.after_request
def set_security_headers(response):
    nonce = getattr(g, "csp_nonce", "")
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        f"style-src 'self' 'unsafe-inline'; "
        f"img-src 'self' data: ui-avatars.com; "
        f"connect-src 'self'; "
        f"frame-ancestors 'none';"
    )
```

```html
<!-- base.html — anti-FOUC с nonce -->
<script nonce="{{ g.csp_nonce }}">
  (function() { /* dark mode init */ })();
</script>
```

> **Бонус:** Bootstrap перенесён локально в v1.4.0 — `cdn.jsdelivr.net` из `script-src` уже можно убрать.

---

### 5.2 Audit Log хранит JSON как Text

**Файл:** `models.py:102`

```python
details = db.Column(db.Text, nullable=True)  # JSON строка
```

**Исправление:** использовать `db.Column(JSON, nullable=True)` — SQLite хранит как Text,
PostgreSQL как нативный JSON с возможностью запросов по полям.

---

## 6. Финансовая логика

### 6.1 Sharpe Ratio: population variance вместо sample variance

**Файл:** `services/portfolio_service.py:244-246`

```python
variance = sum((r - mean_r) ** 2 for r in returns) / n  # ← population std (σ)
```

Закрытые сделки — это **выборка**, а не генеральная совокупность.
Правильно делить на `(n - 1)` — формула Бесселя (sample std).

| n сделок | Sharpe завышен на |
|----------|------------------|
| 3 | +22% |
| 5 | +12% |
| 10 | +5% |

**Исправление:**

```python
variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)  # sample std
```

---

### 6.2 Налоговая база рассчитана неправильно — не по ст. 214.1 НК РФ

**Файлы:** `services/portfolio_service.py:172-222`, `constants.py:35`

Текущий `calc_tax_report` считает: `(sell_price - buy_price) * amount * 0.13`.
Это принципиально неверная формула.

**Что говорит закон:**
Доходы от облигаций регулируются **ст. 214.1 НК РФ** («Особенности определения
налоговой базы по операциям с ценными бумагами»), а **не** ст. 224 про общий НДФЛ.
Брокер — налоговый агент и сам удерживает налог.

**Правильная формула налоговой базы (ст. 214.1):**

```
Налоговая база = Доход от продажи − Расходы на приобретение

Доход от продажи  = цена продажи + НКД полученный (при продаже)
Расходы           = цена покупки + НКД уплаченный (при покупке)
                  + комиссия брокера за покупку + за продажу
```

**Что сейчас теряется:**

| Компонент | Влияние | Что происходит сейчас |
|-----------|---------|----------------------|
| НКД при покупке | Уменьшает базу | Игнорируется → база завышена |
| НКД при продаже | Увеличивает базу | Игнорируется |
| Комиссия при продаже | Уменьшает базу | Игнорируется → база завышена |
| Убытки прошлых лет | Уменьшают базу | Не учитываются |
| ЛДВ (3+ года) | Освобождение до 3M₽/год | Не реализована |

> **Важно:** купонный доход с 2021 г. брокер облагает у источника в момент выплаты.
> Его **не нужно** дублировать в годовом расчёте — иначе налог считается дважды.
> Текущий `calc_tax_report` прибавляет `coupon_income` к базе — **это ошибка**.

**Правильный расчёт:**

```python
def calc_tax_basis_per_trade(bond, rates: dict) -> dict:
    """Налоговая база одной сделки по ст. 214.1 НК РФ."""
    buy_p    = float(bond.buy_price)
    sell_p   = float(bond.sell_price) if bond.sell_price else buy_p
    comm     = float(bond.broker_commission) if bond.broker_commission else 0.0
    nkd_buy  = float(getattr(bond, "nkd_at_buy",  0) or 0)
    nkd_sell = float(getattr(bond, "nkd_at_sell", 0) or 0)
    currency = bond.currency or "RUB"
    rate     = 1.0 if currency in ["RUB", "GLD"] else rates.get(currency, 1.0)
    n        = bond.amount

    gross_income = (sell_p + nkd_sell) * n * rate
    expenses     = (buy_p  + nkd_buy)  * n * rate + comm * rate
    days_held    = (bond.sell_date - bond.purchase_date).days if (bond.purchase_date and bond.sell_date) else 0
    return {
        "gross_income": round(gross_income, 2),
        "expenses":     round(expenses, 2),
        "tax_basis":    round(max(gross_income - expenses, 0.0), 2),
        "days_held":    days_held,
    }
```

**Льгота на долгосрочное владение (ЛДВ, ст. 219.1 НК РФ):**

```python
LDV_YEARS_THRESHOLD  = 3            # минимум 3 года владения
LDV_ANNUAL_DEDUCTION = 3_000_000.0  # до 3 млн ₽ × кол-во лет

def apply_ldv(tax_basis: float, days_held: int, years_owned: int = 1) -> float:
    if days_held < LDV_YEARS_THRESHOLD * 365:
        return tax_basis
    return max(tax_basis - LDV_ANNUAL_DEDUCTION * years_owned, 0.0)
```

**Прогрессивная ставка НДФЛ 2025 (ФЗ-176 от 12.07.2024):**

```python
# constants.py — заменить NDFL_RATE: float = 0.13
NDFL_BRACKETS_2025 = [
    (2_400_000,    0.13),   # до 2.4 млн — 13%
    (5_000_000,    0.15),   # 2.4–5 млн  — 15%
    (20_000_000,   0.18),   # 5–20 млн   — 18%
    (50_000_000,   0.20),   # 20–50 млн  — 20%
    (float("inf"), 0.22),   # свыше 50 млн — 22%
]

def calc_ndfl(income: float) -> float:
    """Прогрессивный НДФЛ по шкале 2025 г. (ФЗ-176 от 12.07.2024)."""
    tax, prev = 0.0, 0.0
    for limit, rate in NDFL_BRACKETS_2025:
        if income <= prev:
            break
        tax += (min(income, limit) - prev) * rate
        prev = limit
    return round(tax, 2)
```

> **Дисклеймер в UI:** «Расчёт носит ознакомительный характер. Брокер является
> налоговым агентом по ст. 214.1 НК РФ и удерживает налог самостоятельно.
> Купонный доход уже обложен у источника — не учитывается повторно.»

---
### 6.3 Безрисковая ставка Sharpe — неправильный источник

**Файл:** `services/portfolio_service.py:258`

```python
risk_free_per_trade = 0.16 / 12  # ← ставка ЦБ РФ, захардкожена и устарела
```

**Почему ключевая ставка ЦБ — неверный выбор:**
Ключевая ставка — это стоимость однодневных денег «сегодня на завтра».
Она не характеризует доходность безрискового вложения на горизонте 1–5 лет
(типичный срок облигационной сделки).

**Правильный источник: кривая КБД (G-curve) MOEX**
MOEX ежедневно публикует кривую бескупонной доходности — доходности ОФЗ
для сроков 0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30 лет.
Это академически корректная безрисковая ставка для российского рынка:
госбумаги без кредитного риска, подобранные к горизонту портфеля.

**API MOEX для G-curve:**

```
GET https://iss.moex.com/iss/engines/stock/markets/index/securities/GCURVE.json
    ?date=2026-05-27   # опционально
```

Ответ: таблица с колонками `PERIOD` (лет) и `VALUE` (доходность %).

**Реализация в `moex.py`:**

```python
def get_gcurve_rate(maturity_years: float, trade_date: str | None = None) -> float:
    """
    Безрисковая ставка с G-curve MOEX на заданный срок.
    Линейная интерполяция между соседними точками кривой.
    Кэш 24 часа (кривая меняется раз в день).
    При сбое MOEX — возвращает последнее известное значение.
    """
    from extensions import cache

    cache_key = f"gcurve:{trade_date or 'latest'}:{maturity_years}"
    cached = cache.get(cache_key)
    if cached is not None:
        return float(cached)

    try:
        url = "https://iss.moex.com/iss/engines/stock/markets/index/securities/GCURVE.json"
        if trade_date:
            url += f"?date={trade_date}"
        res = _fetch_json(url)
        cols       = res["history"]["columns"]
        curve      = {
            float(row[cols.index("PERIOD")]): float(row[cols.index("VALUE")])
            for row in res["history"]["data"]
            if row[cols.index("PERIOD")] is not None and row[cols.index("VALUE")] is not None
        }
        periods    = sorted(curve.keys())

        if maturity_years <= periods[0]:
            rate_pct = curve[periods[0]]
        elif maturity_years >= periods[-1]:
            rate_pct = curve[periods[-1]]
        else:
            lo = max(p for p in periods if p <= maturity_years)
            hi = min(p for p in periods if p >= maturity_years)
            t  = (maturity_years - lo) / (hi - lo) if hi != lo else 0
            rate_pct = curve[lo] + t * (curve[hi] - curve[lo])

        rate = round(rate_pct / 100, 6)
        cache.set(cache_key, rate, timeout=86400)
        return rate

    except Exception as e:
        logger.warning("G-curve fetch failed: %s", e)
        return float(cache.get("gcurve:fallback") or 0.155)
```

**Использование в `calc_sharpe_ratio`:**

```python
avg_days  = sum((b.sell_date - b.purchase_date).days for b in sold_bonds
                if b.sell_date and b.purchase_date) / n
avg_years = max(avg_days / 365, 0.25)

rf_annual           = get_gcurve_rate(maturity_years=avg_years)
risk_free_per_trade = rf_annual * (avg_days / 365)

return {
    "sharpe":          round(sharpe, 2),
    "rf_annual_pct":   round(rf_annual * 100, 2),  # показывать в UI
    "rf_source":       "MOEX КБД",
    "rf_maturity_yrs": round(avg_years, 1),
    ...
}
```

---

### 6.4 Модель `Transaction` есть в БД — реализовать FIFO учёт (ст. 214.1)

**Файл:** `models.py:71`

Модель уже смигрирована (stage7, stage8). `BondPortfolio` хранит только
`buy_price` — усреднённую цену без истории транзакций.

**Почему это неверно юридически:**
По ст. 214.1 НК РФ при частичной продаже применяется метод **FIFO**:
первые купленные лоты продаются первыми.

**Пример:**
```
Куплено:  10 шт по 990₽  (01.01.2025)
Куплено:  10 шт по 1010₽ (01.06.2025)
Продано:  10 шт по 1050₽ (01.12.2025)

FIFO:    доход = (1050 - 990)  * 10 = 600₽  ← правильно
Среднее: доход = (1050 - 1000) * 10 = 500₽  ← занижает базу на 100₽
```

**Расширить Transaction — добавить поле НКД:**

```python
class Transaction(db.Model):
    ...
    nkd          = db.Column(db.Numeric(10, 4), nullable=True)    # НКД на дату сделки
    portfolio_id = db.Column(db.Integer, db.ForeignKey("bond_portfolio.id"), nullable=True)
```

**FIFO алгоритм:**

```python
def calc_fifo_pnl(isin, user_id, sell_amount, sell_price,
                  sell_nkd, sell_commission, rates) -> dict:
    buys = (Transaction.query
            .filter_by(user_id=user_id, isin=isin, tx_type="buy")
            .order_by(Transaction.tx_date.asc(), Transaction.id.asc())
            .all())
    remaining = sell_amount
    total_cost = 0.0
    for buy in buys:
        if remaining <= 0:
            break
        used       = min(buy.amount, remaining)
        buy_cost   = (float(buy.price) + float(buy.nkd or 0)) * used
        buy_comm   = float(buy.commission or 0) * (used / buy.amount)
        total_cost += buy_cost + buy_comm
        remaining  -= used

    rate         = rates.get("RUB", 1.0)
    sell_income  = (sell_price + sell_nkd) * sell_amount * rate
    expenses     = total_cost * rate + sell_commission * rate
    return {
        "tax_basis": round(max(sell_income - expenses, 0.0), 2),
        "pnl":       round(sell_income - expenses, 2),
    }
```

**Скрипт миграции:**

```python
# scripts/migrate_to_transactions.py
with app.app_context():
    for bond in BondPortfolio.query.all():
        if not Transaction.query.filter_by(portfolio_id=bond.id).first():
            db.session.add(Transaction(
                user_id=bond.user_id, isin=bond.isin, name=bond.name,
                tx_type="buy", amount=bond.amount, price=bond.buy_price,
                commission=bond.broker_commission, currency=bond.currency,
                tx_date=bond.purchase_date, portfolio_id=bond.id,
            ))
            if bond.is_sold and bond.sell_price:
                db.session.add(Transaction(
                    user_id=bond.user_id, isin=bond.isin, name=bond.name,
                    tx_type="sell", amount=bond.amount, price=bond.sell_price,
                    commission=bond.broker_commission, currency=bond.currency,
                    tx_date=bond.sell_date, portfolio_id=bond.id,
                ))
    db.session.commit()
```

> Оценка: 2–3 дня разработки. FIFO — единственный юридически корректный метод по НК РФ.

---
## 7. Тестирование

### 7.1 Текущее покрытие — 45%

Для финтех-приложения 45% — опасно мало.

| Файл | Покрытие | Приоритет | Почему |
|------|---------|-----------|--------|
| `moex.py` | ~10% | 🔴 Высокий | MOEX меняет API без предупреждения |
| `services/portfolio_service.py` | ~60% | 🟡 Средний | Финансовая математика, ошибки = деньги |
| `services/telegram_service.py` | ~5% | 🟡 Средний | OTP-коды, безопасность |
| `blueprints/portfolio.py` | ~30% | 🟡 Средний | Парсеры брокеров XLSX |
| `cbr.py` | ~0% | 🟢 Низкий | Новый модуль |

### 7.2 Тесты для circuit breaker и парсинга MOEX

```python
class TestCircuitBreaker:
    def test_opens_after_threshold_failures(self, app_ctx):
        from constants import MOEX_CIRCUIT_FAIL_THRESHOLD
        for _ in range(MOEX_CIRCUIT_FAIL_THRESHOLD):
            _circuit_failure()
        with pytest.raises(RuntimeError, match="MOEX недоступен"):
            _circuit_check()

    def test_success_resets_count(self, app_ctx):
        _circuit_failure()
        _circuit_success()
        _circuit_check()  # не должен бросать

class TestGetMoexBond:
    @patch("moex._fetch_json")
    def test_returns_none_on_empty_data(self, mock_fetch):
        mock_fetch.return_value = {"securities": {"data": [], "columns": []}}
        assert get_moex_bond("RU000A0ZZBD9") is None
```

### 7.3 Property-tests для налогов

```python
@given(sales_pnl=st.floats(min_value=0, max_value=10_000_000))
def test_tax_never_exceeds_income(sales_pnl):
    """Налог не может быть больше дохода."""
    assert calc_ndfl(sales_pnl) <= sales_pnl + 0.01
```

### 7.4 Интеграционные тесты с PostgreSQL

```bash
pip install testcontainers[postgresql]
```

```python
@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url()
```

---

## 8. Архитектура — рефакторинг

### 8.1 `blueprints/portfolio.py` — слишком большой

Файл содержит HTTP-маршруты + парсеры XLSX + парсеры брокеров + псевдонимы колонок.

**Вынести в `services/import_service.py`:**

```
services/
├── portfolio_service.py   # P&L, YTM, Sharpe, налоги
├── moex_service.py        # кэшированный MOEX
├── import_service.py      # ← новый: detect_broker, parse_vtb_xlsx, ...
└── ...
```

Это делает парсеры тестируемыми независимо от Flask.

### 8.2 Prometheus метрики

```bash
pip install prometheus-flask-exporter
```

```python
# extensions.py
from prometheus_flask_exporter import PrometheusMetrics
metrics = PrometheusMetrics.for_app_factory()
```

Автоматически считает latency и количество запросов. Добавить кастомный Gauge
для circuit breaker:

```python
moex_circuit_open = Gauge("moex_circuit_breaker_open", "1 if CB is open")
```

### 8.3 Удалить мёртвый код

`index.js` — явно устаревший, но минифицируется в build pipeline:

```python
# build_assets.py
JS_FILES = ["common", "portfolio", "sidebar", "base",
            "dashboard", "profile", "landing", "portfolio-page", "admin"]
# убрать "index"
```

---
## 9. Новые фичи (приоритизированно)

### 9.1 🟢 Sparklines в таблице позиций (2–4 часа)

Мини-графики цены за 30 дней. Вся инфраструктура уже есть — `get_bond_history_all`.

```python
@portfolio_bp.route("/api/portfolio/<int:bond_id>/sparkline")
@login_required
def bond_sparkline(bond_id):
    bond = BondPortfolio.query.filter_by(
        id=bond_id, user_id=current_user.id, is_sold=False).first_or_404()
    cache_key = f"sparkline:{bond.isin}:30"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)
    history = get_bond_history_all(bond.secid or bond.isin)
    data = {"labels": history["labels"][-30:], "data": history["data"][-30:]}
    cache.set(cache_key, data, timeout=3600)
    return jsonify(data)
```

```javascript
function renderSparkline(canvas, data) {
    new Chart(canvas, {
        type: "line",
        data: { labels: data.labels,
                datasets: [{ data: data.data, borderWidth: 1.5,
                             pointRadius: 0, tension: 0.3 }] },
        options: { responsive: false,
                   plugins: { legend: { display: false } },
                   scales: { x: { display: false }, y: { display: false } } }
    });
}
```

---

### 9.2 🟢 Ценовые алерты для Watchlist (3–5 часов)

```python
# models.py
class Watchlist(db.Model):
    ...
    alert_price     = db.Column(db.Numeric(10, 2), nullable=True)
    alert_triggered = db.Column(db.Boolean, default=False)
```

```python
# app.py — APScheduler job
def _check_price_alerts():
    with app.app_context():
        alerts = Watchlist.query.filter(
            Watchlist.alert_price.isnot(None),
            Watchlist.alert_triggered == False).all()
        for item in alerts:
            bond_data = get_moex_bond(item.isin)
            if not bond_data:
                continue
            if bond_data["price"] >= float(item.alert_price):
                user = User.query.get(item.user_id)
                if user and user.telegram_chat_id and user.telegram_notifications:
                    send_message(user.telegram_chat_id,
                        f"🎯 <b>{item.name}</b> достигла целевой цены!
"
                        f"Текущая: {bond_data['price']:.2f} ₽ / "
                        f"Цель: {float(item.alert_price):.2f} ₽")
                item.alert_triggered = True
        db.session.commit()
```

---

### 9.3 🟡 Экспорт в CSV (1–2 часа)

```python
@portfolio_bp.route("/api/portfolio/export/csv")
@login_required
def export_csv():
    bonds, _ = build_portfolio_list(
        BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all())
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "isin", "name", "amount", "buy_price", "last_price",
        "pnl", "pnl_pct", "ytm", "currency", "purchase_date"])
    writer.writeheader()
    writer.writerows(bonds)
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"  # BOM для Excel
    response.headers["Content-Disposition"] = (
        f'attachment; filename="portfolio_{date.today()}.csv"')
    return response
```

---

### 9.4 🟡 Modified Duration

Для облигаций — более корректная мера риска, чем Sharpe:
«при росте ставок на 1% позиция потеряет ~X%».

```python
def calc_modified_duration(coupon_pct, freq, ytm, years_to_maturity) -> float:
    if ytm <= 0 or freq <= 0 or years_to_maturity <= 0:
        return 0.0
    c, y, n = (coupon_pct/100)/freq, (ytm/100)/freq, int(years_to_maturity*freq)
    if n == 0:
        return 0.0
    price    = sum(c/(1+y)**t for t in range(1, n+1)) + 1/(1+y)**n
    macaulay = (sum((t/freq)*(c/(1+y)**t) for t in range(1, n+1))
                + (n/freq)*(1/(1+y)**n)) / price
    return round(macaulay / (1 + y), 2)
```

---

### 9.5 🟡 Анализ диверсификации

Новая вкладка «Риски» — концентрация по эмитентам + scatter plot дюрация/YTM:

```python
def calc_concentration_risk(portfolio_list) -> dict:
    by_issuer = defaultdict(float)
    total = sum(b["current_value_rub"] for b in portfolio_list)
    for bond in portfolio_list:
        by_issuer[bond["isin"][:6]] += bond["current_value_rub"]
    issuers = sorted(by_issuer.items(), key=lambda x: x[1], reverse=True)
    return {
        "top3_pct": sum(v for _, v in issuers[:3]) / total * 100 if total else 0,
        "issuers": [{"name": k, "pct": round(v/total*100, 1)} for k, v in issuers[:10]],
    }
```

---
### 9.6 🔵 Страница администратора — аналитический отчёт

Сейчас `/admin` показывает только таблицу пользователей. Добавить полноценный
аналитический дашборд с возможностью печати в PDF через `window.print()`.

#### Backend — `/api/admin/analytics`

Новый эндпоинт в `blueprints/admin.py` собирает всю агрегированную статистику платформы:

```python
@admin_bp.route("/api/admin/analytics")
@admin_required
def admin_analytics():
    from sqlalchemy import func, distinct
    from collections import Counter, defaultdict

    # Пользователи
    users_total      = User.query.count()
    users_with_tg    = User.query.filter(User.telegram_chat_id.isnot(None)).count()
    users_with_email = User.query.filter(
        User.email.isnot(None), User.email_notifications == True).count()
    cutoff_30d = datetime.utcnow() - timedelta(days=30)
    logins_30d = (AuditLog.query
        .filter(AuditLog.action == "login_ok", AuditLog.created_at >= cutoff_30d)
        .with_entities(func.count(distinct(AuditLog.user_id))).scalar() or 0)

    # Портфели
    active_bonds = BondPortfolio.query.filter_by(is_sold=False).all()
    closed_bonds = BondPortfolio.query.filter_by(is_sold=True).all()
    total_value  = sum(float(b.last_price or b.buy_price) * b.amount for b in active_bonds)

    by_user = defaultdict(float)
    for b in active_bonds:
        by_user[b.user_id] += float(b.last_price or b.buy_price) * b.amount
    sizes = sorted(by_user.values())
    avg_portfolio = round(sum(sizes)/len(sizes), 2) if sizes else 0
    median_pf     = round(sizes[len(sizes)//2], 2) if sizes else 0

    # Топ-10 облигаций по числу держателей
    counter, names = Counter(), {}
    for b in active_bonds:
        counter[b.isin] += 1
        names[b.isin] = b.name or b.isin
    top_bonds = [{"isin": i, "name": names[i], "holders": c}
                 for i, c in counter.most_common(10)]

    # Средняя YTM по всем активным позициям
    ytm_vals = [float(get_bond_cached(b.isin)["ytm"])
                for b in active_bonds
                if get_bond_cached(b.isin) and get_bond_cached(b.isin).get("ytm")]
    avg_ytm = round(sum(ytm_vals)/len(ytm_vals), 2) if ytm_vals else 0

    # Распределение размеров портфелей по бакетам
    brackets = [("< 50 тыс", 0, 50_000), ("50-200 тыс", 50_000, 200_000),
                ("200-500 тыс", 200_000, 500_000), ("500тыс-1млн", 500_000, 1_000_000),
                ("> 1 млн", 1_000_000, float("inf"))]
    distribution = [{"label": lbl, "count": sum(1 for v in sizes if lo <= v < hi)}
                    for lbl, lo, hi in brackets]

    return jsonify({
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "users": {"total": users_total, "with_telegram": users_with_tg,
                  "with_email_notifications": users_with_email, "active_last_30d": logins_30d},
        "portfolio": {"active_positions": len(active_bonds), "closed_positions": len(closed_bonds),
                      "total_value_rub": round(total_value, 2),
                      "avg_portfolio_rub": avg_portfolio, "median_portfolio_rub": median_pf,
                      "avg_ytm_pct": avg_ytm, "unique_users_with_positions": len(by_user),
                      "size_distribution": distribution},
        "top_bonds": top_bonds,
        "system": {"moex_circuit_breaker_open": bool(cache.get("moex_cb:open_until")),
                   "moex_fail_count": cache.get("moex_cb:fail_count") or 0,
                   "cache_type": current_app.config.get("CACHE_TYPE", "unknown")},
    })
```


#### Мокап страницы `/admin/report`

```
┌─────────────────────────────────────────────────┐
│  InvestTrack — Аналитический отчёт               │
│  Сформирован: 2026-05-27 09:15 UTC               │
│                              [🖨 Печать/PDF] [←]  │
├────────────┬────────────┬───────────────────────── ┤
│Пользователей│  Всего AUM │  Активных позиций        │
│    24       │  14.2 млн ₽│       187                │
├────────────┴────────────┴──────────────────────────┤
│ ПОРТФЕЛИ                                           │
│  Ср. размер: 591 542 ₽    Медиана: 320 000 ₽       │
│  Ср. YTM портфеля: 14.8%                           │
│                                                    │
│  Распределение размеров портфелей:                 │
│  ████░░░  < 50 тыс      — 4 польз.                 │
│  ██████░  50-200 тыс    — 7 польз.                 │
│  ███████  200-500 тыс   — 8 польз.                 │
│  ██████░  500тыс-1млн   — 3 польз.                 │
│  ████░░░  > 1 млн       — 2 польз.                 │
├────────────────────────────────────────────────────┤
│ ТОП-10 ОБЛИГАЦИЙ ПО ЧИСЛУ ДЕРЖАТЕЛЕЙ               │
│  1. ОФЗ 26238   RU000A1038V6   — 18 польз.         │
│  2. Сбербанк Б  RU000A103T89   — 12 польз.         │
│  ...                                               │
├────────────────────────────────────────────────────┤
│ ВОВЛЕЧЁННОСТЬ                                      │
│  Telegram подключён: 14 / 24 (58%)                 │
│  Email уведомления:   9 / 24 (38%)                 │
│  Активны за 30 дней: 19 пользователей              │
├────────────────────────────────────────────────────┤
│ СИСТЕМНЫЙ СТАТУС                                   │
│  MOEX Circuit Breaker:  ● CLOSED (норма)           │
│  Тип кэша: FileSystemCache                         │
└────────────────────────────────────────────────────┘
```


#### Шаблон `templates/admin_report.html`

```html
{% extends "base_public.html" %}
{% block content %}
<div class="report-actions d-print-none mb-3">
  <a href="/admin" class="btn btn-outline-secondary btn-sm">← Назад</a>
  <button onclick="window.print()" class="btn btn-primary btn-sm ms-2">
    🖨 Печать / Сохранить PDF
  </button>
</div>

<h2>InvestTrack — Аналитический отчёт</h2>
<p class="text-muted" id="generated-at"></p>

<!-- Верхние метрики -->
<div class="row g-3 mb-4">
  <div class="col-md-3"><div class="admin-metric-card">
    <div class="metric-label">Пользователей</div>
    <div class="metric-value" id="users-total">—</div>
  </div></div>
  <div class="col-md-3"><div class="admin-metric-card">
    <div class="metric-label">Всего AUM</div>
    <div class="metric-value" id="total-aum">—</div>
    <div class="metric-sub">сумма всех портфелей</div>
  </div></div>
  <div class="col-md-3"><div class="admin-metric-card">
    <div class="metric-label">Активных позиций</div>
    <div class="metric-value" id="active-pos">—</div>
  </div></div>
  <div class="col-md-3"><div class="admin-metric-card">
    <div class="metric-label">Ср. YTM портфелей</div>
    <div class="metric-value" id="avg-ytm">—</div>
  </div></div>
</div>

<!-- Вторая строка метрик -->
<div class="row g-3 mb-4">
  <div class="col-md-4"><div class="admin-metric-card">
    <div class="metric-label">Ср. размер портфеля</div>
    <div class="metric-value" id="avg-pf">—</div>
  </div></div>
  <div class="col-md-4"><div class="admin-metric-card">
    <div class="metric-label">Медианный портфель</div>
    <div class="metric-value" id="med-pf">—</div>
  </div></div>
  <div class="col-md-4"><div class="admin-metric-card">
    <div class="metric-label">Активны за 30 дней</div>
    <div class="metric-value" id="active-30d">—</div>
  </div></div>
</div>

<h5 class="mt-4">Распределение размеров портфелей</h5>
<div id="size-dist" class="mb-4"></div>

<h5>Топ-10 самых популярных облигаций</h5>
<table class="table table-sm mb-4">
  <thead><tr><th>#</th><th>Название</th><th>ISIN</th><th>Держателей</th></tr></thead>
  <tbody id="top-bonds-tbody"></tbody>
</table>

<h5>Вовлечённость</h5>
<div id="engagement" class="mb-4"></div>

<h5>Системный статус</h5>
<div id="system-status"></div>

<style>
  .admin-metric-card {
    border: 1px solid var(--bs-border-color);
    border-radius: 8px; padding: 16px; text-align: center;
  }
  .metric-value { font-size: 2rem; font-weight: 700; }
  .metric-sub   { font-size: .75rem; color: var(--bs-secondary-color); }
  .dist-bar     { height: 20px; background: var(--bs-primary);
                  border-radius: 4px; transition: width .4s; }
  @media print {
    .report-actions { display: none !important; }
    @page { size: A4; margin: 20mm; }
  }
</style>

<script>
document.addEventListener("DOMContentLoaded", async () => {
  const d = await fetch("/api/admin/analytics").then(r => r.json());

  document.getElementById("generated-at").textContent = "Сформирован: " + d.generated_at;
  document.getElementById("users-total").textContent  = d.users.total;
  document.getElementById("avg-ytm").textContent      = d.portfolio.avg_ytm_pct + "%";
  document.getElementById("active-pos").textContent   = d.portfolio.active_positions;
  document.getElementById("active-30d").textContent   = d.users.active_last_30d;

  const fmt = v => v >= 1e6
    ? (v / 1e6).toFixed(1) + " млн ₽"
    : (v / 1e3).toFixed(0) + " тыс ₽";

  document.getElementById("total-aum").textContent = fmt(d.portfolio.total_value_rub);
  document.getElementById("avg-pf").textContent    = fmt(d.portfolio.avg_portfolio_rub);
  document.getElementById("med-pf").textContent    = fmt(d.portfolio.median_portfolio_rub);

  // Горизонтальные бары распределения
  const maxCount = Math.max(...d.portfolio.size_distribution.map(b => b.count)) || 1;
  const distEl = document.getElementById("size-dist");
  d.portfolio.size_distribution.forEach(b => {
    const pct = Math.round(b.count / maxCount * 100);
    distEl.innerHTML += `<div class="d-flex align-items-center gap-2 mb-2">
      <div style="width:130px;font-size:.85rem">${b.label}</div>
      <div class="dist-bar" style="width:${Math.max(pct,2)}%;min-width:4px"></div>
      <div style="font-size:.85rem">${b.count} польз.</div>
    </div>`;
  });

  // Топ облигаций
  const tbody = document.getElementById("top-bonds-tbody");
  d.top_bonds.forEach((b, i) => {
    tbody.innerHTML += `<tr>
      <td>${i + 1}</td>
      <td>${b.name}</td>
      <td><code>${b.isin}</code></td>
      <td><strong>${b.holders}</strong></td>
    </tr>`;
  });

  // Вовлечённость
  const u = d.users;
  const pct = n => u.total ? Math.round(n / u.total * 100) : 0;
  document.getElementById("engagement").innerHTML =
    `<p>Telegram: <strong>${u.with_telegram} / ${u.total}</strong> (${pct(u.with_telegram)}%)</p>
     <p>Email: <strong>${u.with_email_notifications} / ${u.total}</strong>
       (${pct(u.with_email_notifications)}%)</p>`;

  // Системный статус
  const s   = d.system;
  const cbEl = s.moex_circuit_breaker_open
    ? `<span class="badge bg-danger">⚡ OPEN — MOEX недоступен</span>`
    : `<span class="badge bg-success">● CLOSED — норма</span>`;
  document.getElementById("system-status").innerHTML =
    `<p>MOEX Circuit Breaker: ${cbEl} (ошибок подряд: ${s.moex_fail_count})</p>
     <p>Тип кэша: <code>${s.cache_type}</code></p>`;
});
</script>
{% endblock %}
```

**Маршрут и кнопка:**

```python
# blueprints/admin.py
@admin_bp.route("/admin/report")
@admin_required
def admin_report():
    return render_template("admin_report.html")
```

```html
<!-- templates/admin.html — добавить кнопку рядом с заголовком -->
<a href="/admin/report" target="_blank" class="btn btn-outline-primary btn-sm">
  📊 Аналитический отчёт
</a>
```

---
## 10. Мелкие code smells

| # | Файл | Строка | Проблема | Исправление |
|---|------|--------|----------|-------------|
| 1 | `app.py` | 343 | `/tmp/investtrack_scheduler.lock` — Unix путь | `tempfile.gettempdir()` |
| 2 | `blueprints/portfolio.py` | 26 | `from moex import _fetch_json` — приватное API | создать публичную обёртку |
| 3 | `services/portfolio_service.py` | 86 | `b.get("ytm")` — falsy для `ytm=0.0` | `b.get("ytm") is not None` |
| 4 | `models.py` | 18 | `User.avatar` vs `avatar_path` — несогласованно | переименовать в `avatar_path` |
| 5 | `constants.py` | 35 | `NDFL_RATE = 0.13` — устаревшая плоская ставка | заменить на `calc_ndfl()` по ст. 214.1 НК РФ |
| 6 | `services/portfolio_service.py` | 258 | `0.16 / 12` захардкожено, неверный источник | `get_gcurve_rate(avg_years)` из moex.py |
| 7 | `build_assets.py` | JS_FILES | `"index"` — мёртвый файл в сборке | удалить |
| 8 | `blueprints/auth.py` | — | Проверить ключ OTP: должно быть `otp:{user_id}` | — |
| 9 | `moex.py` | 466 | Fallback курсы USD=90, CNY=12.5 — устарели | обновить значения |
| 10 | `templates/index.html` | footer | `© 2025` захардкожен | `© {{ now.year }}` через `jinja_env.globals` |

---

## 11. Приоритетный план

### Неделя 1 — Критические баги и быстрые wins

```
[ ] Исправить fcntl для Windows (app.py:2) — 30 минут
[ ] Вынести get_currency_rates() из build_portfolio_entry — 1 час
[ ] Исправить Sharpe: / n → / (n - 1) — 15 минут
[ ] Удалить index.js из build_assets.py — 10 минут
[ ] Обновить NDFL: calc_ndfl() с прогрессивной шкалой 2025 — 2 часа
```

### Неделя 2 — Производительность и тесты

```
[ ] ThreadPoolExecutor для calc_coupon_income — 2 часа
[ ] Кэширование /api/portfolio/sharpe и /api/portfolio/tax — 1 час
[ ] Тесты для moex.py (circuit breaker, парсинг API) — 4 часа
[ ] Вынести import_service.py из blueprint — 3 часа
```

### Неделя 3 — Безопасность и финансовая логика

```
[ ] CSP nonce вместо unsafe-inline — 3 часа
[ ] AuditLog.details: Text → JSON (миграция) — 1 час
[ ] get_gcurve_rate() в moex.py (G-curve MOEX) — 3 часа
[ ] Prometheus метрики + circuit breaker gauge — 2 часа
```

### Неделя 4–5 — Новые фичи

```
[ ] Аналитический отчёт администратора (admin_report.html) — 6 часов
[ ] Sparklines в таблице позиций — 4 часа
[ ] Ценовые алерты для Watchlist — 5 часов
[ ] CSV экспорт — 2 часа
[ ] Modified Duration в таблице и PDF — 3 часа
[ ] Страница анализа диверсификации — 6 часов
```

### Долгосрочно (Sprint 3+)

```
[ ] FIFO учёт через Transaction (ст. 214.1 НК РФ):
    - get_gcurve_rate уже готова (неделя 3)
    - scripts/migrate_to_transactions.py
    - calc_fifo_pnl() в portfolio_service
    - хранение НКД на дату каждой сделки
    - обновить calc_tax_report под новую базу
[ ] Обновить UI налогового раздела:
    - убрать coupon_income из расчёта (брокер уже удержал)
    - добавить строку ЛДВ-льготы
    - дисклеймер по ст. 214.1
[ ] E2E тесты Playwright (login → add bond → sell → tax report)
[ ] Prometheus + Grafana dashboard в docker-compose
[ ] Активировать deploy job в CI (нужны secrets)
```

---

> **Итог:** проект технически здоровый, но есть несколько мест где срезаны углы,
> которые в production превратятся в инциденты. Начните с критических багов
> (Windows-несовместимость, N+1, Sharpe formula) — они дешевле всего исправить
> сейчас и дороже всего обнаружить потом.
