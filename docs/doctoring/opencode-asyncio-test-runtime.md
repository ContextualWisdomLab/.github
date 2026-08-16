# OpenCode coverage sandbox asyncio test runtime

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

The trusted OpenCode coverage image must execute repository tests that use
`pytest.mark.asyncio`. The pinned review toolchain therefore includes
`pytest-asyncio==1.4.0` and the Python 3.12 audit runtime's
`typing-extensions==4.16.0`. `scripts/ci/ensure_opencode_asyncio_toolchain.sh`
imports `pytest_asyncio` alongside `coverage`, `interrogate`, `pytest`, and
`pytest_cov`. The hashed `opencode-review-dispatch.yml` review-agent blob is
not rewritten to carry that import.

A missing plugin is a coverage-evidence failure. It is not permission to skip
async tests and still claim 100% execution of the repository suite.

The helper is not documentation. After the quality job installs the hash lock,
`trusted-uv-materializer-quality-ci.yml` executes the helper and the contract
suite collects a marked coroutine the same way a downstream buyer suite does.
pytest-asyncio registers through setuptools entry points, so installing the
pin is what makes `pytest.mark.asyncio` collect (Krekel et al., 2026;
Tvrtković, 2026). Keep that execution on the quality path instead of editing
the independent review-agent dispatch blob.

## Why the pin is required

PEP 492 defines native coroutines as first-class Python syntax (Selivanov,
2015). pytest does not run those tests unless an asyncio plugin is installed
in the same isolated image that records coverage. NIST SP 800-218 PW.4.1
requires third-party software to come from expected, trusted sources with
integrity verification (Souppaya et al., 2022). ISO/IEC 25010 treats
functional completeness and testability as product quality characteristics;
an unread helper does not satisfy either (International Organization for
Standardization, 2023). The hash-pinned lock is that source; an untrusted
head cannot replace or omit the plugin.

## Rollback

Rollback requires an independently reviewed change that still executes marked
asyncio tests inside the same isolated coverage image. Removing
`pytest-asyncio` without a replacement plugin reintroduces silent skips.

## Next action

After this lands on protected `main`, rerun coverage on an affected async
consumer such as `ContextualWisdomLab/pg-erd-cloud` and keep the issue open
until that consumer's marked coroutine suite collects under the merged lock.

## References

International Organization for Standardization. (2023). *Systems and software
engineering — Systems and software Quality Requirements and Evaluation
(SQuaRE) — Product quality model* (ISO/IEC 25010:2023).
https://www.iso.org/standard/78176.html

Krekel, H., & pytest-dev team. (2026). *pytest documentation*. pytest-dev.
https://docs.pytest.org/en/stable/

Selivanov, Y. (2015). *Coroutines with async and await syntax* (PEP 492).
Python Software Foundation. https://peps.python.org/pep-0492/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development
Framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

Tvrtković, T. (2026). *pytest-asyncio 1.4.0*. pytest-dev.
https://pypi.org/project/pytest-asyncio/1.4.0/
