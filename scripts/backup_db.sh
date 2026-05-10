#!/usr/bin/env bash
# backup_db.sh — создаёт сжатый дамп PostgreSQL из работающего compose-стека.
#
# Использование:
#   bash scripts/backup_db.sh               # сохраняет в ./backups/
#   bash scripts/backup_db.sh /mnt/nas      # сохраняет в /mnt/nas/
#
# Запускайте из корня репозитория (там, где docker-compose.yml).
# Для автоматического резервного копирования добавьте в crontab хоста:
#   0 3 * * * cd /opt/support-demo && bash scripts/backup_db.sh >> /var/log/support-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${1:-./backups}"
mkdir -p "$BACKUP_DIR"

# ── Читаем настройки БД из backend/.env ────────────────────────────────────
ENV_FILE="backend/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "Ошибка: $ENV_FILE не найден. Запустите из корня репозитория." >&2
    exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

PG_USER="${POSTGRES_USER:-postgres}"
PG_DB="${POSTGRES_DB:-app_db}"

# ── Проверяем, что compose-стек запущен ────────────────────────────────────
if ! docker compose ps db --format json 2>/dev/null | grep -q '"State":"running"'; then
    echo "Ошибка: контейнер db не запущен. Поднимите стек: docker compose up -d" >&2
    exit 1
fi

# ── Создаём дамп ───────────────────────────────────────────────────────────
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="$BACKUP_DIR/support_demo_${TIMESTAMP}.sql.gz"

echo "Создаю дамп базы '${PG_DB}' (пользователь: ${PG_USER})..."

docker compose exec -T db \
    pg_dump -U "$PG_USER" "$PG_DB" \
    | gzip > "$FILENAME"

SIZE=$(du -sh "$FILENAME" | cut -f1)
echo "Готово: $FILENAME ($SIZE)"

# ── Ротация: оставляем последние 30 дампов ─────────────────────────────────
KEEP=30
COUNT=$(find "$BACKUP_DIR" -name 'support_demo_*.sql.gz' | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
    TO_DELETE=$(( COUNT - KEEP ))
    echo "Удаляю $TO_DELETE устаревших дампов (оставляю последние $KEEP)..."
    find "$BACKUP_DIR" -name 'support_demo_*.sql.gz' \
        | sort | head -n "$TO_DELETE" \
        | xargs rm -f
fi
