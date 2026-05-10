#!/usr/bin/env bash
# setup.sh — подготовка окружения для self-hosted развёртывания.
#
# Что делает:
#   1. Проверяет наличие Docker и docker compose.
#   2. Создаёт backend/.env из backend/.env.example (если .env ещё нет).
#   3. Генерирует JWT_SECRET_KEY (cryptographically secure, 64 байта).
#   4. Запрашивает POSTGRES_PASSWORD и BOOTSTRAP_ADMIN_EMAIL.
#   5. Создаёт симлинк .env → backend/.env в корне репозитория,
#      чтобы docker compose мог читать переменные при подстановке в YAML.
#   6. Печатает следующие шаги.
#
# Запуск: bash setup.sh
# Повторный запуск безопасен: уже заполненные значения не перезаписываются.

set -euo pipefail

# ── Цвета ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

# ── Зависимости ────────────────────────────────────────────────────────────
echo ""
echo "=== Support Demo — первоначальная настройка ==="
echo ""

if ! command -v docker &>/dev/null; then
    err "Docker не найден. Установите: https://docs.docker.com/get-docker/"
    exit 1
fi
ok "Docker: $(docker --version | cut -d' ' -f3 | tr -d ',')"

if ! docker compose version &>/dev/null; then
    err "docker compose (v2) не найден. Обновите Docker Desktop или установите плагин."
    exit 1
fi
ok "docker compose: $(docker compose version --short)"

# ── backend/.env ───────────────────────────────────────────────────────────
ENV_FILE="backend/.env"
ENV_EXAMPLE="backend/.env.example"

if [ ! -f "$ENV_EXAMPLE" ]; then
    err "Не найден $ENV_EXAMPLE. Запустите скрипт из корня репозитория."
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    ok "Создан $ENV_FILE из шаблона."
else
    warn "$ENV_FILE уже существует — пропускаем копирование."
fi

# ── JWT_SECRET_KEY ──────────────────────────────────────────────────────────
current_jwt=$(grep -E '^JWT_SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
if [ -z "$current_jwt" ]; then
    if command -v python3 &>/dev/null; then
        jwt_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
    elif command -v openssl &>/dev/null; then
        jwt_key=$(openssl rand -base64 48 | tr -d '\n')
    else
        err "Python3 и openssl не найдены. Вручную установите JWT_SECRET_KEY в $ENV_FILE."
        exit 1
    fi
    # Заменяем строку JWT_SECRET_KEY= на JWT_SECRET_KEY=<значение>
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$jwt_key|" "$ENV_FILE"
    else
        sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$jwt_key|" "$ENV_FILE"
    fi
    ok "JWT_SECRET_KEY сгенерирован (${#jwt_key} символов)."
else
    ok "JWT_SECRET_KEY уже задан — не меняем."
fi

# ── POSTGRES_PASSWORD ───────────────────────────────────────────────────────
current_pg=$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
if [ -z "$current_pg" ] || [ "$current_pg" = "postgres" ]; then
    echo ""
    warn "POSTGRES_PASSWORD сейчас: '${current_pg:-пусто}' — небезопасно для production."
    read -rsp "  Введите новый пароль БД (Enter — оставить как есть): " pg_pass
    echo ""
    if [ -n "$pg_pass" ]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$pg_pass|" "$ENV_FILE"
        else
            sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$pg_pass|" "$ENV_FILE"
        fi
        ok "POSTGRES_PASSWORD обновлён."
    else
        warn "POSTGRES_PASSWORD не изменён. Рекомендуется сменить перед production-запуском."
    fi
else
    ok "POSTGRES_PASSWORD уже задан — не меняем."
fi

# ── BOOTSTRAP_ADMIN_EMAIL ───────────────────────────────────────────────────
current_admin=$(grep -E '^BOOTSTRAP_ADMIN_EMAIL=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
if [ -z "$current_admin" ]; then
    echo ""
    echo "  BOOTSTRAP_ADMIN_EMAIL — email первого администратора."
    echo "  Зарегистрируйтесь с этим email → получите роль admin."
    echo "  После создания первого админа можно убрать из .env."
    read -rp "  Введите admin email (Enter — пропустить): " admin_email
    if [ -n "$admin_email" ]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|^BOOTSTRAP_ADMIN_EMAIL=.*|BOOTSTRAP_ADMIN_EMAIL=$admin_email|" "$ENV_FILE"
        else
            sed -i "s|^BOOTSTRAP_ADMIN_EMAIL=.*|BOOTSTRAP_ADMIN_EMAIL=$admin_email|" "$ENV_FILE"
        fi
        ok "BOOTSTRAP_ADMIN_EMAIL: $admin_email"
    else
        warn "BOOTSTRAP_ADMIN_EMAIL не задан. Задайте его в $ENV_FILE позже."
    fi
else
    ok "BOOTSTRAP_ADMIN_EMAIL уже задан: $current_admin"
fi

# ── CORS_ORIGINS ───────────────────────────────────────────────────────────
current_cors=$(grep -E '^CORS_ORIGINS=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
if [ -z "$current_cors" ]; then
    warn "CORS_ORIGINS пуст. Если фронт и бэк за одним nginx (этот compose) — оставьте пустым."
    warn "Если они на разных портах/доменах — добавьте: CORS_ORIGINS=https://ваш-домен.com"
fi

# ── Симлинк .env → backend/.env ─────────────────────────────────────────────
# docker compose читает .env в текущей директории для подстановки ${VAR} в YAML.
# Симлинк позволяет хранить всё в одном файле.
if [ ! -L ".env" ] && [ ! -f ".env" ]; then
    ln -s backend/.env .env
    ok "Создан .env → backend/.env (симлинк для docker compose)"
elif [ -L ".env" ]; then
    ok ".env симлинк уже существует."
else
    warn ".env уже существует как файл (не симлинк). Убедитесь, что он содержит нужные переменные."
fi

# ── Готово ──────────────────────────────────────────────────────────────────
echo ""
echo "=== Настройка завершена ==="
echo ""
echo "  Следующие шаги:"
echo ""
echo "  1. Убедитесь, что AI-сервис доступен:"
echo "     Замените 'support-demo/ai-service:prod' на реальный образ"
echo "     в docker-compose.yml, или закомментируйте ai-service (fallback на агентов)."
echo ""
echo "  2. Запустите стек:"
echo "     docker compose up -d --build"
echo ""
echo "  3. Откройте браузер: http://localhost"
echo "     Зарегистрируйтесь с email '$current_admin' — получите роль admin."
echo ""
echo "  4. (опционально) Заполните демо-агентов:"
echo "     docker compose exec app python scripts/seed_demo_agents.py"
echo ""
echo "  Бэкап БД:"
echo "     bash scripts/backup_db.sh"
echo ""
