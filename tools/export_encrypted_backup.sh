#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  echo "usage: $0 STATE_DIR EVIDENCE_DIR RECIPIENT_FILE OUTPUT_DIR" >&2
  exit 2
fi

state_dir=$1
evidence_dir=$2
recipient_file=$3
output_dir=$4

command -v age >/dev/null 2>&1 || { echo "age is required" >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo "tar is required" >&2; exit 1; }
test -f "$recipient_file"

umask 077
mkdir -p "$output_dir"
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM
snapshot="$work_dir/snapshot"
python3 tools/staging_backup.py \
  --state-dir "$state_dir" \
  --evidence-dir "$evidence_dir" \
  --output "$snapshot"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
output="$output_dir/rosetta-staging-$stamp.tar.age"
temporary="$output.tmp"
test ! -e "$output"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
  -C "$snapshot" -cf - . | age --encrypt --recipients-file "$recipient_file" --output "$temporary"
mv "$temporary" "$output"
sha256sum "$output" > "$output.sha256"
printf '%s\n' "$output"
