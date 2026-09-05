#!/usr/bin/env bash
set -Eeuo pipefail

certbot_image="certbot/certbot@sha256:1dc5b4a99cce916f154c706569baf062600d7dea13e0711e7d7e1461d6230e39"

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

test -d /var/lib/rosetta/acme
test -d /var/lib/rosetta/certbot
test -d /var/log/rosetta-certbot
test -d /etc/letsencrypt/live/"$public_ip"
docker image inspect "$certbot_image" >/dev/null

flock /run/rosetta-certbot.lock docker run --rm \
  --name rosetta-certbot-renew \
  --network bridge \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 64 \
  --memory 256m \
  --cpus 0.5 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --mount type=bind,src=/etc/letsencrypt,dst=/etc/letsencrypt \
  --mount type=bind,src=/var/lib/rosetta/certbot,dst=/var/lib/letsencrypt \
  --mount type=bind,src=/var/log/rosetta-certbot,dst=/var/log/letsencrypt \
  --mount type=bind,src=/var/lib/rosetta/acme,dst=/var/www/certbot \
  "$certbot_image" renew --no-random-sleep-on-renew

nginx -t
systemctl reload nginx.service
openssl x509 -checkend 129600 -noout \
  -in "/etc/letsencrypt/live/$public_ip/fullchain.pem"
