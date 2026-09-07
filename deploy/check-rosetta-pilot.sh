#!/usr/bin/env bash
set -Eeuo pipefail

health=/var/lib/rosetta/pilot/health.json
activation=/var/lib/rosetta/pilot/activation.json

test -s "$health"
test -s "$activation"
test -S /run/rosetta-signer/signer.sock
systemctl is-active --quiet rosetta-signer.production.service
systemctl is-active --quiet rosetta-pilot.service
docker compose --env-file /etc/rosetta/pilot.env \
  -f /opt/rosetta/current/deploy/compose.pilot.yaml ps --status running --quiet pilot | grep -q .

python3 - "$health" "$activation" <<'PY'
import datetime
import json
import pathlib
import sys

health = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
activation = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
now = datetime.datetime.now(datetime.timezone.utc)
checked = datetime.datetime.fromisoformat(health["checked_at"])
assert (now - checked).total_seconds() < 120
assert health["schema"] == "rosetta.pilot-health.v1"
assert health["status"] == "healthy"
assert health["public_writes_enabled"] is True
assert activation["schema"] == "rosetta.pilot-activation.v1"
assert health["service_room"] == activation["service_room"]
assert health["request_mailbox"] == activation["request_mailbox"]
PY

printf 'pilot_health=pass\n'
