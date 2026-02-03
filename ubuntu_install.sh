#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Remote Support Server — Ubuntu Install Script
#  Sets up Node.js, installs dependencies, and creates a systemd service.
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
APP_NAME="remote-support"
APP_DIR="/opt/${APP_NAME}"
APP_USER="remotesupport"
APP_PORT="${PORT:-3000}"
NODE_MAJOR=20
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

# ── Root check ────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  fail "This script must be run as root (use sudo)."
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Remote Support Server — Installer"
echo "══════════════════════════════════════════════════════════"
echo ""

# ── 1. System updates ────────────────────────────────────────────────────────
info "Updating package lists..."
apt-get update -qq
ok "Package lists updated."

# ── 2. Install Node.js if missing or outdated ────────────────────────────────
install_node() {
  info "Installing Node.js ${NODE_MAJOR}.x..."
  apt-get install -y -qq ca-certificates curl gnupg > /dev/null 2>&1
  mkdir -p /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/nodesource.gpg ]]; then
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  fi
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
    > /etc/apt/sources.list.d/nodesource.list
  apt-get update -qq
  apt-get install -y -qq nodejs > /dev/null 2>&1
  ok "Node.js $(node -v) installed."
}

if command -v node &> /dev/null; then
  CURRENT_NODE=$(node -v | sed 's/v//' | cut -d. -f1)
  if (( CURRENT_NODE >= NODE_MAJOR )); then
    ok "Node.js $(node -v) already installed."
  else
    warn "Node.js $(node -v) is too old, upgrading..."
    install_node
  fi
else
  install_node
fi

# ── 3. Create service user ───────────────────────────────────────────────────
if id "${APP_USER}" &>/dev/null; then
  ok "User '${APP_USER}' already exists."
else
  info "Creating service user '${APP_USER}'..."
  useradd --system --shell /usr/sbin/nologin --home-dir "${APP_DIR}" "${APP_USER}"
  ok "User '${APP_USER}' created."
fi

# ── 4. Copy application files ────────────────────────────────────────────────
info "Installing application to ${APP_DIR}..."
mkdir -p "${APP_DIR}/public"

cp "${SCRIPT_DIR}/server.js"          "${APP_DIR}/server.js"
cp "${SCRIPT_DIR}/package.json"       "${APP_DIR}/package.json"
cp "${SCRIPT_DIR}/public/index.html"     "${APP_DIR}/public/index.html"
cp "${SCRIPT_DIR}/public/operator.html"  "${APP_DIR}/public/operator.html"

# Copy optional files if present
[[ -f "${SCRIPT_DIR}/client.py" ]]        && cp "${SCRIPT_DIR}/client.py"        "${APP_DIR}/client.py"
[[ -f "${SCRIPT_DIR}/requirements.txt" ]] && cp "${SCRIPT_DIR}/requirements.txt" "${APP_DIR}/requirements.txt"
[[ -f "${SCRIPT_DIR}/README.md" ]]        && cp "${SCRIPT_DIR}/README.md"        "${APP_DIR}/README.md"

chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
ok "Application files installed."

# ── 5. Install npm dependencies ──────────────────────────────────────────────
info "Installing npm dependencies..."
cd "${APP_DIR}"
sudo -u "${APP_USER}" npm install --production --silent 2>/dev/null
ok "Dependencies installed."

# ── 6. Create systemd service ────────────────────────────────────────────────
info "Creating systemd service..."

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Remote Support Server
Documentation=file://${APP_DIR}/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/node ${APP_DIR}/server.js
Restart=always
RestartSec=5

# Environment
Environment=NODE_ENV=production
Environment=PORT=${APP_PORT}

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${APP_DIR}
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${APP_NAME}

[Install]
WantedBy=multi-user.target
EOF

ok "Systemd service created."

# ── 7. Enable and start ──────────────────────────────────────────────────────
info "Enabling and starting service..."
systemctl daemon-reload
systemctl enable "${APP_NAME}" --quiet
systemctl restart "${APP_NAME}"

# Wait a moment for the service to start
sleep 2

if systemctl is-active --quiet "${APP_NAME}"; then
  ok "Service is running."
else
  warn "Service may not have started. Check: journalctl -u ${APP_NAME}"
fi

# ── 8. Firewall (ufw) ────────────────────────────────────────────────────────
if command -v ufw &> /dev/null; then
  if ufw status | grep -q "active"; then
    info "Opening port ${APP_PORT} in UFW..."
    ufw allow "${APP_PORT}/tcp" > /dev/null 2>&1
    ok "Firewall rule added for port ${APP_PORT}."
  else
    info "UFW is installed but not active — skipping firewall rule."
  fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
SERVER_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "══════════════════════════════════════════════════════════"
echo -e "  ${GREEN}✓ Installation complete!${NC}"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "  Server running on port ${APP_PORT}"
echo ""
echo "  Operator console:"
echo "    http://${SERVER_IP}:${APP_PORT}/operator.html"
echo ""
echo "  Client command:"
echo "    python client.py --server ws://${SERVER_IP}:${APP_PORT}"
echo ""
echo "  Manage the service:"
echo "    sudo systemctl status  ${APP_NAME}"
echo "    sudo systemctl stop    ${APP_NAME}"
echo "    sudo systemctl start   ${APP_NAME}"
echo "    sudo systemctl restart ${APP_NAME}"
echo "    sudo journalctl -u ${APP_NAME} -f"
echo ""
echo "  Config: ${SERVICE_FILE}"
echo "  App:    ${APP_DIR}"
echo ""
