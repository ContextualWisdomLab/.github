#!/usr/bin/env bash
# Fail closed unless the reviewed LLVM 19 coverage tools are bound.
set -euo pipefail

LLVM_COV_PATH="${LLVM_COV_PATH:-/usr/bin/llvm-cov-19}"
LLVM_PROFDATA_PATH="${LLVM_PROFDATA_PATH:-/usr/bin/llvm-profdata-19}"

if [ "${LLVM_COV:-}" != "$LLVM_COV_PATH" ] ||
  [ "${LLVM_PROFDATA:-}" != "$LLVM_PROFDATA_PATH" ] ||
  ! test -x "${LLVM_COV:-}" ||
  ! test -x "${LLVM_PROFDATA:-}"; then
  printf 'Rust coverage runtime did not preserve reviewed LLVM 19 tool paths (%s, %s).\n' \
    "$LLVM_COV_PATH" "$LLVM_PROFDATA_PATH" >&2
  exit 1
fi
