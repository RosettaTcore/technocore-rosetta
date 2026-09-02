#!/usr/bin/env bash
set -Eeuo pipefail

release_dir="${1:?release directory required}"
commit="${2:?commit required}"
previous_commit="${3:?previous commit required}"
release_root="/opt/rosetta/releases"
current_link="/opt/rosetta/current"
environment_file="/etc/rosetta/staging.env"
service="rosetta-observer.service"
activated=0
service_stopped=0

printf '%s\n' "$commit" | grep -Eq '^[0-9a-f]{40}$'
printf '%s\n' "$previous_commit" | grep -Eq '^[0-9a-f]{40}$'
test "$(id -u)" = "0"
test "$release_dir" = "$release_root/$commit"
test -d "$release_dir"
test "$(readlink -f "$current_link")" = "$release_root/$previous_commit"

previous_release="$(readlink -f "$current_link")"
previous_image="$(awk -F= '$1 == "ROSETTA_IMAGE" {print substr($0, index($0, "=") + 1)}' "$environment_file")"
test -n "$previous_image"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_directory="/var/backups/rosetta/pre-${commit}-${timestamp}"
install -d -o root -g root -m 0700 "$backup_directory"
install -o root -g root -m 0600 "$environment_file" "$backup_directory/staging.env"

rollback() {
  local result="$1"
  trap - ERR TERM INT
  set +e
  if test "$activated" = "1"; then
    systemctl stop "$service"
    ln -sfn "$previous_release" /opt/rosetta/.current.rollback
    mv -Tf /opt/rosetta/.current.rollback "$current_link"
    install -o root -g root -m 0600 "$backup_directory/staging.env" "$environment_file"
  fi
  if test "$service_stopped" = "1"; then
    systemctl start "$service"
  fi
  echo "upgrade failed; rollback attempted" >&2
  exit "$result"
}
trap 'rollback $?' ERR
trap 'rollback 143' TERM
trap 'rollback 130' INT

docker build --file "$release_dir/deploy/Dockerfile" --tag "rosetta/observer:${commit}" "$release_dir"
new_image="$(docker image inspect "rosetta/observer:${commit}" --format '{{.Id}}')"
case "$new_image" in
  sha256:[0-9a-f][0-9a-f]*) ;;
  *) echo "invalid built image ID" >&2; exit 1 ;;
esac

ROSETTA_IMAGE="$new_image" \
ROSETTA_CONFIG=/etc/rosetta/config.yaml \
ROSETTA_STATE_DIR=/var/lib/rosetta/state \
ROSETTA_EVIDENCE_DIR=/var/lib/rosetta/evidence \
docker compose --file "$release_dir/deploy/compose.staging.yaml" \
  config --format json >"$backup_directory/rendered-compose.json"

python3 - "$backup_directory/rendered-compose.json" "$new_image" <<'PY'
import json
import sys

document = json.load(open(sys.argv[1], encoding="utf-8"))
expected_image = sys.argv[2]
services = document["services"]
assert set(services) == {"observer", "egress-proxy"}
for service in services.values():
    assert service["image"] == expected_image
    assert service["read_only"] is True
    assert service["user"] == "65532:65532"
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert not service.get("ports")
    assert not service.get("privileged", False)
observer = services["observer"]
assert set(observer["networks"]) == {"observer-internal"}
assert "docker.sock" not in json.dumps(observer.get("volumes", []))
assert set(services["egress-proxy"]["networks"]) == {"observer-internal", "egress"}
PY

systemctl stop "$service"
service_stopped=1
sqlite_source="$backup_directory/sqlite-source"
install -d -o root -g root -m 0700 "$sqlite_source"
database_source="/var/lib/rosetta/state/observer.sqlite3"
test -f "$database_source"
test ! -L "$database_source"
install -o root -g root -m 0600 "$database_source" "$sqlite_source/observer.sqlite3"
for suffix in -wal -shm; do
  sidecar_source="${database_source}${suffix}"
  if test -e "$sidecar_source"; then
    test -f "$sidecar_source"
    test ! -L "$sidecar_source"
    install -o root -g root -m 0600 \
      "$sidecar_source" "$sqlite_source/observer.sqlite3${suffix}"
  fi
done
python3 - "$sqlite_source/observer.sqlite3" "$backup_directory/observer.sqlite3" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
try:
    source.backup(target)
    if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise RuntimeError("backup_integrity_failed")
finally:
    target.close()
    source.close()
PY
rm -rf "$sqlite_source"
tar -czf "$backup_directory/evidence.tar.gz" -C /var/lib/rosetta evidence
if test -f /var/lib/rosetta/state/health.json; then
  install -o root -g root -m 0600 /var/lib/rosetta/state/health.json "$backup_directory/health.json"
fi

environment_new="${environment_file}.new"
awk -v image="$new_image" '
  BEGIN { replaced = 0 }
  $0 ~ /^ROSETTA_IMAGE=/ { print "ROSETTA_IMAGE=" image; replaced = 1; next }
  { print }
  END { if (!replaced) print "ROSETTA_IMAGE=" image }
' "$environment_file" >"$environment_new"
chown root:root "$environment_new"
chmod 0600 "$environment_new"

activated=1
activation_time="$(date -u +%Y-%m-%dT%H:%M:%S%z)"
ln -sfn "$release_dir" /opt/rosetta/.current.new
mv -Tf /opt/rosetta/.current.new "$current_link"
mv -f "$environment_new" "$environment_file"
systemctl start "$service"

verified=0
for _attempt in $(seq 1 30); do
  if python3 "$release_dir/tools/verify_staging_live.py" \
      --expected-image "$new_image" \
      --expected-release-dir "$release_dir" \
      --not-before "$activation_time" \
      >"$backup_directory/live-verification.pending"; then
    mv "$backup_directory/live-verification.pending" \
      "$backup_directory/live-verification.json"
    verified=1
    break
  fi
  sleep 10
done
if test "$verified" != "1"; then
  rollback 1
fi

activated=0
service_stopped=0
trap - ERR TERM INT
cat "$backup_directory/live-verification.json"
printf 'upgrade=pass\ncommit=%s\nimage=%s\nprevious_commit=%s\nbackup=%s\n' \
  "$commit" "$new_image" "$previous_commit" "$backup_directory"
