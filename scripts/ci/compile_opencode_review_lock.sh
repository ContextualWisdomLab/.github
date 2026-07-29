#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$repo_root"

uv pip compile \
  --upgrade \
  --generate-hashes \
  --python-version 3.14 \
  --python-platform x86_64-manylinux_2_28 \
  --custom-compile-command "./scripts/ci/compile_opencode_review_lock.sh" \
  --output-file requirements-opencode-review-ci-hashes.txt \
  requirements-opencode-review-ci.txt
