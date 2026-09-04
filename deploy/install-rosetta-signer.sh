#!/usr/bin/env bash
set -Eeuo pipefail

source_root="${1:?checked-out release directory required}"
staging_environment="${2:?staging environment file required}"
signer_user=rosetta-signer
signer_uid=65531
signer_gid=65531
service=rosetta-signer.production.service
image_temporary=

cleanup() {
  if test -n "$image_temporary"; then
    find "$image_temporary" -maxdepth 0 -type f -delete 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

test "$(id -u)" = "0"
source_root="$(readlink -f -- "$source_root")"
test "$source_root" = "$(readlink -f -- /opt/rosetta/current)"
test "$(dirname -- "$source_root")" = "/opt/rosetta/releases"
basename -- "$source_root" | grep -Eq '^[0-9a-f]{40}$'
test -f "$source_root/deploy/$service"
test -x "$source_root/deploy/run-rosetta-production-signer.sh"
test -x "$source_root/deploy/provision-rosetta-signer-credential.sh"
test -f "$source_root/deploy/rosetta-signer.sudoers"
test -f "$staging_environment"
command -v docker >/dev/null
command -v getent >/dev/null
command -v groupadd >/dev/null
command -v useradd >/dev/null
command -v systemd-analyze >/dev/null
command -v visudo >/dev/null
visudo -cf "$source_root/deploy/rosetta-signer.sudoers"

test "$(grep -c '^ROSETTA_IMAGE=' "$staging_environment")" = "1"
image="$(awk -F= '$1 == "ROSETTA_IMAGE" {print substr($0, index($0, "=") + 1)}' "$staging_environment")"
printf '%s\n' "$image" | grep -Eq '^sha256:[0-9a-f]{64}$'
test "$(docker image inspect "$image" --format '{{.Id}}')" = "$image"

if systemctl is-active --quiet "$service" || systemctl is-enabled --quiet "$service"; then
  echo "refusing to replace an active or enabled production signer" >&2
  exit 1
fi

if signer_group_entry="$(getent group "$signer_user")"; then
  test "$(printf '%s\n' "$signer_group_entry" | cut -d: -f3)" = "$signer_gid"
else
  if getent group "$signer_gid" >/dev/null; then
    echo "signer GID is already assigned to another group" >&2
    exit 1
  fi
  groupadd --system --gid "$signer_gid" "$signer_user"
fi

if signer_user_entry="$(getent passwd "$signer_user")"; then
  test "$(printf '%s\n' "$signer_user_entry" | cut -d: -f3)" = "$signer_uid"
  test "$(printf '%s\n' "$signer_user_entry" | cut -d: -f4)" = "$signer_gid"
  test "$(printf '%s\n' "$signer_user_entry" | cut -d: -f6)" = "/nonexistent"
  test "$(printf '%s\n' "$signer_user_entry" | cut -d: -f7)" = "/usr/sbin/nologin"
else
  if getent passwd "$signer_uid" >/dev/null; then
    echo "signer UID is already assigned to another user" >&2
    exit 1
  fi
  useradd --system --uid "$signer_uid" --gid "$signer_gid" --no-create-home \
    --home-dir /nonexistent --shell /usr/sbin/nologin "$signer_user"
fi

docker run --rm --network none --read-only --user "$signer_uid:$signer_gid" \
  --cap-drop ALL --security-opt no-new-privileges \
  "$image" rosetta_signer.service --help >/dev/null

install -d -o root -g root -m 0755 /usr/local/libexec /etc/rosetta
install -o root -g root -m 0555 \
  "$source_root/deploy/run-rosetta-production-signer.sh" \
  /usr/local/libexec/rosetta-production-signer
install -o root -g root -m 0555 \
  "$source_root/deploy/provision-rosetta-signer-credential.sh" \
  /usr/local/libexec/provision-rosetta-signer-credential
install -o root -g root -m 0444 \
  "$source_root/deploy/$service" "/etc/systemd/system/$service"
install -o root -g root -m 0440 \
  "$source_root/deploy/rosetta-signer.sudoers" /etc/sudoers.d/93-rosetta-signer
image_temporary="$(mktemp /etc/rosetta/.signer-image.XXXXXX)"
printf '%s\n' "$image" >"$image_temporary"
install -o root -g root -m 0400 "$image_temporary" /etc/rosetta/signer-image
find "$image_temporary" -maxdepth 0 -type f -delete
image_temporary=

visudo -cf /etc/sudoers.d/93-rosetta-signer
systemd-analyze verify "/etc/systemd/system/$service"
systemctl daemon-reload
trap - EXIT
printf 'signer_install=pass\nsigner_enabled=no\npublic_writes=0\n'
