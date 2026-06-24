#!/usr/bin/env bash
set -euo pipefail

# ─── Цвета ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ─── Параметры ────────────────────────────────────────────────────────────────
APP_DIR="/opt/oko"
SERVICE_NAME="oko-bot"
REPO_URL="${REPO_URL:-https://github.com/ZipZipa/oko.git}"
BRANCH="${BRANCH:-main}"
SERVICE_SRC="$APP_DIR/deploy/oko-bot.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"

# ─── Проверка root ────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Запустите скрипт от root: sudo bash setup.sh"

# ─── 1. Системные зависимости ─────────────────────────────────────────────────
info "Обновление пакетов и установка зависимостей..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    git curl wget \
    libgl1 libglib2.0-0 \
    build-essential

# ─── 2. Клонирование / обновление репозитория ─────────────────────────────────
if [[ -d "$APP_DIR/.git" ]]; then
    info "Репозиторий уже существует — обновляю..."
    git -C "$APP_DIR" fetch origin
    git -C "$APP_DIR" reset --hard "origin/$BRANCH"
else
    info "Клонирование репозитория в $APP_DIR..."
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

# ─── 3. Виртуальное окружение Python ─────────────────────────────────────────
if [[ ! -d "$APP_DIR/venv" ]]; then
    info "Создание виртуального окружения..."
    python3 -m venv "$APP_DIR/venv"
else
    info "Виртуальное окружение уже существует — пропускаю создание."
fi

info "Установка/обновление Python-зависимостей (может занять несколько минут)..."
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ─── 4. Файл окружения .env ───────────────────────────────────────────────────
if [[ ! -f "$APP_DIR/.env" ]]; then
    info "Создание .env из .env.example..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    warn "Заполните переменные в $APP_DIR/.env перед запуском бота:"
    warn "  BOT_TOKEN, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, BOT_USERNAME, ADMIN_IDS"
    echo ""
    read -r -p "Нажмите Enter, чтобы открыть .env в nano (или Ctrl+C для пропуска)..." _
    nano "$APP_DIR/.env" || true
else
    info ".env уже существует — пропускаю."
fi

# ─── 5. Установка systemd-сервиса ─────────────────────────────────────────────
UNIT_CHANGED=false
if [[ ! -f "$SERVICE_DST" ]]; then
    info "Установка systemd unit файла (новый)..."
    cp "$SERVICE_SRC" "$SERVICE_DST"
    UNIT_CHANGED=true
elif ! diff -q "$SERVICE_SRC" "$SERVICE_DST" > /dev/null 2>&1; then
    info "systemd unit файл изменился — обновляю..."
    cp "$SERVICE_SRC" "$SERVICE_DST"
    UNIT_CHANGED=true
else
    info "systemd unit файл не изменился — пропускаю."
fi

if [[ "$UNIT_CHANGED" == true ]]; then
    systemctl daemon-reload
fi

systemctl enable "$SERVICE_NAME" --quiet

# ─── 6. Запуск сервиса ────────────────────────────────────────────────────────
# Проверяем, задан ли BOT_TOKEN
if grep -qE '^BOT_TOKEN=\s*$' "$APP_DIR/.env" 2>/dev/null || ! grep -q '^BOT_TOKEN=' "$APP_DIR/.env" 2>/dev/null; then
    warn "BOT_TOKEN не задан в .env — сервис не запущен."
    warn "Заполните $APP_DIR/.env и выполните: systemctl start $SERVICE_NAME"
else
    if [[ "$UNIT_CHANGED" == true ]]; then
        info "Unit изменился — перезапускаю сервис..."
        systemctl restart "$SERVICE_NAME"
    elif systemctl is-active --quiet "$SERVICE_NAME"; then
        info "Сервис уже запущен и unit не менялся — пропускаю перезапуск."
    else
        info "Сервис не запущен — запускаю..."
        systemctl start "$SERVICE_NAME"
    fi
    sleep 2
    systemctl status "$SERVICE_NAME" --no-pager
fi

# ─── Готово ───────────────────────────────────────────────────────────────────
echo ""
info "Готово!"
echo -e "  Логи:    ${YELLOW}journalctl -u $SERVICE_NAME -f${NC}"
echo -e "  Статус:  ${YELLOW}systemctl status $SERVICE_NAME${NC}"
echo -e "  Стоп:    ${YELLOW}systemctl stop $SERVICE_NAME${NC}"
echo -e "  Рестарт: ${YELLOW}systemctl restart $SERVICE_NAME${NC}"
