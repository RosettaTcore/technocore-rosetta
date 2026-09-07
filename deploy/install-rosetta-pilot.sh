#!/usr/bin/env bash
set -Eeuo pipefail

source_root="${1:?active release directory required}"
staging_environment="${2:?staging environment file required}"
pilot_config_source="${3:?reviewed pilot configuration required}"
service=rosetta-pilot.service
runtime_uid=65532
runtime_gid=65532
signer_gid=65531

test "$(id -u)" = "0"
source_root="$(readlink -f -- "$source_root")"
test "$source_root" = "$(readlink -f -- /opt/rosetta/current)"
test "$(dirname -- "$source_root")" = "/opt/rosetta/releases"
basename -- "$source_root" | grep -Eq '^[0-9a-f]{40}$'
test -f "$staging_environment"
test -f "$pilot_config_source"
test ! -L "$pilot_config_source"
test "$(grep -c '^ROSETTA_IMAGE=' "$staging_environment")" = "1"
image="$(awk -F= '$1 == "ROSETTA_IMAGE" {print substr($0, index($0, "=") + 1)}' "$staging_environment")"
printf '%s\n' "$image" | grep -Eq '^sha256:[0-9a-f]{64}$'
test "$(docker image inspect "$image" --format '{{.Id}}')" = "$image"

for file in \
  deploy/compose.pilot.yaml \
  deploy/rosetta-pilot.service \
  deploy/prepare-rosetta-pilot.sh \
  deploy/activate-rosetta-pilot.sh \
  deploy/check-rosetta-pilot.sh \
  deploy/rosetta-pilot-healthcheck.service \
  deploy/rosetta-pilot-healthcheck.timer; do
  test -f "$source_root/$file"
done
if systemctl is-active --quiet "$service" || systemctl is-enabled --quiet "$service"; then
  echo "refusing to replace an active or enabled pilot" >&2
  exit 1
fi
test "$(getent passwd rosetta-runtime | cut -d: -f3)" = "$runtime_uid"
test "$(getent group rosetta-runtime | cut -d: -f3)" = "$runtime_gid"
test "$(getent group rosetta-signer | cut -d: -f3)" = "$signer_gid"

install -d -o root -g root -m 0755 /etc/rosetta /usr/local/libexec
install -o root -g root -m 0444 "$pilot_config_source" /etc/rosetta/pilot.yaml
mapfile -t identity < <(
  docker run --rm --network none --read-only --user "$runtime_uid:$runtime_gid" \
    --cap-drop ALL --security-opt no-new-privileges:true \
    -e ROSETTA_PILOT_ENABLE=PUBLIC_WRITES_APPROVED \
    --mount type=bind,src=/etc/rosetta/pilot.yaml,dst=/etc/rosetta/pilot.yaml,readonly \
    --entrypoint python "$image" -c \
    'from pathlib import Path; from rosetta.pilot_config import load_pilot_config; from rosetta.service import service_names; c=load_pilot_config(Path("/etc/rosetta/pilot.yaml")); print(c.identity.public_did); print(*service_names(c.identity.public_did), sep="\n")'
)
test "${#identity[@]}" = "3"
printf '%s\n' "${identity[0]}" | grep -Eq '^did:key:z[1-9A-HJ-NP-Za-km-z]{20,120}$'
printf '%s\n' "${identity[1]}" | grep -Eq '^d-rosetta-[a-z0-9]{16}$'
printf '%s\n' "${identity[2]}" | grep -Eq '^mb-rosetta-[a-z0-9]{16}$'

environment_temporary="$(mktemp)"
trap 'rm -f -- "$environment_temporary"' EXIT
printf '%s\n' \
  "ROSETTA_IMAGE=$image" \
  "ROSETTA_PUBLIC_DID=${identity[0]}" \
  "ROSETTA_SERVICE_ROOM=${identity[1]}" \
  "ROSETTA_REQUEST_MAILBOX=${identity[2]}" \
  "ROSETTA_PILOT_CONFIG=/etc/rosetta/pilot.yaml" >"$environment_temporary"
install -o root -g root -m 0444 "$environment_temporary" /etc/rosetta/pilot.env

install -d -o "$runtime_uid" -g "$runtime_gid" -m 0700 \
  /var/lib/rosetta/pilot /var/lib/rosetta/publish-spool
install -d -o "$runtime_uid" -g "$runtime_gid" -m 0755 /var/lib/rosetta/public
install -o root -g root -m 0555 \
  "$source_root/deploy/check-rosetta-pilot.sh" /usr/local/libexec/check-rosetta-pilot
install -o root -g root -m 0555 \
  "$source_root/deploy/prepare-rosetta-pilot.sh" /usr/local/libexec/prepare-rosetta-pilot
install -o root -g root -m 0555 \
  "$source_root/deploy/activate-rosetta-pilot.sh" /usr/local/libexec/activate-rosetta-pilot
for unit in \
  rosetta-pilot.service \
  rosetta-pilot-healthcheck.service \
  rosetta-pilot-healthcheck.timer; do
  install -o root -g root -m 0444 "$source_root/deploy/$unit" "/etc/systemd/system/$unit"
done

docker compose --env-file /etc/rosetta/pilot.env \
  -f "$source_root/deploy/compose.pilot.yaml" config --quiet
systemd-analyze verify "/etc/systemd/system/$service"
systemd-analyze verify /etc/systemd/system/rosetta-pilot-healthcheck.service
systemd-analyze verify /etc/systemd/system/rosetta-pilot-healthcheck.timer
systemctl daemon-reload
printf 'pilot_install=pass\npilot_enabled=no\npublic_writes=0\n'
