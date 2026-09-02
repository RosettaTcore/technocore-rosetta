#!/usr/bin/env bash
set -Eeuo pipefail

source_root="${1:?checked-out release directory required}"
allowed_signers_source="${2:?allowed signers file required}"

test "$(id -u)" = "0"
test -f "$source_root/tools/release_package.py"
test -f "$source_root/deploy/rosetta-upgrade.service"
test -f "$source_root/deploy/rosetta-upgrade.sudoers"
test -f "$allowed_signers_source"
awk '
  /^[[:space:]]*($|#)/ { next }
  { count += 1; if ($1 != "rosetta-release" || $2 != "ssh-ed25519" || NF < 3) bad = 1 }
  END { exit !(count == 1 && bad == 0) }
' "$allowed_signers_source"

install -d -o root -g root -m 0755 /usr/local/libexec
install -d -o root -g root -m 0755 /etc/rosetta
install -d -o root -g root -m 0755 /var/lib/rosetta/upgrades
install -d -o rosetta -g rosetta -m 0700 /var/lib/rosetta/upgrades/incoming
install -d -o root -g root -m 0700 /var/lib/rosetta/upgrades/work
install -d -o root -g root -m 0700 /var/lib/rosetta/upgrades/processed

install -o root -g root -m 0555 \
  "$source_root/tools/release_package.py" /usr/local/libexec/rosetta-release-package
install -o root -g root -m 0444 \
  "$source_root/deploy/rosetta-upgrade.service" /etc/systemd/system/rosetta-upgrade.service
install -o root -g root -m 0444 \
  "$allowed_signers_source" /etc/rosetta/release-allowed-signers
install -o root -g root -m 0440 \
  "$source_root/deploy/rosetta-upgrade.sudoers" /etc/sudoers.d/92-rosetta-upgrade

visudo -cf /etc/sudoers.d/92-rosetta-upgrade
systemctl daemon-reload
systemctl disable rosetta-upgrade.service >/dev/null 2>&1 || true
printf 'upgrader_install=pass\n'
