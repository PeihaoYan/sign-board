#!/usr/bin/env bash
# Put Caddy in front of the signature wall for HTTPS on a real domain.
#
#   sudo bash deploy/setup-caddy.sh --domain wall.example.com                 # Let's Encrypt
#   sudo bash deploy/setup-caddy.sh --domain wall.example.com --origin-cert   # Cloudflare origin cert
#
# The app keeps listening on a loopback port (default 18080) and Caddy terminates TLS on
# 80/443. With --origin-cert, place the Cloudflare Origin CA certificate at
# /etc/caddy/certs/origin.pem and its private key at /etc/caddy/certs/origin.key first;
# that variant is the one to use while the domain is proxied by Cloudflare.
set -euo pipefail

DOMAIN=""
ORIGIN_CERT=0
APP_PORT="${APP_PORT:-18080}"
PUBLIC_PORT="${PUBLIC_PORT:-80}"
HTTPS_PORT="${HTTPS_PORT:-443}"
CADDYFILE=/etc/caddy/Caddyfile

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --origin-cert) ORIGIN_CERT=1; shift ;;
    --app-port) APP_PORT="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "please run with sudo" >&2
  exit 2
fi
if [[ -z "${DOMAIN}" ]]; then
  echo "usage: sudo bash deploy/setup-caddy.sh --domain <domain> [--origin-cert]" >&2
  exit 2
fi

echo "== install caddy =="
if ! command -v caddy >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg >/dev/null
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy >/dev/null
fi

echo "== move the app to a loopback port =="
# Caddy must own 80/443, so the app leaves port 80.
CURRENT_EXEC=$(grep '^ExecStart=' /etc/systemd/system/sign-board.service)
if grep -q -- '--port 80' /etc/systemd/system/sign-board.service; then
  sed -i "s|--host 0\.0\.0\.0 --port 80|--host 127.0.0.1 --port ${APP_PORT}|" /etc/systemd/system/sign-board.service
  systemctl daemon-reload
  systemctl restart sign-board.service
  sleep 2
fi
echo "exec_start=${CURRENT_EXEC}"

echo "== Caddyfile =="
mkdir -p /etc/caddy
if [[ "${ORIGIN_CERT}" -eq 1 ]]; then
  if [[ ! -f /etc/caddy/certs/origin.pem || ! -f /etc/caddy/certs/origin.key ]]; then
    echo "missing /etc/caddy/certs/origin.pem or origin.key" >&2
    exit 3
  fi
  cat > "${CADDYFILE}" <<CADDY
{
	admin off
}

https://${DOMAIN} {
	tls /etc/caddy/certs/origin.pem /etc/caddy/certs/origin.key
	encode zstd gzip
	reverse_proxy 127.0.0.1:${APP_PORT}
}

http://${DOMAIN} {
	redir https://{host}{uri} permanent
}
CADDY
else
  cat > "${CADDYFILE}" <<CADDY
{
	admin off
}

${DOMAIN} {
	encode zstd gzip
	reverse_proxy 127.0.0.1:${APP_PORT}
}
CADDY
fi

caddy validate --config "${CADDYFILE}" --adapter caddyfile
systemctl enable caddy >/dev/null
systemctl restart caddy
sleep 3

echo "== drop the old raw-port redirect rules =="
iptables -t nat -D PREROUTING -p tcp --dport "${PUBLIC_PORT}" -j REDIRECT --to-ports "${APP_PORT}" 2>/dev/null || true
netfilter-persistent save >/dev/null 2>&1 || true

echo "== firewall (if any) =="
if command -v ufw >/dev/null 2>&1; then
  ufw allow "${PUBLIC_PORT}/tcp" >/dev/null 2>&1 || true
  ufw allow "${HTTPS_PORT}/tcp" >/dev/null 2>&1 || true
fi

echo "== status =="
systemctl --no-pager --lines=0 status caddy || true
echo "app_health=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${APP_PORT}/health")"
echo "https_via_host=$(curl -s -k -o /dev/null -w '%{http_code}' "https://127.0.0.1/health" -H "Host: ${DOMAIN}")"
echo "done"
