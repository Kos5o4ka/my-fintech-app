# Инструкция по интеграции T-Invest API для импорта портфеля

> **Для кого:** AI-агент, реализующий интеграцию на сайте. Документацию читать нельзя — всё необходимое есть в этом файле.

---

## 1. Что такое T-Invest API

T-Invest API — это **gRPC-интерфейс** брокера Т-Банк (бывший Тинькофф) для доступа к торговой платформе Т-Инвестиции. Также поддерживаются REST и WebSocket.

**Базовые адреса:**

| Контур | Адрес |
|--------|-------|
| Prod (биржа) | `invest-public-api.tbank.ru:443` |
| Sandbox (тест) | `sandbox-invest-public-api.tbank.ru:443` |

Все данные предоставляются бесплатно. Для доступа обязательно нужен токен.

---

## 2. Получение токена доступа

### Типы токенов

| Тип | Права |
|-----|-------|
| `read-only` | Только чтение: портфель, котировки, операции. **Достаточен для импорта портфеля.** |
| `full-access` | Все методы, включая выставление ордеров |
| `transfer-access` | Full-access + переводы между счетами |
| `sandbox` | Только для тестовой среды |

**Для задачи импорта портфеля используется `read-only` токен.**

### Как пользователю получить токен

Пользователь должен сделать это самостоятельно в браузере:

1. Открыть [https://www.tbank.ru/invest/settings/](https://www.tbank.ru/invest/settings/) и авторизоваться.
2. Убедиться, что функция **«Подтверждение сделок кодом»** отключена.
3. Нажать «Выпустить токен» → выбрать тип **read-only** → скопировать токен.

> ⚠️ Токен отображается **только один раз**. Если не сохранить — придётся выпускать новый.
> ⚠️ Срок жизни токена — **3 месяца с последнего использования**.

### Как агент должен принять токен на сайте

```html
<!-- Форма ввода токена на странице настроек -->
<input type="password" id="t-invest-token" placeholder="Вставьте токен T-Invest API" />
<button onclick="saveToken()">Сохранить и импортировать</button>
```

Токен нужно сохранить в защищённом месте (например, в переменных окружения на сервере или в зашифрованном хранилище). **Никогда не передавать токен на клиентскую сторону и не хранить в localStorage.**

---

## 3. Авторизация в запросах

Токен передаётся в заголовке каждого запроса:

```
Authorization: Bearer <токен>
```

**Пример для REST (fetch):**

```javascript
const headers = {
  'Authorization': `Bearer ${token}`,
  'Content-Type': 'application/json',
};
```

**Пример для gRPC (metadata):**

```
Authorization: Bearer t.QtEo8ahkNFX4RTpbqp0u4z4GDZq27HzUp6AotJASBx7_...
```

---

## 4. Выбор протокола для веб-сайта

Для интеграции на сайте **рекомендуется REST API** через бэкенд-прокси. Прямые запросы из браузера с токеном недопустимы (CORS, безопасность).

**Архитектура:**

```
Браузер (ваш сайт)
       ↓  REST-запрос к вашему бэкенду
Ваш сервер (Node.js / Python / PHP / etc.)
       ↓  REST/gRPC-запрос с токеном
T-Invest API (invest-public-api.tbank.ru:443)
       ↓  JSON-ответ
Ваш сервер → парсинг → ответ браузеру
```

**Почему не напрямую из браузера:**
- Токен будет виден в DevTools → угроза безопасности.
- CORS может блокировать запросы.

---

## 5. Необходимые REST-методы для импорта портфеля

Все REST-запросы идут методом **POST** по базовому URL:

```
https://invest-public-api.tbank.ru/rest
```

### 5.1 Получить список счетов пользователя

**Endpoint:** `POST /tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts`

**Body:**
```json
{}
```

**Ответ:**
```json
{
  "accounts": [
    {
      "id": "2000123456",
      "type": "ACCOUNT_TYPE_TINKOFF",
      "name": "Мой брокерский счёт",
      "status": "ACCOUNT_STATUS_OPEN",
      "openedDate": { "seconds": "1600000000", "nanos": 0 },
      "accessLevel": "ACCOUNT_ACCESS_LEVEL_FULL_ACCESS"
    }
  ]
}
```

**Важные поля:**
- `id` — идентификатор счёта, нужен во всех последующих запросах.
- `type` — тип счёта: `ACCOUNT_TYPE_TINKOFF` (брокерский), `ACCOUNT_TYPE_TINKOFF_IIS` (ИИС).
- `status` — `ACCOUNT_STATUS_OPEN` = открыт, `ACCOUNT_STATUS_CLOSED` = закрыт.

---

### 5.2 Получить портфель по счёту

**Endpoint:** `POST /tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio`

**Body:**
```json
{
  "accountId": "2000123456",
  "currency": "RUB"
}
```

**Ответ (сокращён):**
```json
{
  "totalAmountShares": { "currency": "RUB", "units": "150000", "nano": 500000000 },
  "totalAmountBonds": { "currency": "RUB", "units": "50000", "nano": 0 },
  "totalAmountEtf": { "currency": "RUB", "units": "30000", "nano": 0 },
  "totalAmountCurrencies": { "currency": "RUB", "units": "10000", "nano": 0 },
  "totalAmountPortfolio": { "currency": "RUB", "units": "240000", "nano": 500000000 },
  "expectedYield": { "units": "15", "nano": 300000000 },
  "positions": [
    {
      "figi": "BBG004730N88",
      "instrumentType": "share",
      "quantity": { "units": "10", "nano": 0 },
      "averagePositionPrice": { "currency": "RUB", "units": "250", "nano": 0 },
      "expectedYield": { "units": "150", "nano": 0 },
      "currentNkd": { "currency": "RUB", "units": "0", "nano": 0 },
      "currentPrice": { "currency": "RUB", "units": "265", "nano": 0 },
      "averagePositionPriceFifo": { "currency": "RUB", "units": "248", "nano": 0 },
      "quantityLots": { "units": "1", "nano": 0 },
      "blocked": false,
      "instrumentUid": "e6123145-9665-43e0-8413-cd61b8aa9b13"
    }
  ]
}
```

**Важные поля в positions:**
- `figi` — идентификатор инструмента (FIGI).
- `instrumentType` — `share`, `bond`, `etf`, `currency`.
- `quantity` — количество лотов/штук.
- `averagePositionPrice` — средняя цена покупки.
- `currentPrice` — текущая цена.
- `expectedYield` — незафиксированная прибыль/убыток.

---

### 5.3 Получить информацию об инструменте по FIGI

**Endpoint:** `POST /tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy`

**Body:**
```json
{
  "idType": "INSTRUMENT_ID_TYPE_FIGI",
  "id": "BBG004730N88"
}
```

**Ответ:**
```json
{
  "instrument": {
    "figi": "BBG004730N88",
    "ticker": "SBER",
    "classCode": "TQBR",
    "isin": "RU0009029540",
    "lot": 10,
    "currency": "rub",
    "name": "Сбер Банк",
    "exchange": "MOEX",
    "sector": "financial",
    "instrumentType": "share",
    "uid": "e6123145-9665-43e0-8413-cd61b8aa9b13",
    "countryOfRisk": "RU",
    "countryOfRiskName": "Российская Федерация"
  }
}
```

---

### 5.4 Получить историю операций (сделки, пополнения, дивиденды)

**Endpoint:** `POST /tinkoff.public.invest.api.contract.v1.OperationsService/GetOperations`

**Body:**
```json
{
  "accountId": "2000123456",
  "from": { "seconds": "1700000000", "nanos": 0 },
  "to": { "seconds": "1720000000", "nanos": 0 },
  "state": "OPERATION_STATE_EXECUTED",
  "figi": ""
}
```

> Поле `from` / `to` — это тип **Timestamp** (секунды с эпохи Unix). Смотри раздел 7.

**Ответ:**
```json
{
  "operations": [
    {
      "id": "12345678",
      "parentOperationId": "",
      "currency": "RUB",
      "payment": { "currency": "RUB", "units": "-25000", "nano": 0 },
      "price": { "currency": "RUB", "units": "250", "nano": 0 },
      "state": "OPERATION_STATE_EXECUTED",
      "quantity": 100,
      "quantityRest": 0,
      "figi": "BBG004730N88",
      "instrumentType": "share",
      "date": { "seconds": "1700500000", "nanos": 0 },
      "type": "Покупка ценных бумаг",
      "operationType": "OPERATION_TYPE_BUY",
      "trades": []
    }
  ]
}
```

**Типы операций (`operationType`):**
- `OPERATION_TYPE_BUY` — покупка
- `OPERATION_TYPE_SELL` — продажа
- `OPERATION_TYPE_BROKER_FEE` — комиссия брокера
- `OPERATION_TYPE_DIVIDEND` — дивиденды
- `OPERATION_TYPE_COUPON` — купонные выплаты
- `OPERATION_TYPE_INPUT` — пополнение счёта
- `OPERATION_TYPE_OUTPUT` — вывод средств

---

### 5.5 Получить текущие котировки инструментов

**Endpoint:** `POST /tinkoff.public.invest.api.contract.v1.MarketDataService/GetLastPrices`

**Body:**
```json
{
  "figi": ["BBG004730N88", "BBG00475KKY8"]
}
```

**Ответ:**
```json
{
  "lastPrices": [
    {
      "figi": "BBG004730N88",
      "price": { "units": "265", "nano": 500000000 },
      "time": { "seconds": "1720000000", "nanos": 0 }
    }
  ]
}
```

---

### 5.6 Получить доходность портфеля

**Endpoint:** `POST /tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolioStream`  
*(для разового запроса используй GetPortfolio из п. 5.2 — поле `expectedYield` содержит совокупную доходность)*

---

## 6. Примеры кода на Node.js (бэкенд)

### Базовый fetch-клиент

```javascript
// lib/tinvest.js
const BASE_URL = 'https://invest-public-api.tbank.ru/rest';

async function tinvestRequest(method, body, token) {
  const response = await fetch(`${BASE_URL}/${method}`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(`T-Invest API error ${response.status}: ${err.message || response.statusText}`);
  }

  return response.json();
}

module.exports = { tinvestRequest };
```

### Получить все счета

```javascript
async function getAccounts(token) {
  return tinvestRequest(
    'tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts',
    {},
    token
  );
}
```

### Получить портфель

```javascript
async function getPortfolio(accountId, token) {
  return tinvestRequest(
    'tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio',
    { accountId, currency: 'RUB' },
    token
  );
}
```

### Обогатить позиции названиями инструментов

```javascript
async function enrichPositions(positions, token) {
  const enriched = await Promise.all(positions.map(async (pos) => {
    try {
      const info = await tinvestRequest(
        'tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy',
        { idType: 'INSTRUMENT_ID_TYPE_FIGI', id: pos.figi },
        token
      );
      return {
        ...pos,
        ticker: info.instrument.ticker,
        name: info.instrument.name,
        sector: info.instrument.sector,
        exchange: info.instrument.exchange,
      };
    } catch {
      return pos; // если инструмент недоступен — возвращаем как есть
    }
  }));
  return enriched;
}
```

---

## 7. Работа с нестандартными типами данных

### MoneyValue → обычное число

Все денежные значения в API возвращаются в формате `MoneyValue`:

```json
{ "currency": "RUB", "units": "114", "nano": 250000000 }
```

**Конвертация в JavaScript:**

```javascript
function moneyValueToFloat(mv) {
  if (!mv) return 0;
  const units = parseInt(mv.units || 0, 10);
  const nano = parseInt(mv.nano || 0, 10);
  return units + nano / 1_000_000_000;
}

// Пример:
// { units: "114", nano: 250000000 } → 114.25
// { units: "-200", nano: -200000000 } → -200.20
```

### Quotation → обычное число (аналогично, без валюты)

```javascript
function quotationToFloat(q) {
  if (!q) return 0;
  const units = parseInt(q.units || 0, 10);
  const nano = parseInt(q.nano || 0, 10);
  return units + nano / 1_000_000_000;
}
```

### Timestamp → дата JavaScript

```javascript
function timestampToDate(ts) {
  if (!ts) return null;
  return new Date(parseInt(ts.seconds, 10) * 1000);
}

// Обратно:
function dateToTimestamp(date) {
  const seconds = Math.floor(date.getTime() / 1000);
  return { seconds: String(seconds), nanos: 0 };
}
```

---

## 8. Полный сценарий импорта портфеля

```javascript
// routes/portfolio.js — пример Express-роута

const { tinvestRequest } = require('../lib/tinvest');
const { moneyValueToFloat, quotationToFloat, timestampToDate } = require('../lib/converters');

async function importPortfolio(req, res) {
  const { token } = req.body; // токен от пользователя

  try {
    // 1. Получаем список счетов
    const { accounts } = await tinvestRequest(
      'tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts',
      {},
      token
    );

    const openAccounts = accounts.filter(a => a.status === 'ACCOUNT_STATUS_OPEN');

    // 2. Для каждого счёта получаем портфель
    const portfolios = await Promise.all(openAccounts.map(async (account) => {
      const portfolio = await tinvestRequest(
        'tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio',
        { accountId: account.id, currency: 'RUB' },
        token
      );

      // 3. Конвертируем денежные значения
      const positions = portfolio.positions.map(pos => ({
        figi: pos.figi,
        instrumentType: pos.instrumentType,
        quantity: quotationToFloat(pos.quantity),
        averagePrice: moneyValueToFloat(pos.averagePositionPrice),
        currentPrice: moneyValueToFloat(pos.currentPrice),
        expectedYield: moneyValueToFloat(pos.expectedYield),
        currentValue: moneyValueToFloat(pos.currentPrice) * quotationToFloat(pos.quantity),
      }));

      // 4. Получаем тикеры и названия
      const figiList = [...new Set(positions.map(p => p.figi))];
      const instrumentsMap = {};
      for (const figi of figiList) {
        try {
          const { instrument } = await tinvestRequest(
            'tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy',
            { idType: 'INSTRUMENT_ID_TYPE_FIGI', id: figi },
            token
          );
          instrumentsMap[figi] = {
            ticker: instrument.ticker,
            name: instrument.name,
            sector: instrument.sector,
            exchange: instrument.exchange,
          };
        } catch { /* пропускаем */ }
      }

      const enrichedPositions = positions.map(p => ({
        ...p,
        ...(instrumentsMap[p.figi] || {}),
      }));

      return {
        accountId: account.id,
        accountName: account.name,
        accountType: account.type,
        totalValue: moneyValueToFloat(portfolio.totalAmountPortfolio),
        totalShares: moneyValueToFloat(portfolio.totalAmountShares),
        totalBonds: moneyValueToFloat(portfolio.totalAmountBonds),
        totalEtf: moneyValueToFloat(portfolio.totalAmountEtf),
        totalCash: moneyValueToFloat(portfolio.totalAmountCurrencies),
        expectedYieldPercent: quotationToFloat(portfolio.expectedYield),
        positions: enrichedPositions,
      };
    }));

    res.json({ success: true, portfolios });

  } catch (err) {
    res.status(400).json({ success: false, error: err.message });
  }
}

module.exports = { importPortfolio };
```

---

## 9. Лимиты запросов (важно!)

| Сервис | Лимит |
|--------|-------|
| Сервис инструментов | 200 запросов/мин |
| Сервис счетов | 100 запросов/мин |
| Сервис операций (портфель) | 200 запросов/мин |
| Сервис котировок | 600 запросов/мин |

**Рекомендация:** не превышать **50 запросов в секунду** суммарно.

**Как соблюдать лимиты при обогащении инструментами:**

```javascript
// Вместо Promise.all для сотни инструментов — используй батчинг
async function batchGetInstruments(figiList, token, batchSize = 5) {
  const results = {};
  for (let i = 0; i < figiList.length; i += batchSize) {
    const batch = figiList.slice(i, i + batchSize);
    await Promise.all(batch.map(async (figi) => {
      try {
        const { instrument } = await tinvestRequest(
          'tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy',
          { idType: 'INSTRUMENT_ID_TYPE_FIGI', id: figi },
          token
        );
        results[figi] = instrument;
      } catch { /* пропускаем */ }
    }));
    if (i + batchSize < figiList.length) {
      await new Promise(r => setTimeout(r, 200)); // пауза 200мс между батчами
    }
  }
  return results;
}
```

---

## 10. Обработка ошибок

### Коды ошибок API

| Код | Причина |
|-----|---------|
| `40003` | Токен недействителен или истёк (`authentication token is missing or invalid`) |
| `40001` | Нет доступа к счёту |
| `50002` | Превышен лимит запросов |

**Обработка в коде:**

```javascript
async function safeRequest(method, body, token) {
  try {
    return await tinvestRequest(method, body, token);
  } catch (err) {
    if (err.message.includes('40003')) {
      throw new Error('Токен T-Invest API устарел. Пожалуйста, выпустите новый токен в настройках Т-Инвестиций.');
    }
    if (err.message.includes('50002')) {
      // Подождать и повторить
      await new Promise(r => setTimeout(r, 60_000));
      return tinvestRequest(method, body, token);
    }
    throw err;
  }
}
```

---

## 11. Безопасность токена

- **Никогда** не передавать токен на фронтенд (браузер).
- Хранить токен в зашифрованном виде в БД (например, через `crypto.createCipher` или библиотеку `bcrypt`/`jsonwebtoken`).
- Все запросы к T-Invest API делать **только с бэкенда**.
- Добавить возможность пользователю отозвать/заменить токен в настройках сайта.
- Логировать попытки использования токена, при ошибке `40003` уведомлять пользователя.

**Пример хранения токена (Node.js + переменные окружения для одного пользователя / база для нескольких):**

```javascript
// Для нескольких пользователей — шифруем перед сохранением в БД
const crypto = require('crypto');

function encryptToken(token) {
  const iv = crypto.randomBytes(16);
  const key = Buffer.from(process.env.ENCRYPTION_KEY, 'hex'); // 32 байта
  const cipher = crypto.createCipheriv('aes-256-cbc', key, iv);
  const encrypted = Buffer.concat([cipher.update(token), cipher.final()]);
  return iv.toString('hex') + ':' + encrypted.toString('hex');
}

function decryptToken(encrypted) {
  const [ivHex, dataHex] = encrypted.split(':');
  const iv = Buffer.from(ivHex, 'hex');
  const key = Buffer.from(process.env.ENCRYPTION_KEY, 'hex');
  const decipher = crypto.createDecipheriv('aes-256-cbc', key, iv);
  const decrypted = Buffer.concat([decipher.update(Buffer.from(dataHex, 'hex')), decipher.final()]);
  return decrypted.toString();
}
```

---

## 12. Структура данных для сохранения в БД сайта

При импорте рекомендуется сохранять следующую структуру:

```sql
-- Таблица токенов пользователей
CREATE TABLE user_tokens (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL,
  encrypted_token TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  last_used_at TIMESTAMP,
  is_active BOOLEAN DEFAULT TRUE
);

-- Таблица счетов
CREATE TABLE broker_accounts (
  id VARCHAR(50) PRIMARY KEY,  -- accountId от T-Invest
  user_id INT NOT NULL,
  name VARCHAR(255),
  type VARCHAR(50),
  last_synced_at TIMESTAMP
);

-- Таблица позиций портфеля
CREATE TABLE portfolio_positions (
  id SERIAL PRIMARY KEY,
  account_id VARCHAR(50),
  figi VARCHAR(20),
  ticker VARCHAR(20),
  name VARCHAR(255),
  instrument_type VARCHAR(20),
  quantity DECIMAL,
  average_price DECIMAL,
  current_price DECIMAL,
  current_value DECIMAL,
  expected_yield DECIMAL,
  currency VARCHAR(10),
  sector VARCHAR(100),
  exchange VARCHAR(50),
  synced_at TIMESTAMP DEFAULT NOW()
);
```

---

## 13. Тестирование через Sandbox

Для тестирования без реальных данных используй **sandbox-токен** и адрес:

```
https://sandbox-invest-public-api.tbank.ru/rest
```

В sandbox доступны те же методы, но данные не влияют на реальный счёт.

> Если передать sandbox-токен на prod-контур — API вернёт ошибку.

---

## 14. Краткая памятка: порядок действий агента

1. **Принять токен** от пользователя (форма на сайте).
2. **Зашифровать и сохранить** токен в БД.
3. **Вызвать GetAccounts** → получить список открытых счетов.
4. **Для каждого счёта вызвать GetPortfolio** → получить позиции.
5. **Конвертировать MoneyValue и Quotation** в обычные числа.
6. **Обогатить позиции** через GetInstrumentBy (батчами по 5, с паузой).
7. **Сохранить результат** в таблицу portfolio_positions.
8. **Показать пользователю** на странице портфеля.
9. **Настроить периодическое обновление** (cron / webhook) — не чаще чем раз в 5 минут.
10. **Обрабатывать ошибку 40003** — просить пользователя обновить токен.

---

## 15. Полезные ссылки (для справки)

- Официальная документация: `https://developer.tbank.ru/invest/intro/intro`
- REST API explorer: `https://developer.tbank.ru/invest/api`
- Swagger UI: `https://russianinvestments.github.io/investAPI/swagger-ui/`
- JS SDK (официальный): `https://opensource.tbank.ru/invest/invest-js`
- Proto-контракты: `https://opensource.tbank.ru/invest/invest-contracts/-/tree/master/src/docs/contracts`
- Telegram-поддержка: `https://t.me/joinchat/VaW05CDzcSdsPULM`