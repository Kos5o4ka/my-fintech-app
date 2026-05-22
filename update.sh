#!/bin/bash
set -e

cd /root/my_web_app

echo ">>> Подтягиваем изменения из GitHub..."
git pull origin main

echo ">>> Устанавливаем зависимости..."
.venv/bin/pip install -r requirements.txt -q

echo ">>> Применяем миграции..."
.venv/bin/flask db upgrade

echo ">>> Перезапускаем сервис..."
systemctl restart myapp.service

echo ""
echo "✓ Сайт обновлён!"
