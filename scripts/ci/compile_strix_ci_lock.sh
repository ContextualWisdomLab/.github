#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$repo_root"

uv pip compile \
  --upgrade \
  --generate-hashes \
  --python-version 3.13 \
  --python-platform x86_64-manylinux_2_28 \
  --overrides requirements-strix-ci-overrides.txt \
  --custom-compile-command "./scripts/ci/compile_strix_ci_lock.sh" \
  --output-file requirements-strix-ci-hashes.txt \
  requirements-strix-ci.txt
