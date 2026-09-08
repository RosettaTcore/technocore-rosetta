#!/bin/sh
set -eu

UV=${UV:-uv}
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

cp requirements.lock "$tmp_dir/requirements.lock"
cp requirements-dev.lock "$tmp_dir/requirements-dev.lock"
cp adapters/official_mcp/requirements.lock "$tmp_dir/official-mcp-requirements.lock"

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

"$UV" --quiet pip compile vendor/technocore-chat-v0.13.0/mcp/pyproject.toml \
  --universal \
  --python-version 3.12 \
  --generate-hashes \
  --no-emit-index-url \
  --constraint adapters/official_mcp/upstream.constraints \
  --custom-compile-command tools/lock_requirements.sh \
  --output-file "$tmp_dir/official-mcp-requirements.lock"

cmp requirements.lock "$tmp_dir/requirements.lock"
cmp requirements-dev.lock "$tmp_dir/requirements-dev.lock"
cmp adapters/official_mcp/requirements.lock "$tmp_dir/official-mcp-requirements.lock"
