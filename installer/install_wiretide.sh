#!/usr/bin/env bash
set -euo pipefail

# Wiretide Controller Installer
# - Creates wiretide user/groups, directories, venv
# - Deploys backend code to /opt/wiretide
# - Configures systemd + nginx
# Flags:
#   --dry-run   : show actions without changing the system
#   --update    : backup existing /opt/wiretide before deploying
#   --cert-cn X : CN for self-signed TLS cert (default: wiretide.local)

DRY_RUN=0
DO_UPDATE=0
CERT_CN="wiretide.local"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --update) DO_UPDATE=1; shift ;;
    --cert-cn) CERT_CN="${2:-wiretide.local}"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

log() { echo "[$(date -Iseconds)] $*"; }
run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] $*"
  else
    "$@"
  fi
}

require_root() {
  if [[ "$DRY_RUN" -eq 0 && "$(id -u)" -ne 0 ]]; then
    echo "This script must run as root (or use sudo)."
    exit 1
  fi
}

require_root

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd -P)"
SRC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
APP_DIR="/opt/wiretide"
STATIC_DIR="$APP_DIR/backend/static"
VENV_DIR="$APP_DIR/venv"
DATA_DIR="/var/lib/wiretide"
CONFIG_DIR="/etc/wiretide"
LOG_DIR="/var/log/wiretide"
NGINX_CONF="/etc/nginx/sites-available/wiretide.conf"
SYSTEMD_UNIT="/etc/systemd/system/wiretide.service"
CERT_DIR="/etc/ssl/nginx"
CERT_PATH="$CERT_DIR/wiretide.crt"
KEY_PATH="$CERT_DIR/wiretide.key"
WIRETIDE_USER="wiretide"
WIRETIDE_GROUP="wiretide"

log "Starting Wiretide installer (dry-run=$DRY_RUN, update=$DO_UPDATE)"

# Users / groups
if ! id -u "$WIRETIDE_USER" >/dev/null 2>&1; then
  run useradd --system --create-home --shell /usr/sbin/nologin "$WIRETIDE_USER"
fi

# Directories
for d in "$APP_DIR" "$DATA_DIR" "$CONFIG_DIR" "$LOG_DIR"; do
  run mkdir -p "$d"
  run chown "$WIRETIDE_USER:$WIRETIDE_GROUP" "$d"
done

# Backup on update
if [[ "$DO_UPDATE" -eq 1 && "$DRY_RUN" -eq 0 && -d "$APP_DIR" ]]; then
  TS="$(date +%Y%m%d%H%M%S)"
  BACKUP_PATH="/opt/wiretide.bak.$TS.tar.gz"
  log "Creating backup at $BACKUP_PATH"
  run tar -czf "$BACKUP_PATH" -C /opt wiretide
fi

# Packages
run apt-get update
run apt-get install -y python3 python3-venv python3-pip nginx sqlite3 curl

# Deploy code
run mkdir -p "$APP_DIR/backend"
run rsync -a --delete --exclude '.venv' "$SRC_ROOT/backend/" "$APP_DIR/backend/"
run chown -R "$WIRETIDE_USER:$WIRETIDE_GROUP" "$APP_DIR"

# Venv + deps
if [[ "$DRY_RUN" -eq 0 ]]; then
  if [[ ! -d "$VENV_DIR" ]]; then
    run python3 -m venv "$VENV_DIR"
  fi
  run "$VENV_DIR/bin/pip" install --upgrade pip
  run "$VENV_DIR/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
fi

# Systemd service
run bash -c "cat > '$SYSTEMD_UNIT' <<'EOF'
[Unit]
Description=Wiretide Controller Backend
After=network.target

[Service]
User=wiretide
Group=wiretide
WorkingDirectory=$APP_DIR/backend
ExecStart=$VENV_DIR/bin/uvicorn wiretide.main:app --host 127.0.0.1 --port 9000 --workers 2
Restart=always
Environment=WIRETIDE_DATABASE_URL=sqlite:///$DATA_DIR/wiretide.db
Environment=WIRETIDE_ADMIN_TOKEN=wiretide-admin-dev
Environment=WIRETIDE_ADMIN_COOKIE_SECURE=true

[Install]
WantedBy=multi-user.target
EOF"

# TLS self-signed
run mkdir -p "$CERT_DIR"
if [[ ! -f "$CERT_PATH" || ! -f "$KEY_PATH" ]]; then
  run openssl req -x509 -newkey rsa:4096 -days 3650 -nodes \
    -keyout "$KEY_PATH" -out "$CERT_PATH" \
    -subj "/CN=$CERT_CN"
fi

# Nginx config
if [[ "$DRY_RUN" -eq 1 ]]; then
  log "[dry-run] writing nginx config to $NGINX_CONF"
else
cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    server_name _;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name _;
    ssl_certificate     $CERT_PATH;
    ssl_certificate_key $KEY_PATH;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers         'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff";
    add_header X-Frame-Options "DENY";
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy "no-referrer";

    # Proxy everything to uvicorn; let uvicorn serve /static to avoid home-dir perms issues.
    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection upgrade;
        proxy_read_timeout 60s;
    }
}
EOF
fi
run ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/wiretide.conf
run rm -f /etc/nginx/sites-enabled/default

if [[ "$DRY_RUN" -eq 0 ]]; then
  run nginx -t
  run systemctl daemon-reload
  run systemctl enable --now wiretide.service
  run systemctl reload nginx
fi

log "Wiretide installer completed. Uvicorn on 127.0.0.1:9000, Nginx on 443."
