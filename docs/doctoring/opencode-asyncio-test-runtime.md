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

## Why the pin is required

PEP 492 defines native coroutines as first-class Python syntax (Selivanov,
2015). pytest does not run those tests unless an asyncio plugin is installed
in the same isolated image that records coverage. NIST SP 800-218 PW.4.1
requires third-party software to come from expected, trusted sources with
integrity verification (Souppaya et al., 2022). The hash-pinned lock is that
source; an untrusted head cannot replace or omit the plugin.

## Rollback

Rollback requires an independently reviewed change that still executes marked
asyncio tests inside the same isolated coverage image. Removing
`pytest-asyncio` without a replacement plugin reintroduces silent skips.

## References

Selivanov, Y. (2015). *Coroutines with async and await syntax* (PEP 492).
Python Software Foundation. https://peps.python.org/pep-0492/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development
Framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
