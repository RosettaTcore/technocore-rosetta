#!/usr/bin/env bash
set -Eeuo pipefail

test "$(id -u)" = "0"
test -r /etc/rosetta/static-origin.ip
public_ip="$(tr -d '\r\n' </etc/rosetta/static-origin.ip)"
python3 - "$public_ip" <<'PY'
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1])
if address.version != 4 or not address.is_global:
    raise SystemExit("public IPv4 address required")
PY

test -d /var/lib/rosetta/public
test -z "$(find /var/lib/rosetta/public -type l -print -quit)"
systemctl is-active --quiet nginx.service
nginx -t
openssl x509 -checkend 129600 -noout \
  -in "/etc/letsencrypt/live/$public_ip/fullchain.pem"

health="$({ curl --fail --silent --show-error \
  --proto '=https' --tlsv1.2 --max-time 10 \
  --resolve "$public_ip:443:127.0.0.1" \
  "https://$public_ip/healthz"; } 2>/dev/null)"
python3 - "$health" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected = {"schema": "rosetta.static-origin-health.v1", "status": "ok"}
if payload != expected:
    raise SystemExit("unexpected static-origin health payload")
PY

root_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --proto '=https' --tlsv1.2 --max-time 10 \
  --resolve "$public_ip:443:127.0.0.1" "https://$public_ip/")"
test "$root_status" = "404"

post_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --request POST --proto '=https' --tlsv1.2 --max-time 10 \
  --resolve "$public_ip:443:127.0.0.1" "https://$public_ip/healthz")"
test "$post_status" = "403"

printf 'static_origin_status=pass\n'
