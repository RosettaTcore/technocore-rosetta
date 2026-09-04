#!/usr/bin/env bash
set -Eeuo pipefail

signer_uid=65531
signer_gid=65531
image_file=/etc/rosetta/signer-image
runtime_directory=/run/rosetta-signer
state_directory=/var/lib/rosetta-signer
seed_file="$runtime_directory/rosetta.seed"
socket_file="$runtime_directory/signer.sock"
container_name=rosetta-production-signer

test "$(id -u)" = "0"
test -n "${CREDENTIALS_DIRECTORY:-}"
credential="$CREDENTIALS_DIRECTORY/rosetta.seed"
test -f "$credential"
test ! -L "$credential"
test "$(stat -c '%u' "$credential")" = "0"
test "$((8#$(stat -c '%a' "$credential") & 8#077))" = "0"
test "$(wc -c <"$credential")" = "32"

test -f "$image_file"
test ! -L "$image_file"
test "$(stat -c '%u' "$image_file")" = "0"
test "$((8#$(stat -c '%a' "$image_file") & 8#022))" = "0"
mapfile -t image_lines <"$image_file"
test "${#image_lines[@]}" = "1"
image="${image_lines[0]}"
printf '%s\n' "$image" | grep -Eq '^sha256:[0-9a-f]{64}$'
test "$(docker image inspect "$image" --format '{{.Id}}')" = "$image"

if docker container inspect "$container_name" >/dev/null 2>&1; then
  echo "refusing to replace an existing production signer container" >&2
  exit 1
fi

install -d -o "$signer_uid" -g "$signer_gid" -m 0750 "$runtime_directory"
install -d -o "$signer_uid" -g "$signer_gid" -m 0700 "$state_directory"
install -o "$signer_uid" -g "$signer_gid" -m 0400 "$credential" "$seed_file"
test "$(stat -c '%u:%g:%a:%s' "$seed_file")" = "$signer_uid:$signer_gid:400:32"

container_started=0
docker_pid=
cleanup() {
  local result=$?
  trap - EXIT
  set +e
  if test "$container_started" = "1"; then
    docker stop --time 10 "$container_name" >/dev/null 2>&1
    test -n "$docker_pid" && wait "$docker_pid" >/dev/null 2>&1
  fi
  find "$seed_file" -maxdepth 0 -type f -delete 2>/dev/null
  exit "$result"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

docker run --rm \
  --name "$container_name" \
  --network none \
  --read-only \
  --user "$signer_uid:$signer_gid" \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 64 \
  --memory 128m \
  --cpus 0.25 \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --mount "type=bind,src=$runtime_directory,dst=/run/rosetta-signer" \
  --mount "type=bind,src=$state_directory,dst=/var/lib/rosetta-signer" \
  "$image" \
  rosetta_signer.service \
  --socket /run/rosetta-signer/signer.sock \
  --state /var/lib/rosetta-signer/nonce.sqlite3 \
  --seed-file /run/rosetta-signer/rosetta.seed &
docker_pid=$!
container_started=1

socket_ready=0
for _attempt in $(seq 1 100); do
  if test -S "$socket_file"; then
    chmod 0660 "$socket_file"
    test "$(stat -c '%u:%g:%a' "$socket_file")" = "$signer_uid:$signer_gid:660"
    socket_ready=1
    break
  fi
  if ! kill -0 "$docker_pid" 2>/dev/null; then
    set +e
    wait "$docker_pid"
    result=$?
    set -e
    test "$result" != "0" || result=1
    exit "$result"
  fi
  sleep 0.1
done
test "$socket_ready" = "1"

set +e
wait "$docker_pid"
result=$?
set -e
container_started=0
test "$result" != "0" || result=1
exit "$result"
