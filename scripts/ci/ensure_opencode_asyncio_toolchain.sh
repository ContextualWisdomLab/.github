#!/usr/bin/env bash
# Fail closed unless the reviewed coverage toolchain can import pytest-asyncio.
set -euo pipefail

python3 -I -c 'import coverage, interrogate, pytest, pytest_asyncio, pytest_cov; print("trusted offline Python test toolchain imports passed")'
