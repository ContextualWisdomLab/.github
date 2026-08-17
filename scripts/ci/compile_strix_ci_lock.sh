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

official_url="https://files.pythonhosted.org/packages/63/11/17a38cedceee7dc63d10f0728139a73576fe6f651a6108f3b5f70f2930c1/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl"
official_sha="ba0b6b13f13f41e45f3eb4dba515641d1bc71363ca6e758d0cd05c20ff56b6ea"
official="$(mktemp)"
trap 'rm -f "$official"' EXIT
curl --fail --silent --show-error --location --output "$official" "$official_url"
printf '%s  %s\n' "$official_sha" "$official" | sha256sum --check --strict

published_ref_file="vendor/strix/published-git-ref"
if [ ! -f "$published_ref_file" ] || [ -L "$published_ref_file" ]; then
  echo "vendor/strix/published-git-ref must be a regular file containing the published wheel commit" >&2
  exit 1
fi
ref="$(tr -d '[:space:]' < "$published_ref_file")"
if ! [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "vendor/strix/published-git-ref must be a 40-character git SHA" >&2
  exit 1
fi
wheel_url="https://raw.githubusercontent.com/ContextualWisdomLab/.github/${ref}/vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl"

python3 scripts/ci/rewrite_strix_agent_cryptography_bound.py \
  --input "$official" \
  --output vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl \
  --lock requirements-strix-ci-hashes.txt \
  --wheel-url "$wheel_url"
