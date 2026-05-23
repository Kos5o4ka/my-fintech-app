# Архитектурный Roadmap по оптимизации и устранению багов (InvestTrack)

**Для:** Ведущего разработчика (Lead Developer)  
**Ветка изменений:** `feature/architecture-optimization`  
**Дата:** 2026-05-23  

---

## 🛠 Введение
Данный документ представляет собой детальный технический аудит кодовой базы InvestTrack. В ходе анализа были выявлены критические логические ошибки (включая финансовые неточности в налоговых отчетах), уязвимости безопасности (риск brute-force OTP-кодов 2FA и спуфинга вебхуков Telegram), а также архитектурные узкие места, которые могут привести к падению производительности и блокировкам со стороны Московской Биржи (MOEX ISS API).

Ниже приведен детальный пошаговый план (Roadmap) по исправлению багов и рефакторингу архитектуры для повышения стабильности, безопасности и масштабируемости системы.

---

## 📍 КРАТКИЙ СПИСОК НАЙДЕННЫХ ПРОБЛЕМ

| Класс проблемы | Описание | Затронутые модули | Критичность |
| :--- | :--- | :--- | :--- |
| 🔴 **Финансовый баг** | Упущен купонный доход по проданным в течение года бумагам в налоговом отчете | `services/portfolio_service.py` (`calc_tax_report`) | **Высокая** |
| 🔴 **Уязвимость (2FA)** | Отсутствие инвалидации OTP при неудачной попытке входа (риск brute-force) | `services/telegram_service.py` (`verify_otp`) | **Высокая** |
| 🔴 **Уязвимость (Бот)** | Отсутствие проверки подлинности входящих запросов на вебхук Telegram | `blueprints/telegram_bot.py` (`webhook`) | **Высокая** |
| 🟡 **Архитектурный сбой** | Дублирование фонового шедулера APScheduler в каждом воркере Gunicorn (дубли писем/запросов) | `app.py` | **Высокая** |
| 🟡 **N+1 HTTP-запросы** | Отсутствие кэширования купонных календарей (N медленных запросов к MOEX ISS по кругу) | `blueprints/portfolio.py`, `services/moex_service.py` | **Высокая** |
| 🟢 **Логическая ошибка** | Искажение средневзвешенного YTM портфеля при наличии бумаг без YTM | `services/portfolio_service.py` (`calc_portfolio_ytm`) | **Средняя** |
| 🟢 **Сплит-брейн CB** | Локальное хранение состояния Circuit Breaker в памяти воркера вместо Redis | `moex.py` | **Средняя** |
| 🟢 **Баг Скринера** | Стратегия "Limit before Filter" в скринере обрезает подходящие облигации | `moex.py` (`get_screener_bonds`) | **Средняя** |
| 🟢 **N+1 Cache-запросы**| Последовательные GET кэша в цикле отрисовки портфеля | `services/portfolio_service.py` (`build_portfolio_entry`) | **Низкая** |

---

## 📋 ДЕТАЛЬНЫЙ ROADMAP И ИНСТРУКЦИИ ПО ИСПРАВЛЕНИЮ

---

### ЭТАП 1. ИСПРАВЛЕНИЕ КРИТИЧЕСКИХ БАГОВ И УЯЗВИМОСТЕЙ (БЕЗОПАСНОСТЬ И ФИНАНСЫ)

#### 1.1. Исправление финансовой логики в Налоговом Отчете
*   **Где исправлять:** `services/portfolio_service.py` -> функция [calc_tax_report](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/services/portfolio_service.py#L118)
*   **Проблема:** В расчете `coupon_income` за отчетный год учитываются только бумаги, находящиеся в списке `active_bonds` (активные на данный момент). Если пользователь владел облигацией, получал по ней купоны в течение года, а затем продал ее, эта облигация переходит в архив (`sold_bonds`). В результате купонный доход по ней полностью выпадает из расчета НДФЛ, занижая налоговую базу.
*   **Решение:**
    Купонный доход должен рассчитываться по всем бумагам, которыми пользователь владел в течение отчетного года (и активным, и проданным).
*   **Инструкция по изменению кода:**
    ```python
    # Было:
    for bond in active_bonds:
        target = bond.secid or bond.isin
        # ... fetch coupons ...

    # Стало:
    # Объединяем списки активных и проданных облигаций для сканирования календаря купонов
    all_bonds = list(active_bonds) + list(sold_bonds)
    # Исключаем дубликаты по id на случай непредвиденных пересечений
    seen_ids = set()
    unique_bonds = []
    for b in all_bonds:
        if b.id not in seen_ids:
            seen_ids.add(b.id)
            unique_bonds.append(b)

    for bond in unique_bonds:
        target = bond.secid or bond.isin
        # ... далее стандартный цикл фильтрации по датам выплат ...
    ```

#### 1.2. Защита OTP 2FA от brute-force атак
*   **Где исправлять:** `services/telegram_service.py` -> функция [verify_otp](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/services/telegram_service.py#L59)
*   **Проблема:** Метод `verify_otp` удаляет временный OTP-код из кэша (`cache.delete`) только в случае *успешного* совпадения (`if is_valid:`). Если злоумышленник пытается подобрать 6-значный цифровой код (всего 1 млн комбинаций), он может отправлять сотни запросов в секунду. Так как код не сгорает при ошибке ввода, распределенная brute-force атака (в обход лимитера по IP) легко подберет код за 5 минут жизни токена.
*   **Решение:**
    Сделайте OTP-код строго одноразовым! Код должен удаляться из кэша **незамедлительно при первой же попытке проверки**, независимо от того, верный он или нет.
*   **Инструкция по изменению кода:**
    ```python
    # Было:
    def verify_otp(chat_id: str, code: str) -> bool:
        stored = cache.get(f"tg_otp:{chat_id}")
        if stored is None:
            return False
        is_valid = secrets.compare_digest(str(stored), str(code).strip())
        if is_valid:
            cache.delete(f"tg_otp:{chat_id}")
        return is_valid

    # Стало:
    def verify_otp(chat_id: str, code: str) -> bool:
        stored = cache.get(f"tg_otp:{chat_id}")
        if stored is None:
            return False
        # Удаляем код СРАЗУ же после считывания (сгорает при любой попытке)
        cache.delete(f"tg_otp:{chat_id}")
        return secrets.compare_digest(str(stored), str(code).strip())
    ```

#### 1.3. Защита Вебхука Telegram от спуфинга
*   **Где исправлять:** `blueprints/telegram_bot.py` -> эндпоинт [webhook](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/blueprints/telegram_bot.py#L15)
*   **Проблема:** Эндпоинт `/api/telegram/webhook` является публичным и не имеет авторизации. Любой сторонний клиент может отправлять поддельные HTTP POST запросы, эмулируя сообщения от Telegram (например, привязывая чужие chat_id, перехватывая сессии 2FA или генерируя ложные команды).
*   **Решение:**
    1.  Использовать секретный токен в URL вебхука, известный только Telegram и вашему серверу (рекомендованный подход Telegram).
    2.  Добавить заголовок `X-Telegram-Bot-Api-Secret-Token` при регистрации вебхука и сверять его на бэкенде.
*   **Инструкция по изменению кода:**
    Задайте переменную окружения `TELEGRAM_WEBHOOK_SECRET` в конфигурации. Перепишите роут вебхука следующим образом:
    ```python
    # В config.py добавить:
    # TELEGRAM_WEBHOOK_SECRET = os.environ.get('TELEGRAM_WEBHOOK_SECRET')

    # В blueprints/telegram_bot.py:
    @telegram_bp.route("/api/telegram/webhook/<secret>", methods=["POST"])
    def webhook(secret):
        expected_secret = current_app.config.get("TELEGRAM_WEBHOOK_SECRET")
        if not expected_secret or secret != expected_secret:
            abort(403) # Отклоняем запросы с неверным секретом
        
        # Альтернативно/дополнительно проверяем заголовок:
        # if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != expected_secret:
        #     abort(403)
        
        # ... продолжение обработки сообщения ...
    ```

---

### ЭТАП 2. ОПТИМИЗАЦИЯ СТАБИЛЬНОСТИ И ПРОИЗВОДИТЕЛЬНОСТИ (АРХИТЕКТУРА)

#### 2.1. Изоляция фонового планировщика (APScheduler) в Multi-Worker среде
*   **Где исправлять:** `app.py` -> [APScheduler блок инициализации](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/app.py#L326)
*   **Проблема:** Инициализация `BackgroundScheduler()` происходит прямо внутри процесса Flask. При запуске приложения на сервере через Gunicorn с несколькими воркерами (например, `--workers=4`), код `app.py` импортируется и запускается в 4 изолированных процессах. 
    Это приводит к тому, что **одновременно работают 4 шедулера**. Они:
    1.  Делают в 4 раза больше тяжелых запросов к MOEX ISS API в фоне.
    2.  В 9:00 отправляют пользователю **4 одинаковых дублирующихся email-письма** и **4 сообщения в Telegram** о купонах.
    3.  Вызывают блокировки строк в PostgreSQL при одновременных `bulk_update_mappings`.
*   **Решение:**
    *   **Для Production (Рекомендуется):** Вынесите APScheduler в отдельный изолированный Docker-контейнер/процесс (например, `celery beat` + `celery worker` или отдельный Python-скрипт `run_scheduler.py`, запускаемый в одном экземпляре).
    *   **Быстрое решение на базе блокировок (File Lock):** Использовать системную блокировку файла (библиотека `trollius` / `portalocker` или встроенный в Linux `flock`), чтобы шедулер запускался только в первом инициализированном воркере Gunicorn.
*   **Архитектурный пример `run_scheduler.py` (выделенный процесс):**
    Создать файл [run_scheduler.py](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/run_scheduler.py):
    ```python
    import os
    import time
    from app import app, _update_bond_prices, _send_coupon_reminders
    from apscheduler.schedulers.blocking import BlockingScheduler

    if __name__ == "__main__":
        # Запуск планировщика в единственном экземпляре в отдельном контейнере
        scheduler = BlockingScheduler()
        scheduler.add_job(
            _update_bond_prices,
            "interval",
            minutes=15,
            id="price_update"
        )
        scheduler.add_job(
            _send_coupon_reminders,
            "cron",
            hour=9,
            minute=0,
            id="coupon_reminders"
        )
        print("Dedicated APScheduler process started successfully.")
        scheduler.start()
    ```
    В `app.py` полностью убрать автозапуск шедулера при инициализации веб-сервера.

#### 2.2. Устранение N+1 HTTP-запросов к MOEX (Кэширование Календаря Купонов)
*   **Где исправлять:** `blueprints/portfolio.py` (роуты `/api/portfolio/calendar` и `/api/portfolio/income`) + `services/moex_service.py`
*   **Проблема:** В функциях [get_portfolio_calendar](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/blueprints/portfolio.py#L375) и [calc_coupon_income](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/services/portfolio_service.py#L80) вызывается сырой метод `get_coupon_calendar(isin)` напрямую из `moex.py`. Данный метод делает синхронный HTTP-запрос к внешнему API Московской Биржи. Если у пользователя в портфеле 20 бумаг, загрузка дашборда вызовет 20 последовательных сетевых запросов! Это приводит к Timeouts (504 Gateway Timeout), исчерпанию пула потоков Gunicorn и банам со стороны MOEX.
*   **Решение:**
    1.  Реализовать кэширование купонного календаря на уровне `services/moex_service.py`. Так как даты выплат по купонам меняются крайне редко (раз в несколько месяцев при объявлении новых выпусков), кэш можно ставить на **12-24 часа**.
    2.  Заменить импорт в `blueprints/portfolio.py` и `services/portfolio_service.py` на кэшированную версию.
*   **Инструкция по изменению кода:**
    Добавить в `services/moex_service.py`:
    ```python
    def get_coupon_calendar_cached(secid: str) -> list[dict]:
        """Возвращает купонный календарь с кэшем на 12 часов."""
        key = f"moex_coupons:{secid}"
        result = cache.get(key)
        if result is None:
            from moex import get_coupon_calendar
            result = get_coupon_calendar(secid)
            if result:
                try:
                    cache.set(key, result, timeout=43200) # 12 часов
                except Exception:
                    pass
        return result or []
    ```
    Заменить все вызовы `get_coupon_calendar` на `get_coupon_calendar_cached`.

#### 2.3. Сплит-брейн Circuit Breaker в Gunicorn
*   **Где исправлять:** `moex.py` -> [Circuit Breaker переменные](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/moex.py#L25)
*   **Проблема:** Состояние предохранителя (`_cb_fail_count`, `_cb_open_until`) сохраняется в глобальных переменных модуля `moex.py`. В многопроцессном Gunicorn у каждого воркера своя копия этих переменных в ОЗУ. Если MOEX "упадет", воркер №1 совершит 5 ошибок и закроет доступ на 10 минут. Воркер №2 ничего об этом не узнает и продолжит бомбардировать упавший MOEX новыми запросами, усугубляя ситуацию.
*   **Решение:**
    Хранить состояние Circuit Breaker в едином распределенном кэше (Redis), который является общим для всех воркеров.
*   **Инструкция по изменению кода:**
    ```python
    # В moex.py переписать функции проверки предохранителя:
    def _circuit_check() -> None:
        from extensions import cache
        open_until = cache.get("moex_cb:open_until") or 0.0
        if time.time() < open_until:
            remaining = int(open_until - time.time())
            raise RuntimeError(f"MOEX недоступен (CB OPEN), повтор через {remaining} с.")

    def _circuit_success() -> None:
        from extensions import cache
        cache.set("moex_cb:fail_count", 0, timeout=86400)

    def _circuit_failure() -> None:
        from extensions import cache
        from constants import MOEX_CIRCUIT_FAIL_THRESHOLD, MOEX_CIRCUIT_OPEN_SECONDS
        
        fail_count = (cache.get("moex_cb:fail_count") or 0) + 1
        cache.set("moex_cb:fail_count", fail_count, timeout=3600)
        
        if fail_count >= MOEX_CIRCUIT_FAIL_THRESHOLD:
            open_until = time.time() + MOEX_CIRCUIT_OPEN_SECONDS
            cache.set("moex_cb:open_until", open_until, timeout=MOEX_CIRCUIT_OPEN_SECONDS)
            cache.set("moex_cb:fail_count", 0, timeout=86400)
            logger.warning("MOEX CB OPEN — лимит ошибок превышен. Пауза %d с.", MOEX_CIRCUIT_OPEN_SECONDS)
    ```

---

### ЭТАП 3. ИСПРАВЛЕНИЕ ЛОГИЧЕСКИХ И МАТЕМАТИЧЕСКИХ ОШИБОК

#### 3.1. Корректировка средневзвешенного YTM портфеля
*   **Где исправлять:** `services/portfolio_service.py` -> функция [calc_portfolio_ytm](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/services/portfolio_service.py#L52)
*   **Проблема:** В текущей формуле:
    ```python
    ytm_weight_sum = sum(b["ytm"] * b["current_value"] for b in portfolio_list if b["ytm"])
    return round(ytm_weight_sum / total_value, 2)
    ```
    Сумма весов YTM делится на **общую стоимость всего портфеля** (`total_value`). Если в портфеле есть бумага, по которой MOEX не отдал дюрацию/доходность (`ytm` равен `None` или `0.0`), ее стоимость все равно прибавляется к знаменателю `total_value`. Это математически некорректно и сильно занижает итоговый YTM портфеля.
*   **Решение:**
    Делить сумму взвешенных доходностей только на суммарную стоимость тех позиций, у которых **есть валидный YTM**.
*   **Инструкция по изменению кода:**
    ```python
    def calc_portfolio_ytm(portfolio_list: list[dict], total_value: float) -> float:
        """Средневзвешенная YTM портфеля (веса только по бумагам с валидным YTM)."""
        valid_bonds = [b for b in portfolio_list if b.get("ytm")]
        if not valid_bonds:
            return 0.0
        
        ytm_weight_sum = sum(b["ytm"] * b["current_value"] for b in valid_bonds)
        total_valid_value = sum(b["current_value"] for b in valid_bonds)
        
        return round(ytm_weight_sum / total_valid_value, 2) if total_valid_value else 0.0
    ```

#### 3.2. Баг Скринера: Стратегия "Limit before Filter"
*   **Где исправлять:** `moex.py` -> функция [get_screener_bonds](file:///c:/Users/Kos5o4ka/PycharmProjects/my-fintech-app/moex.py#L250)
*   **Проблема:** Запрос к MOEX ISS API выполняется с жестким лимитом `limit={limit}` (по умолчанию 100-200 бумаг). Затем к этому ограниченному списку локально применяются фильтры по `min_ytm`, `max_ytm`, `maturity_from` и `maturity_to`. В результате, если подходящие пользователю бумаги находятся дальше первой сотни в выдаче MOEX, скринер вернет **пустой результат**, пропустив нужные облигации.
*   **Решение:**
    Передать базовые числовые фильтры на сторону API Московской Биржи (серверная фильтрация параметров), либо существенно увеличить размер сканируемого пакета данных (например, до 1000 бумаг) или реализовать пагинацию при сканировании списка в фоновом режиме.

---

## 📈 ПЛАН ТЕСТИРОВАНИЯ И ВЕРИФИКАЦИИ

После применения исправлений необходимо выполнить верификацию по следующему чек-листу:

1.  **Локальный запуск тестов:**
    Обязательно установите правильную переменную окружения перед тестированием:
    ```powershell
    $env:FLASK_ENV="testing"
    python -m pytest
    ```
    *Ожидаемый результат: Все 53 теста (включая property-based Hypothesis) должны проходить успешно.*

2.  **Проверка 2FA безопасности:**
    *   Попробуйте войти в аккаунт с привязанным Telegram.
    *   Введите неверный код OTP.
    *   Сразу же введите верный код.
    *   *Ожидаемый результат: Вход должен быть заблокирован (ошибка 401), так как при первой же попытке код сгорел. Пользователь должен инициировать генерацию нового OTP.*

3.  **Проверка налогового отчета:**
    *   Добавьте облигацию, дождитесь наступления купонной даты в тесте или смоделируйте выплату купонов в базе данных.
    *   Продайте облигацию (переведите в архив).
    *   Запустите генерацию налогового отчета за текущий год.
    *   *Ожидаемый результат: Купонный доход по проданной облигации отображается в строке "Купонный доход" и корректно облагается НДФЛ 13%.*

4.  **Проверка дублирования шедулера:**
    *   Запустить приложение через Gunicorn: `gunicorn -w 4 app:app`.
    *   Проверить логи приложения.
    *   *Ожидаемый результат: Лог инициализации APScheduler должен появиться ровно 1 раз (если шедулер вынесен в run_scheduler.py) вместо 4 раз в стандартном выводе воркеров.*

---

*Документ подготовлен для команды разработки InvestTrack. Все исправления рекомендуется делать точечными коммитами в созданной ветке `feature/architecture-optimization`.*
