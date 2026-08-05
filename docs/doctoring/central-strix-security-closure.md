# Central Strix security dependency closure

## Decision

The central Strix security lane uses one reviewed, generated, hash-locked Python dependency closure. The direct input now fixes the security-sensitive packages at:

- `aiohttp==3.14.3`;
- `cryptography==50.0.0`;
- `strix-agent==1.0.4` and the existing reviewed direct dependencies.

The generated lock resolves the compatible transitive `pyOpenSSL==26.4.0` release. The complete lock is replaced as one artifact rather than editing individual hashes or transitive versions by hand.

## Triggering evidence

The central Python Security job on August 5, 2026 failed on the existing protected base because:

- `aiohttp==3.14.1` was within ranges affected by three 2026 advisories covering a malformed chunked-response parser out-of-bounds read, unnegotiated WebSocket compression acceptance, and request smuggling through WebSocket upgrade handling;
- `cryptography==49.0.0` was within the range reported by `PYSEC-2026-3552` for a PKCS7 decryption timing-oracle issue;
- the published fixed floors were `aiohttp>=3.14.2` for the affected aiohttp advisories and `cryptography>=50.0.0` for the cryptography advisory.

The branch first added an executable regression contract. Exact head `768cc63e58ff6b2c3900585258d5e873c3755e1d` failed before dependency replacement because the direct input still selected `aiohttp==3.14.1`. This proves the test detects the vulnerable baseline rather than merely documenting the final state.

## Trust boundary

- The direct input and generated hash lock are both reviewed source artifacts.
- CI installs with `python -m pip install --require-hashes` and therefore cannot silently resolve an unhashed replacement.
- The exact-head closure workflow receives no repository-write permission, secret, OIDC token, or reviewer credential.
- The workflow checks out the immutable pull-request head SHA and verifies both the declared security floor and a real hash-locked installation.
- No advisory is ignored, suppressed, or reclassified.
- OpenCode, Noema, Strix, NVIDIA NIM, and reviewer credential names and scopes are unchanged.

## Scope separation

This security closure is deliberately separated from the generic coverage/native-fuzz boundary in pull request #763. A dependency lifecycle update and a coverage materialization policy are independently reviewable changes and may be rejected or rolled back separately.

## Verification and rollback

Merge requires the exact current head to pass:

- the dedicated Strix closure contract and hash-locked installation;
- Python Security and dependency review;
- OSV, CodeQL, Semgrep, Secret Scan, SBOM, and Scorecard;
- repository tests and exact-head independent review.

Rollback is prohibited while the prior versions remain advisory-affected. A future replacement must provide a newly generated hash lock, a passing advisory scan, an updated regression contract if the security floor changes, and a new doctoring entry.

## APA 7 references

GitHub. (2026a). *AIOHTTP: HTTP request smuggling via WebSocket upgrade* [Security advisory, GHSA-mfx4-hv73-q22v]. GitHub Advisory Database. https://github.com/advisories/GHSA-mfx4-hv73-q22v

GitHub. (2026b). *AIOHTTP: Out-of-bounds heap read in C HTTP response parser error path* [Security advisory, GHSA-cq5v-8q36-5273]. GitHub Advisory Database. https://github.com/advisories/GHSA-cq5v-8q36-5273

GitHub. (2026c). *AIOHTTP: WebSocket client accepts compressed frames without negotiated permessage-deflate* [Security advisory, GHSA-mq44-7p77-q5h7]. GitHub Advisory Database. https://github.com/advisories/GHSA-mq44-7p77-q5h7

Open Source Vulnerabilities. (2026). *PYSEC-2026-3552* [Security advisory]. https://osv.dev/vulnerability/PYSEC-2026-3552

Python Packaging Authority. (2026). *Python Packaging Advisory Database* [Data set]. GitHub. https://github.com/pypa/advisory-database

Python Packaging Authority. (2026). *pip-audit* [Computer software]. GitHub. https://github.com/pypa/pip-audit
