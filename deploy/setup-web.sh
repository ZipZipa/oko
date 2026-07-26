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

# ─── Параметры ────────────────────────────────────────────────────────────────
APP_DIR="/opt/oko"
SERVICE_NAME="oko-web"
SERVICE_SRC="$APP_DIR/deploy/oko-web.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_SRC="$APP_DIR/deploy/nginx-oko-web.conf"
NGINX_DST="/etc/nginx/sites-available/oko-web"
NGINX_LINK="/etc/nginx/sites-enabled/oko-web"
ENV_FILE="$APP_DIR/.env"
WEB_PORT="${WEB_PORT:-8080}"

usage() {
    cat <<EOF
${CYAN}Oko WebApp — «Спросить ОКО»${NC}

Ставит веб-сервис мини-аппа, nginx-прокси и TLS-сертификат.

${CYAN}Использование:${NC}
  sudo bash deploy/setup-web.sh <домен> [email-для-certbot]

${CYAN}Пример:${NC}
  sudo bash deploy/setup-web.sh oko.example.com admin@example.com

${CYAN}Перед запуском:${NC}
  A-запись домена должна указывать на этот сервер,
  порты 80 и 443 должны быть открыты,
  основная установка (deploy/setup.sh) уже выполнена.
EOF
    exit 1
}

[[ $EUID -ne 0 ]] && error "Запустите от root: sudo bash deploy/setup-web.sh <домен>"

DOMAIN="${1:-}"
CERT_EMAIL="${2:-}"
[[ -z "$DOMAIN" ]] && usage
if ! [[ "$DOMAIN" =~ ^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
    error "Домен выглядит некорректно: '$DOMAIN'"
fi

[[ -d "$APP_DIR/venv" ]] || error "Основная установка не найдена ($APP_DIR/venv). Сначала: sudo bash deploy/setup.sh"
[[ -f "$ENV_FILE" ]]     || error "Нет $ENV_FILE. Сначала: sudo bash deploy/setup.sh"

# ─── 1. Зависимости ───────────────────────────────────────────────────────────
info "Установка nginx и certbot..."
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx

# ─── 2. WEBAPP_URL в .env ─────────────────────────────────────────────────────
WEBAPP_URL="https://${DOMAIN}"
if grep -q '^WEBAPP_URL=' "$ENV_FILE"; then
    CURRENT=$(grep '^WEBAPP_URL=' "$ENV_FILE" | head -1 | cut -d= -f2-)
    if [[ "$CURRENT" != "$WEBAPP_URL" ]]; then
        info "Обновляю WEBAPP_URL в .env: $CURRENT → $WEBAPP_URL"
        sed -i "s|^WEBAPP_URL=.*|WEBAPP_URL=${WEBAPP_URL}|" "$ENV_FILE"
    else
        info "WEBAPP_URL уже задан."
    fi
else
    info "Добавляю WEBAPP_URL в .env..."
    printf '\n# WebApp «Спросить ОКО»\nWEBAPP_URL=%s\nWEB_HOST=127.0.0.1\nWEB_PORT=%s\n' \
        "$WEBAPP_URL" "$WEB_PORT" >> "$ENV_FILE"
fi

# ─── 3. systemd-сервис ────────────────────────────────────────────────────────
UNIT_CHANGED=false
if [[ ! -f "$SERVICE_DST" ]] || ! diff -q "$SERVICE_SRC" "$SERVICE_DST" > /dev/null 2>&1; then
    info "Установка systemd unit $SERVICE_NAME..."
    cp "$SERVICE_SRC" "$SERVICE_DST"
    systemctl daemon-reload
    UNIT_CHANGED=true
else
    info "systemd unit не изменился."
fi
systemctl enable "$SERVICE_NAME" --quiet

# ─── 4. nginx ─────────────────────────────────────────────────────────────────
info "Настройка nginx для $DOMAIN..."
sed -e "s|__DOMAIN__|${DOMAIN}|g" -e "s|__PORT__|${WEB_PORT}|g" "$NGINX_SRC" > "$NGINX_DST"
ln -sf "$NGINX_DST" "$NGINX_LINK"
nginx -t || error "Конфигурация nginx не прошла проверку"
systemctl reload nginx

# ─── 5. Запуск сервиса ────────────────────────────────────────────────────────
if [[ "$UNIT_CHANGED" == true ]] || ! systemctl is-active --quiet "$SERVICE_NAME"; then
    info "Запуск $SERVICE_NAME..."
    systemctl restart "$SERVICE_NAME"
else
    info "Перезапуск $SERVICE_NAME (подхватить .env)..."
    systemctl restart "$SERVICE_NAME"
fi
sleep 2
systemctl is-active --quiet "$SERVICE_NAME" || {
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager
    error "$SERVICE_NAME не поднялся — смотрите лог выше"
}

# ─── 6. TLS ───────────────────────────────────────────────────────────────────
if [[ -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
    info "Сертификат для $DOMAIN уже есть — пропускаю certbot."
else
    info "Выпуск сертификата Let's Encrypt..."
    if [[ -n "$CERT_EMAIL" ]]; then
        certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$CERT_EMAIL" --redirect
    else
        warn "Email не передан — certbot спросит данные интерактивно."
        certbot --nginx -d "$DOMAIN" --redirect
    fi
fi

# ─── 7. Перезапуск бота ───────────────────────────────────────────────────────
# Бот читает WEBAPP_URL при старте: без рестарта кнопка «Спросить ОКО» не появится.
if systemctl list-unit-files | grep -q '^oko-bot.service'; then
    info "Перезапуск oko-bot, чтобы появилась кнопка мини-аппа..."
    systemctl restart oko-bot
fi

# ─── Готово ───────────────────────────────────────────────────────────────────
echo ""
info "Готово! Мини-апп: ${WEBAPP_URL}"
echo -e "  Проверка: ${YELLOW}curl -s ${WEBAPP_URL}/health${NC}"
echo -e "  Логи:     ${YELLOW}journalctl -u ${SERVICE_NAME} -f${NC}"
echo -e "  Рестарт:  ${YELLOW}systemctl restart ${SERVICE_NAME}${NC}"
