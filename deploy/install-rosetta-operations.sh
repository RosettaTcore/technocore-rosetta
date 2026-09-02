#!/usr/bin/env bash
set -Eeuo pipefail

source_root="${1:?checked-out release directory required}"
recipient_source="${2:?Age public recipient file required}"
healthchecks_source="${3:-}"

test "$(id -u)" = "0"
test "$source_root" = "$(readlink -f /opt/rosetta/current)"
test -f "$source_root/tools/staging_status.py"
test -f "$source_root/tools/export_encrypted_backup.sh"
test -f "$source_root/tools/healthchecks_notify.py"
test -f "$recipient_source"
command -v age >/dev/null

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
install -d -o 65532 -g 65532 -m 0700 /var/backups/rosetta/encrypted
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
