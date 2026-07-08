#!/usr/bin/env bash
set -euo pipefail

# ─── Цвета ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ─── Константы ────────────────────────────────────────────────────────────────
APP_DIR="/opt/oko"

# ─── Справка ──────────────────────────────────────────────────────────────────
usage() {
    cat <<EOF
${CYAN}Oko Bot — Deploy Instance${NC}

Создаёт дополнительный инстанс бота с отдельной конфигурацией (.env) и БД.
Кодовая база и venv — общие с основным инстансом (${APP_DIR}).

${CYAN}Использование:${NC}
  sudo bash deploy/deploy-instance.sh <instance_name>

${CYAN}Параметры:${NC}
  instance_name   Имя инстанса (например: test, staging, prod2)

${CYAN}Примеры:${NC}
  sudo bash deploy/deploy-instance.sh test
  sudo bash deploy/deploy-instance.sh staging

${CYAN}Что происходит:${NC}
  1. Создаётся ${APP_DIR}/.env-<instance> с отдельной DATABASE_URL и BOT_TOKEN
  2. Создаётся systemd-сервис oko-bot-<instance>
  3. Сервис запускается

${CYAN}Управление инстансом:${NC}
  journalctl -u oko-bot-<instance> -f     # логи
  systemctl status oko-bot-<instance>      # статус
  systemctl stop oko-bot-<instance>        # стоп
  systemctl restart oko-bot-<instance>     # рестарт

${CYAN}Удаление инстанса:${NC}
  systemctl stop oko-bot-<instance>
  systemctl disable oko-bot-<instance>
  rm /etc/systemd/system/oko-bot-<instance>.service
  rm ${APP_DIR}/.env-<instance>
  rm ${APP_DIR}/oko_bot_<instance>.db   # если используется SQLite
  systemctl daemon-reload
EOF
    exit 1
}

# ─── Проверка root ────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Запустите от root: sudo bash deploy/deploy-instance.sh <instance_name>"

# ─── Парсинг аргументов ───────────────────────────────────────────────────────
INSTANCE="${1:-}"
[[ -z "$INSTANCE" ]] && usage

# Валидация имени инстанса
if ! [[ "$INSTANCE" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    error "Имя инстанса может содержать только буквы, цифры, дефис и подчёркивание: '$INSTANCE'"
fi

# systemd не любит подчёркивания — заменяем на дефисы
SERVICE_NAME="oko-bot-${INSTANCE//_/-}"
ENV_FILE="$APP_DIR/.env-${INSTANCE}"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"

# ─── Проверка предварительных условий ─────────────────────────────────────────
if [[ ! -d "$APP_DIR/venv" ]]; then
    error "Основная установка не найдена ($APP_DIR/venv). Сначала запустите: sudo bash deploy/setup.sh"
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
    error "Файл .env не найден. Сначала запустите: sudo bash deploy/setup.sh"
fi

# ─── 1. Файл окружения .env-<instance> ────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    info "Создание $ENV_FILE..."
    # Базовый шаблон из .env.example + инстанс-специфичные поля
    cp "$APP_DIR/.env.example" "$ENV_FILE"
    {
        echo ""
        echo "# ─── Instance: $INSTANCE ─────────────────────────────────────────"
        echo ""
        echo "# Telegram bot token для этого инстанса (ОБЯЗАТЕЛЬНО)"
        echo "# Получите у @BotFather — токен должен быть от ДРУГОГО бота,"
        echo "# иначе Telegram разорвёт подключение одного из инстансов."
        echo "BOT_TOKEN="
        echo ""
        echo "# База данных (по умолчанию — отдельный SQLite-файл)"
        echo "# Для PostgreSQL: postgresql+asyncpg://user:pass@host:5432/oko_${INSTANCE}"
        echo "DATABASE_URL=sqlite+aiosqlite:///oko_bot_${INSTANCE}.db"
        echo ""
        echo "# AI-ключи (если нужны отдельные для этого инстанса)"
        echo "# Раскомментируйте и заполните при необходимости:"
        echo "#AI_API_KEY="
        echo "#AI_BASE_URL="
        echo "#AI_MODEL="
    } >> "$ENV_FILE"

    warn "Заполните переменные в $ENV_FILE:"
    warn "  BOT_TOKEN — обязательно (другой токен от @BotFather)"
    warn "  Остальные — при необходимости"
    echo ""
    read -r -p "Нажмите Enter, чтобы открыть $ENV_FILE в nano (или Ctrl+C для пропуска)..." _
    nano "$ENV_FILE" || true
else
    info "$ENV_FILE уже существует."
    read -r -p "Открыть для редактирования? (y/N) " yn
    [[ "$yn" =~ ^[Yy]$ ]] && { nano "$ENV_FILE" || true; }
fi

# ─── 2. Генерация systemd-сервиса ─────────────────────────────────────────────
info "Создание systemd unit: $SERVICE_NAME..."

cat > "$SERVICE_DST" <<EOF
[Unit]
Description=Oko Telegram Bot (instance: $INSTANCE)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/python -m src.bot.main
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" --quiet

# ─── 3. Запуск сервиса ────────────────────────────────────────────────────────
# Проверяем, задан ли BOT_TOKEN
if grep -qE '^BOT_TOKEN=\s*$' "$ENV_FILE" 2>/dev/null || ! grep -q '^BOT_TOKEN=' "$ENV_FILE" 2>/dev/null; then
    warn "BOT_TOKEN не задан в $ENV_FILE — сервис не запущен."
    warn "Заполните $ENV_FILE и выполните: systemctl start $SERVICE_NAME"
else
    info "Запуск $SERVICE_NAME..."
    systemctl restart "$SERVICE_NAME"
    sleep 2
    systemctl status "$SERVICE_NAME" --no-pager || true
fi

# ─── Готово ───────────────────────────────────────────────────────────────────
echo ""
info "Инстанс '$INSTANCE' развёрнут!"
echo -e "  Конфиг:  ${YELLOW}$ENV_FILE${NC}"
echo -e "  Логи:    ${YELLOW}journalctl -u $SERVICE_NAME -f${NC}"
echo -e "  Статус:  ${YELLOW}systemctl status $SERVICE_NAME${NC}"
echo -e "  Стоп:    ${YELLOW}systemctl stop $SERVICE_NAME${NC}"
echo -e "  Рестарт: ${YELLOW}systemctl restart $SERVICE_NAME${NC}"
echo ""
echo -e "  ${CYAN}Все инстансы бота:${NC}"
echo -e "  ${YELLOW}systemctl list-units --type=service | grep oko-bot${NC}"