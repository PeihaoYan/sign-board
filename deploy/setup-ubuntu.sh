#!/usr/bin/env bash
# Provision the signature wall on a fresh Ubuntu host.
# Run from the project root after uploading the sources:
#   sudo bash deploy/setup-ubuntu.sh
#
# Supply ADMIN_TOKEN through the environment, ADMIN_TOKEN_FILE, or the hidden prompt below.
# Never pass a token as a command-line argument: process listings and shell history can expose it.
#
# The service binds port 80 directly and is granted CAP_NET_BIND_SERVICE by systemd.
# Earlier revisions used an iptables REDIRECT to port 18180; that approach was removed
# because on this host external connections to port 80 were reset while port 8080 worked.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sign-board}"
APP_USER="${APP_USER:-signboard}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
ADMIN_TOKEN_FILE="${ADMIN_TOKEN_FILE:-}"

if [[ -z "${ADMIN_TOKEN}" && -n "${ADMIN_TOKEN_FILE}" ]]; then
  if [[ ! -r "${ADMIN_TOKEN_FILE}" ]]; then
    echo "ADMIN_TOKEN_FILE is not readable: ${ADMIN_TOKEN_FILE}" >&2
    exit 2
  fi
  ADMIN_TOKEN="$(head -n 1 "${ADMIN_TOKEN_FILE}" | tr -d '\r\n')"
fi
if [[ -z "${ADMIN_TOKEN}" && -t 0 ]]; then
  read -r -s -p "Admin token: " ADMIN_TOKEN
  echo
fi
if [[ -z "${ADMIN_TOKEN}" ]]; then
  echo "set ADMIN_TOKEN, set ADMIN_TOKEN_FILE, or run interactively for a hidden prompt" >&2
  exit 2
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "please run with sudo" >&2
  exit 2
fi

echo "== packages =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip >/dev/null

echo "== service account =="
id -u "${APP_USER}" >/dev/null 2>&1 || useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"

echo "== python environment =="
rm -rf "${APP_DIR}/.venv" "${APP_DIR}/app/__pycache__"
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"

echo "== permissions =="
# The service account must be able to read the application code.
chmod 755 "${APP_DIR}" "${APP_DIR}/app" "${APP_DIR}/static" "${APP_DIR}/deploy"
chmod 644 "${APP_DIR}"/app/*.py "${APP_DIR}"/static/* 2>/dev/null || true
mkdir -p "${APP_DIR}/data/signatures"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}/data"

echo "== environment file =="
# A separate read-only credential for /monitor keeps on-site staff from getting edit rights.
MONITOR_TOKEN="$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n')"
cat > "${APP_DIR}/.env" <<ENVFILE
DATA_DIR=${APP_DIR}/data
EVENT_SLUG=integrity-2026
EVENT_TITLE=科研诚信研讨会
EVENT_SUBTITLE=以诚立身，以实求真
EVENT_ORGANIZATION=科研诚信主题活动
# The first deployment stays closed until an operator explicitly opens the event.
EVENT_STATUS=draft
ADMIN_TOKEN=${ADMIN_TOKEN}
MONITOR_TOKEN=${MONITOR_TOKEN}
ENVFILE
chown "${APP_USER}:${APP_USER}" "${APP_DIR}/.env"
chmod 600 "${APP_DIR}/.env"
echo "credentials written to ${APP_DIR}/.env; tokens are intentionally not printed"

echo "== systemd unit =="
install -m 644 "${APP_DIR}/deploy/sign-board.service" /etc/systemd/system/sign-board.service
systemctl daemon-reload
systemctl enable sign-board.service >/dev/null
systemctl restart sign-board.service

echo "== status =="
sleep 3
systemctl --no-pager --lines=0 status sign-board.service || true
curl -fsS http://127.0.0.1/health && echo
echo "done"
