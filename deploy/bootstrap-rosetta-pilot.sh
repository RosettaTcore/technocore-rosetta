#!/usr/bin/env bash
set -Eeuo pipefail

test "$#" = "0"
test "$(id -u)" = "0"

source_root="$(readlink -f -- /opt/rosetta/current)"
staging_environment=/etc/rosetta/staging.env
public_ip_file=/etc/rosetta/static-origin.ip
signer_socket=/run/rosetta-signer/signer.sock
pilot_config=

cleanup() {
  if test -n "$pilot_config"; then
    find "$pilot_config" -maxdepth 0 -type f -delete 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

test "$source_root" = "$(readlink -f -- /opt/rosetta/current)"
test "$(dirname -- "$source_root")" = "/opt/rosetta/releases"
basename -- "$source_root" | grep -Eq '^[0-9a-f]{40}$'
test -f "$staging_environment"
test -r "$public_ip_file"
test ! -L "$public_ip_file"
test "$(stat -c '%u' "$public_ip_file")" = "0"
test -S "$signer_socket"
systemctl is-active --quiet rosetta-signer.production.service
! systemctl is-active --quiet rosetta-pilot.service
! systemctl is-enabled --quiet rosetta-pilot.service
test ! -e /etc/rosetta/pilot.yaml
test ! -e /var/lib/rosetta/pilot/activation-preview.json

test "$(grep -c '^ROSETTA_IMAGE=' "$staging_environment")" = "1"
image="$(awk -F= '$1 == "ROSETTA_IMAGE" {print substr($0, index($0, "=") + 1)}' \
  "$staging_environment")"
printf '%s\n' "$image" | grep -Eq '^sha256:[0-9a-f]{64}$'
test "$(docker image inspect "$image" --format '{{.Id}}')" = "$image"

public_ip="$(tr -d '\r\n' <"$public_ip_file")"
python3 - "$public_ip" <<'PY'
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1])
assert address.version == 4
assert address.is_global
PY

# Ask the already-running networkless signer for only its public DID. The request signs a fixed
# service-document probe and does not create any Technocore or other network write.
public_did="$(
  docker run --rm \
    --network none \
    --read-only \
    --user 65532:65532 \
    --group-add 65531 \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --pids-limit 32 \
    --memory 64m \
    --cpus 0.1 \
    --tmpfs /tmp:rw,noexec,nosuid,size=8m \
    --mount type=bind,src=/run/rosetta-signer,dst=/run/rosetta-signer \
    --entrypoint python \
    "$image" -c '
import asyncio
import hashlib
from rosetta.contracts import SignRequest
from rosetta.signer_client import SignerClient

async def main() -> None:
    digest = "sha256:" + hashlib.sha256(b"rosetta-pilot-bootstrap-identity-v1").hexdigest()
    response = await SignerClient("/run/rosetta-signer/signer.sock").sign(
        SignRequest(action="service_document", scope="pilot-bootstrap-identity", digest=digest)
    )
    print(response.did)

asyncio.run(main())
'
)"
printf '%s\n' "$public_did" | grep -Eq '^did:key:z[1-9A-HJ-NP-Za-km-z]{20,120}$'
test "$(printf '%s\n' "$public_did" | wc -l)" = "1"

pilot_config="$(mktemp /root/.rosetta-pilot-config.XXXXXX)"
chmod 0400 "$pilot_config"
cat >"$pilot_config" <<EOF
schema: rosetta.pilot-config.v1
mode: pilot

technocore:
  authority_origin: "https://technocore.chat"
  fetch_origin: "http://technocore-egress:8082"
  pinned_release: "v0.13.0"
  discovery_rooms: ["lobby", "meta"]
  request_timeout_seconds: 20
  max_response_bytes: 1048576

identity:
  public_did: "$public_did"
  signer_socket: "$signer_socket"

service:
  enabled: true
  public_base_url: "https://$public_ip"
  state_directory: "/var/lib/rosetta/pilot"
  spool_directory: "/var/lib/rosetta/publish-spool"
  static_root: "/var/lib/rosetta/public"
  kill_switch_file: "/var/lib/rosetta/state/KILL_SWITCH"
  poll_seconds: 10
  max_requests_per_did_per_day: 2
  max_external_jobs_per_day: 8
  max_queue_depth: 16
  max_parallel_runners: 1
  monthly_budget_cents: 4000

model_provider: disabled
EOF

"$source_root/deploy/install-rosetta-pilot.sh" \
  "$source_root" "$staging_environment" "$pilot_config"
/usr/local/libexec/prepare-rosetta-pilot

test -s /var/lib/rosetta/pilot/activation-preview.json
test -s /var/lib/rosetta/pilot/activation-preview.sha256
cat /var/lib/rosetta/pilot/activation-preview.json
cat /var/lib/rosetta/pilot/activation-preview.sha256
printf 'pilot_bootstrap=pass\npilot_enabled=no\npublic_writes=0\n'
