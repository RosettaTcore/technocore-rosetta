#!/bin/sh
set -eu

UV=${UV:-uv}
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

cp requirements.lock "$tmp_dir/requirements.lock"
cp requirements-dev.lock "$tmp_dir/requirements-dev.lock"

"$UV" --quiet pip compile requirements.in \
  --universal \
  --python-version 3.10 \
  --generate-hashes \
  --no-emit-index-url \
  --custom-compile-command tools/lock_requirements.sh \
  --output-file "$tmp_dir/requirements.lock"

"$UV" --quiet pip compile requirements-dev.in \
  --universal \
  --python-version 3.10 \
  --generate-hashes \
  --no-emit-index-url \
  --custom-compile-command tools/lock_requirements.sh \
  --output-file "$tmp_dir/requirements-dev.lock"

cmp requirements.lock "$tmp_dir/requirements.lock"
cmp requirements-dev.lock "$tmp_dir/requirements-dev.lock"
