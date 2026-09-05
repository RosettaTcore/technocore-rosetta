#!/usr/bin/env bash
set -Eeuo pipefail

source_root="${1:?active release directory required}"
public_ip="${2:?public IPv4 address required}"
account_email="${3:?ACME account email required}"
certbot_image="certbot/certbot@sha256:1dc5b4a99cce916f154c706569baf062600d7dea13e0711e7d7e1461d6230e39"

test "$(id -u)" = "0"
source_root="$(readlink -f -- "$source_root")"
test "$source_root" = "$(readlink -f -- /opt/rosetta/current)"
test "$(dirname -- "$source_root")" = "/opt/rosetta/releases"
basename -- "$source_root" | grep -Eq '^[0-9a-f]{40}$'
python3 - "$public_ip" "$account_email" <<'PY'
import ipaddress
import re
import sys

address = ipaddress.ip_address(sys.argv[1])
if address.version != 4 or not address.is_global:
    raise SystemExit("public IPv4 address required")
if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", sys.argv[2]):
    raise SystemExit("valid ACME account email required")
PY

for command in docker flock nginx openssl python3 systemctl; do
  command -v "$command" >/dev/null
done
for file in \
  deploy/rosetta-static-origin-http.conf \
  deploy/rosetta-static-origin-https.conf \
  deploy/renew-rosetta-ip-certificate.sh \
  deploy/check-rosetta-static-origin.sh \
  deploy/rosetta-certificate-renew.service \
  deploy/rosetta-certificate-renew.timer \
  deploy/rosetta-static-origin-healthcheck.service \
  deploy/rosetta-static-origin-healthcheck.timer; do
  test -f "$source_root/$file"
done
docker image inspect "$certbot_image" >/dev/null

install -d -o root -g root -m 0755 /etc/rosetta
install -d -o root -g root -m 0700 /etc/letsencrypt
install -d -o root -g root -m 0755 /var/lib/rosetta/public
install -d -o root -g root -m 0755 /var/lib/rosetta/acme
install -d -o root -g root -m 0700 /var/lib/rosetta/certbot
install -d -o root -g root -m 0700 /var/log/rosetta-certbot
install -d -o root -g root -m 0755 /etc/nginx/sites-available /etc/nginx/sites-enabled
ip_record="$(mktemp)"
printf '%s\n' "$public_ip" >"$ip_record"
install -o root -g root -m 0444 "$ip_record" /etc/rosetta/static-origin.ip
rm -f -- "$ip_record"

if test -e /etc/nginx/sites-enabled/default; then
  test -L /etc/nginx/sites-enabled/default
  test "$(readlink -f -- /etc/nginx/sites-enabled/default)" = \
    "$(readlink -f -- /etc/nginx/sites-available/default)"
  unlink /etc/nginx/sites-enabled/default
fi

install -o root -g root -m 0444 \
  "$source_root/deploy/rosetta-static-origin-http.conf" \
  /etc/nginx/sites-available/rosetta-static-origin
ln -sfn /etc/nginx/sites-available/rosetta-static-origin \
  /etc/nginx/sites-enabled/rosetta-static-origin
nginx -t
systemctl enable --now nginx.service
systemctl reload nginx.service

docker run --rm \
  --name rosetta-certbot-initial \
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
  "$certbot_image" certonly \
  --non-interactive \
  --agree-tos \
  --email "$account_email" \
  --preferred-profile shortlived \
  --webroot \
  --webroot-path /var/www/certbot \
  --ip-address "$public_ip"

rendered_config="$(mktemp)"
trap 'rm -f -- "$rendered_config"' EXIT
sed "s/__ROSETTA_PUBLIC_IP__/$public_ip/g" \
  "$source_root/deploy/rosetta-static-origin-https.conf" >"$rendered_config"
install -o root -g root -m 0444 "$rendered_config" \
  /etc/nginx/sites-available/rosetta-static-origin

install -o root -g root -m 0555 \
  "$source_root/deploy/renew-rosetta-ip-certificate.sh" \
  /usr/local/libexec/renew-rosetta-ip-certificate
install -o root -g root -m 0555 \
  "$source_root/deploy/check-rosetta-static-origin.sh" \
  /usr/local/libexec/check-rosetta-static-origin
for unit in \
  rosetta-certificate-renew.service \
  rosetta-certificate-renew.timer \
  rosetta-static-origin-healthcheck.service \
  rosetta-static-origin-healthcheck.timer; do
  install -o root -g root -m 0444 \
    "$source_root/deploy/$unit" "/etc/systemd/system/$unit"
done

nginx -t
systemctl reload nginx.service
systemctl daemon-reload
systemctl start rosetta-static-origin-healthcheck.service
systemctl enable --now \
  rosetta-certificate-renew.timer \
  rosetta-static-origin-healthcheck.timer
systemctl is-active --quiet rosetta-certificate-renew.timer
systemctl is-active --quiet rosetta-static-origin-healthcheck.timer

printf 'static_origin_install=pass\n'
