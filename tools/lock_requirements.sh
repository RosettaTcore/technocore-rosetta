#!/bin/sh
set -eu

UV=${UV:-uv}

"$UV" --quiet pip compile requirements.in \
  --universal \
  --python-version 3.10 \
  --generate-hashes \
  --no-emit-index-url \
  --custom-compile-command tools/lock_requirements.sh \
  --output-file requirements.lock

"$UV" --quiet pip compile requirements-dev.in \
  --universal \
  --python-version 3.10 \
  --generate-hashes \
  --no-emit-index-url \
  --custom-compile-command tools/lock_requirements.sh \
  --output-file requirements-dev.lock
