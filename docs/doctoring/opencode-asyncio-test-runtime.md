# OpenCode coverage sandbox asyncio test runtime

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

The trusted OpenCode coverage image must execute repository tests that use
`pytest.mark.asyncio`. The pinned review toolchain therefore includes
`pytest-asyncio==1.4.0` and the Python 3.12 audit runtime's
`typing-extensions==4.16.0`. The coverage image installs that lock with
`--require-hashes --only-binary=:all:`. pytest then loads the installed
plugin, so marked coroutine tests run instead of failing collection.

`scripts/ci/ensure_opencode_asyncio_toolchain.sh` is the isolated
`python3 -I` import wrapper. After the quality job installs the hash lock,
`trusted-uv-materializer-quality-ci.yml` executes that helper. The same
suite also runs a marked coroutine the way a downstream buyer suite does.
The hashed `opencode-review-dispatch.yml` review-agent blob keeps its
existing smoke import because `tests/test_opencode_agent_contract.py` pins
that line. Do not rewrite the blob to carry `pytest_asyncio`.

Root `AGENTS.md`, `ARCHITECTURE.md`, and `CLAUDE.md` stay with
ContextualWisdomLab/.github#896. Record the asyncio boundary here and in
`CHANGELOG.md` instead of colliding with that control-plane documentation
graph.

A missing plugin is a coverage-evidence failure. It is not permission to skip
async tests and still claim 100% execution of the repository suite.

## Why the pin is required

PEP 492 defines native coroutines as first-class Python syntax (Selivanov,
2015). pytest does not run those tests unless an asyncio plugin is installed
in the same isolated image that records coverage. NIST SP 800-218 PW.4.1
requires third-party software to come from expected, trusted sources with
integrity verification (Souppaya et al., 2022). The hash-pinned lock is that
source; an untrusted head cannot replace or omit the plugin. pytest-asyncio
1.4.0 is the current stable release with Python 3.10–3.14 classifiers
(Seifert & pytest-asyncio contributors, 2026).

## Rollback

Rollback requires an independently reviewed change that still executes marked
asyncio tests inside the same isolated coverage image. Removing
`pytest-asyncio` without a replacement plugin reintroduces silent skips.

## References

Seifert, T., & pytest-asyncio contributors. (2026). *pytest-asyncio 1.4.0*
[Computer software]. Python Package Index.
https://pypi.org/project/pytest-asyncio/1.4.0/

Selivanov, Y. (2015). *Coroutines with async and await syntax* (PEP 492).
Python Software Foundation. https://peps.python.org/pep-0492/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development
Framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
