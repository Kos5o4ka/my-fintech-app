# Приоритеты разработки

Функциональные задачи в порядке приоритета. Тесты и документация — в конце, после выхода в прод.

---

## 🔴 Блок 1 — Быстрые wins (делаются за 1-3 часа каждая)

1. ~~**Debounce 300ms для поиска облигаций**~~ — уже был реализован (`portfolio.js:354`)

2. ~~**Таймаут на все `requests.get()` в `moex.py`**~~ — `_TIMEOUT = 10`, единая константа, `_fetch_json()` хелпер

3. ~~**Предупреждение при добавлении дублирующегося ISIN**~~ — backend возвращает `duplicate_warning`, жёлтый тост

4. ~~**Retry с exponential backoff для MOEX API**~~ — `tenacity` 3 попытки, backoff 1/2/4 сек, авто-логирование ретраев

5. ~~**Заменить `print()` на `logging`**~~ в `moex.py` — `logger.error()` / `logger.warning()`

> Бонус: обновлён `Flask-WTF 1.1.1 → 1.3.0` (совместимость с Flask 3.x). Все 36 тестов проходят.

---

## 🟠 Блок 2 — UX форм и таблиц (делаются за день каждая)

6. ~~**Live-preview облигации при вводе ISIN**~~ — карточка с названием, ценой, YTM, погашением, купоном, НКД; появляется при выборе из дропдауна или blur на поле длиной ≥10 символов

7. ~~**Автозаполнение `buy_price` текущей ценой**~~ — реализовано в рамках preview; повторная правка поля сбрасывает автозаполнение

8. ~~**Skeleton screens при загрузке таблицы**~~ — анимированные skeleton-ячейки пока идёт запрос (активный портфель и история)

9. ~~**Empty state при пустом портфеле**~~ — иконка + текст "Портфель пуст" с подсказкой

10. ~~**Фильтрация истории торгов по дате**~~ — date picker from/to над таблицей; бэкенд фильтрует по `sell_date`; кнопка "Сбросить"

> Бонус: `get_bond_details()` в `moex.py`; `add_bond` переведён на `_fetch_json` (retry + timeout вместо голого requests)

---

## 🟡 Блок 3 — Аналитика (ключевые виджеты)

11. ~~**Средневзвешенный YTM по всему портфелю**~~ — взвешен по стоимости позиции, отображается в карточке портфеля рядом с количеством позиций

12. ~~**Виджет купонного дохода**~~ — `GET /api/portfolio/income` суммирует купоны за 30/90/365 дней; переключатель в карточке; кэш 15 мин

13. ~~**Круговая диаграмма распределения**~~ — Chart.js Doughnut рядом с графиком прибыли; рендерится на фронте из `bondsData` без лишнего запроса

14. ~~**Комиссия брокера при продаже**~~ — поле `broker_commission` в модели; sell modal с ценой + комиссией; P&L в истории учитывает комиссию; lightweight ALTER TABLE в `init_db.py`

---

## 🟢 Блок 4 — Новые страницы и разделы

15. **Страница `/dashboard`** — главный экран после логина:
    - Общая стоимость портфеля
    - P&L за всё время
    - Средневзвешенный YTM
    - Ближайшие 5 купонов
    - Лучшая и худшая позиция  
    `blueprints/main.py` → новый роут  
    `templates/dashboard.html` (новый шаблон)

16. **Navbar с навигацией** — Dashboard / Portfolio / Profile / Admin  
    Вынести в `templates/base.html` (сейчас нет базового шаблона)  
    Рефакторинг всех шаблонов под `{% extends "base.html" %}`

17. **Admin-панель как отдельная страница `/admin`**  
    `blueprints/admin.py` → добавить роут  
    `templates/admin.html` (новый шаблон)

18. **Мобильная адаптация таблиц** — card view на экранах < 768px  
    `static/css/portfolio.css` + медиа-запросы

---

## 🔵 Блок 5 — Новые функции

19. ~~**Watchlist** — облигации "в избранном" без добавления в портфель~~  
    `models.py` → `Watchlist` модель; `blueprints/portfolio.py` → CRUD (GET/POST/DELETE);  
    `templates/portfolio.html` → вкладка ⭐ Избранное; `portfolio.js` → fetch + render

20. ~~**Скринер облигаций** — поиск с фильтрами (YTM, срок погашения)~~  
    `moex.py` → `get_screener_bonds()`; `blueprints/portfolio.py` → `GET /api/screener`;  
    `templates/portfolio.html` → вкладка 🔍 Скринер с фильтрами; ⭐ в watchlist из скринера

21. ~~**Email-уведомления о купонах** — за 1 день до выплаты~~  
    `requirements.txt` → `flask-mail`; `models.py` → `email`, `email_notifications` в User;  
    `blueprints/profile.py` → `POST /api/profile/email`; APScheduler → `_send_coupon_reminders()` (cron 9:00);  
    `templates/profile.html` → карточка с email + checkbox

22. ~~**Экспорт в Excel `.xlsx`** — с форматированием~~  
    `requirements.txt` → `openpyxl`; `blueprints/portfolio.py` → `GET /api/portfolio/export/xlsx`;  
    `templates/portfolio.html` → кнопка 📊 Excel в navbar

23. ~~**Модель `Transaction`** — история всех покупок/продаж~~  
    `models.py` → `Transaction` (user_id, isin, tx_type, amount, price, commission, tx_date);  
    `blueprints/portfolio.py` → логируется при `add_bond` и `sell_bond`

24. ~~**Налоговый отчёт** — расчёт НДФЛ 13% с купонов и прибыли~~  
    `blueprints/portfolio.py` → `GET /api/portfolio/tax?year=`

25. ~~**Бенчмарк портфель vs RGBI** — история индекса~~  
    `moex.py` → `get_rgbi_history()`; `blueprints/portfolio.py` → `GET /api/portfolio/benchmark`

---

## ⚙️ Блок 6 — Инфраструктура (не тесты)

26. ~~**Alembic-миграции**~~ — `flask db init` + `flask db migrate -m "initial schema"`;  
    `scripts/init_db.py` теперь вызывает `flask_migrate.upgrade()` вместо `db.create_all()`

27. ~~**Разделить `config.py`**~~ — `DevelopmentConfig` / `TestingConfig` / `ProductionConfig`;  
    `ProductionConfig.validate()` падает если `SECRET_KEY` не задан;  
    `get_config()` выбирает класс по `FLASK_ENV`

28. ~~**Redis для кэша**~~ — `redis==5.2.1` в requirements; `app.py` использует `RedisCache`  
    если задан `REDIS_URL`, иначе `SimpleCache` (обратная совместимость)

29. ~~**Dockerfile + docker-compose**~~ — multi-stage `Dockerfile` (builder + runtime);  
    `docker-compose.yml`: web + postgres:16 + redis:7, healthchecks, named volumes;  
    `.dockerignore` для минимального образа

30. ~~**Healthcheck endpoint `GET /health`**~~ — проверяет DB (`SELECT 1`), cache (set/get),  
    MOEX connectivity; возвращает `{"status": "ok"|"degraded", "db":…, "cache":…, "moex":…}`

---

## ⏸️ Отложено (не приоритет сейчас)

- Тесты, покрытие, CI/CD — после стабилизации функционала
- 2FA / TOTP
- Email-подтверждение при смене пароля
- HaveIBeenPwned проверка паролей
- Logout со всех устройств
- Публичный REST API + JWT
- OpenAPI / Swagger документация
- Webhook-уведомления

---

## Порядок работы

```
Блок 1 (быстрые wins) → Блок 2 (UX) → Блок 3 (аналитика)
→ Блок 4 (новые страницы) → Блок 5 (функции) → Блок 6 (инфра)
```

Каждый пункт в блоках 1-3 независим — можно брать в любом порядке.
