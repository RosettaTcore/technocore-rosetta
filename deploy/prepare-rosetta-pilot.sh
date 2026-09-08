#!/usr/bin/env bash
set -Eeuo pipefail

test "$(id -u)" = "0"
test -f /etc/rosetta/pilot.env
test -f /etc/rosetta/pilot.yaml
systemctl is-active --quiet rosetta-signer.production.service
systemctl is-active --quiet rosetta-pilot.service && {
  echo "refusing to prepare while pilot is active" >&2
  exit 1
}

cd /opt/rosetta/current
docker compose --env-file /etc/rosetta/pilot.env -f deploy/compose.pilot.yaml \
  run --rm pilot rosetta.pilot --config /etc/rosetta/pilot.yaml prepare
test -s /var/lib/rosetta/pilot/activation-preview.json
test -s /var/lib/rosetta/pilot/activation-preview.sha256
printf 'pilot_prepare=pass\npublic_writes=0\npreview=/var/lib/rosetta/pilot/activation-preview.json\n'
