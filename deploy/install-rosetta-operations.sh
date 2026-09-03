#!/usr/bin/env bash
set -Eeuo pipefail

source_root="${1:?checked-out release directory required}"
recipient_source="${2:?Age public recipient file required}"
healthchecks_source="${3:-}"
runtime_user="rosetta-runtime"
runtime_uid="65532"
runtime_gid="65532"

test "$(id -u)" = "0"
source_root="$(readlink -f -- "$source_root")"
test "$source_root" = "$(readlink -f -- /opt/rosetta/current)"
test "$(dirname -- "$source_root")" = "/opt/rosetta/releases"
basename -- "$source_root" | grep -Eq '^[0-9a-f]{40}$'
test -f "$source_root/tools/staging_status.py"
test -f "$source_root/tools/export_encrypted_backup.sh"
test -f "$source_root/tools/healthchecks_notify.py"
test -f "$recipient_source"
command -v age >/dev/null
command -v getent >/dev/null
command -v groupadd >/dev/null
command -v useradd >/dev/null
command -v runuser >/dev/null

if runtime_group_entry="$(getent group "$runtime_user")"; then
  test "$(printf '%s\n' "$runtime_group_entry" | cut -d: -f3)" = "$runtime_gid"
else
  if getent group "$runtime_gid" >/dev/null; then
    echo "runtime GID is already assigned to another group" >&2
    exit 1
  fi
  groupadd --system --gid "$runtime_gid" "$runtime_user"
fi

if runtime_user_entry="$(getent passwd "$runtime_user")"; then
  test "$(printf '%s\n' "$runtime_user_entry" | cut -d: -f3)" = "$runtime_uid"
  test "$(printf '%s\n' "$runtime_user_entry" | cut -d: -f4)" = "$runtime_gid"
  test "$(printf '%s\n' "$runtime_user_entry" | cut -d: -f6)" = "/nonexistent"
  test "$(printf '%s\n' "$runtime_user_entry" | cut -d: -f7)" = "/usr/sbin/nologin"
else
  if getent passwd "$runtime_uid" >/dev/null; then
    echo "runtime UID is already assigned to another user" >&2
    exit 1
  fi
  useradd --system --uid "$runtime_uid" --gid "$runtime_gid" --no-create-home \
    --home-dir /nonexistent --shell /usr/sbin/nologin "$runtime_user"
fi

runuser -u "$runtime_user" -- test -r "$source_root/tools/staging_status.py"
runuser -u "$runtime_user" -- test -x "$source_root/tools/export_encrypted_backup.sh"
runuser -u "$runtime_user" -- test -x "$source_root/tools/healthchecks_notify.py"

awk '
  /^age1[023456789acdefghjklmnpqrstuvwxyz]{58}$/ { count += 1; next }
  { bad = 1 }
  END { exit !(count == 1 && bad == 0) }
' "$recipient_source"

if test -n "$healthchecks_source"; then
  test -f "$healthchecks_source"
  python3 "$source_root/tools/healthchecks_notify.py" \
    --url-file "$healthchecks_source" --check-only
fi

install -d -o root -g root -m 0755 /etc/rosetta
install -d -o root -g root -m 0711 /var/backups/rosetta
install -d -o "$runtime_uid" -g "$runtime_gid" -m 0700 /var/backups/rosetta/encrypted
install -o root -g root -m 0644 "$recipient_source" /etc/rosetta/backup-recipient.txt
if test -n "$healthchecks_source"; then
  install -o root -g root -m 0400 "$healthchecks_source" /etc/rosetta/healthchecks.url
fi

for unit in \
  rosetta-healthcheck.service \
  rosetta-healthcheck.timer \
  rosetta-healthcheck-notify@.service \
  rosetta-backup.service \
  rosetta-backup.timer; do
  install -o root -g root -m 0444 \
    "$source_root/deploy/$unit" "/etc/systemd/system/$unit"
done

systemctl daemon-reload
systemctl start rosetta-healthcheck.service
systemctl start rosetta-backup.service
systemctl enable --now rosetta-healthcheck.timer rosetta-backup.timer

systemctl is-active rosetta-healthcheck.timer >/dev/null
systemctl is-active rosetta-backup.timer >/dev/null
systemctl --quiet is-failed rosetta-healthcheck.service && exit 1
systemctl --quiet is-failed rosetta-backup.service && exit 1
printf 'operations_install=pass\n'
