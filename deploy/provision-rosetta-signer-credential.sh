#!/usr/bin/env bash
set -Eeuo pipefail

target=/etc/credstore.encrypted/rosetta.seed

test "$(id -u)" = "0"
command -v systemd-creds >/dev/null
command -v base64 >/dev/null
test ! -e "$target"
test ! -L "$target"
install -d -o root -g root -m 0700 /etc/credstore.encrypted
temporary="$(mktemp /etc/credstore.encrypted/.rosetta.seed.XXXXXX)"
cleanup() {
  find "$temporary" -maxdepth 0 -type f -delete 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Read a Base64 transport envelope only from stdin, decode it in memory and stream the raw seed
# directly into systemd-creds. Neither representation appears in argv, the environment, shell
# history or a persistent plaintext file on this host.
base64 --decode | systemd-creds encrypt --name=rosetta.seed - "$temporary"
test "$(systemd-creds decrypt --name=rosetta.seed "$temporary" - | wc -c)" = "32"
chown root:root "$temporary"
chmod 0600 "$temporary"
mv -T "$temporary" "$target"
test "$(stat -c '%u:%g:%a' "$target")" = "0:0:600"
trap - EXIT
printf 'signer_credential_provisioned=pass\n'
