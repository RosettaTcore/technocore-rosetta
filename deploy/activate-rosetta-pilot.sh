#!/usr/bin/env bash
set -Eeuo pipefail

approved_digest="${1:?exact approved activation preview digest required}"
test "$(id -u)" = "0"
printf '%s\n' "$approved_digest" | grep -Eq '^sha256:[0-9a-f]{64}$'
test "$(tr -d '\n' </var/lib/rosetta/pilot/activation-preview.sha256)" = "$approved_digest"
systemctl is-active --quiet rosetta-signer.production.service
systemctl is-active --quiet rosetta-pilot.service && {
  echo "pilot is already active" >&2
  exit 1
}

cd /opt/rosetta/current
docker compose --env-file /etc/rosetta/pilot.env -f deploy/compose.pilot.yaml \
  run --rm pilot rosetta.pilot --config /etc/rosetta/pilot.yaml \
  activate --approved-digest "$approved_digest"
test -s /var/lib/rosetta/pilot/activation.json
systemctl enable --now rosetta-pilot.service
systemctl enable --now rosetta-pilot-healthcheck.timer
for _attempt in $(seq 1 60); do
  if /usr/local/libexec/check-rosetta-pilot >/dev/null 2>&1; then
    printf 'pilot_activation=pass\n'
    exit 0
  fi
  sleep 1
done
echo "pilot did not become healthy within 60 seconds" >&2
exit 1
