# My Fintech App

## Улучшения

Этот проект обновлён согласно плану UX/доступности/производительности.

- Серверный `range=day|week|month|all` и downsampling для `/api/bond_chart/<isin>`
- CSRF-защита для POST/DELETE запросов через `Flask-WTF` и `XSRF-TOKEN`
- Валидация загрузок аватаров: расширения, MIME и содержимое изображения
- TTL-кэш для MOEX-интеграции, таймауты и устойчивый fallback
- Отдельные JS-модули: `static/js/common.js`, `static/js/index.js`, `static/js/portfolio.js`
- ARIA-метки, `alt`, `aria-label` и фокус для модальных диалогов
- Оптимизация загрузки: `defer`, `preconnect`, lazy loading аватаров
- Тёмная тема с CSS-переменными и сохранением выбора в localStorage
- Smoke-тесты для основных страниц и конфигурации

## Как запускать

1. Создайте виртуальное окружение и установите зависимости:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

2. Запустите приложение:

```bash
flask run
```

3. Сгенерируйте минифицированные ассеты:

```bash
python build_assets.py
```

4. Проверьте smoke-тесты:

```bash
python -m unittest discover tests
```

## Обратите внимание

- Максимальный размер загружаемого аватара: `5 MB`
- Разрешённые форматы: `png`, `jpg`, `jpeg`, `gif`, `webp`
- Тема сохраняется в `localStorage` и восстанавливается при следующем заходе
