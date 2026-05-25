#!/bin/bash
# Деплой обновлений с GitHub. Запускать после git pull или вместо него.
# Использование: bash scripts/deploy.sh
set -euo pipefail

APP_DIR="/root/my_web_app"
SERVICE="myapp.service"
VENV="$APP_DIR/.venv"

cd "$APP_DIR"

echo "==> Бэкап БД перед деплоем..."
bash "$APP_DIR/scripts/backup_db.sh"

echo "==> Подтягиваю изменения с GitHub..."
git pull origin main

echo "==> Устанавливаю зависимости (если изменились)..."
"$VENV/bin/pip" install -r requirements.txt -q

echo "==> Применяю миграции БД..."
FLASK_APP=app.py "$VENV/bin/flask" db upgrade

echo "==> Перезапускаю воркеры gunicorn (graceful)..."
systemctl reload "$SERVICE"

echo ""
echo "✓ Деплой завершён. Статус сервиса:"
systemctl status "$SERVICE" --no-pager -l | head -10
