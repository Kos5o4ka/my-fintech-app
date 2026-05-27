#!/bin/bash
# Деплой обновлений с GitHub через Docker Compose
# Использование: bash scripts/deploy.sh
set -euo pipefail

APP_DIR="/root/my_web_app"
cd "$APP_DIR"

echo "==> Бэкап БД перед деплоем..."
bash "$APP_DIR/scripts/backup_db.sh"

echo "==> Подтягиваю изменения с GitHub..."
git pull origin main

echo "==> Пересборка и запуск контейнеров в фоне..."
# Эта команда сама обновит зависимости (pip install) внутри контейнера
docker compose up -d --build

echo "==> Применяю миграции БД (внутри контейнера!)..."
# Запускаем flask db upgrade прямо внутри работающего контейнера app
docker compose exec app flask db upgrade

echo "==> Очистка старых образов Docker..."
docker image prune -f

echo ""
echo "✓ Деплой завершён. Статус контейнеров:"
docker compose ps