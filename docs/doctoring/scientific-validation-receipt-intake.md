# Scientific-validation signer receipt intake

Issue #2315 closes the byte/file boundary between the unsigned scientific-validation verifier in #2300 and the future credentialed signer owned by #2299. `validate_receipt_manifest()` remains the semantic authority for the versioned manifest/predicate pair; the new signer-facing reader controls how those exact bytes enter that validator.

## Finding

The verifier already bounds the sealed scientific evidence document at 16 MiB, but the signer handoff is a separate trust boundary. A credentialed job that first used an ordinary path read on an attacker-controlled manifest or predicate could allocate or hash an arbitrarily large file before semantic validation rejected it. The signer must therefore bound the file read itself, not merely check the parsed object afterward.

## Decision

`scripts/ci/validate_scientific_validation_receipt.py` is the signer-facing intake primitive. It pins each receipt parent by walking directory components without following symlinks through the existing verifier owner primitive, opens the leaf once with `O_NOFOLLOW | O_NONBLOCK`, requires a regular inode by descriptor, reads at most 4 MiB + 1 byte, and passes those exact bytes to `validate_receipt_manifest()` without re-serialization.

The 4 MiB ceiling is deliberately independent from the 16 MiB scientific-evidence ceiling. One execution-artifact identity occupies roughly 67 bytes in compact JSON (64 hex characters plus quotes/comma overhead), so 4 MiB leaves room for more than 60,000 ordered execution identities before fixed receipt fields are considered. That is far above current scientific acceptance workloads while putting a deterministic upper bound on signer memory and parser work.

Manifest and predicate paths must be distinct. Missing leaves, symlinks, FIFOs/directories, symlinked parents, oversize files, and semantically invalid bounded pairs fail closed. `O_NONBLOCK` prevents a FIFO from stalling the signer before the regular-file test executes.

## Boundary

This reader does not authenticate the caller, GitHub run, artifact producer, workflow source, signature, or Sigstore bundle. It does not run caller code, request OIDC, hold attestation permissions, or make psychometric decisions. #2164 remains the reusable-workflow identity prerequisite; #2299 still owns live GitHub metadata verification, credentialed signing, bundle verification, and the immutable released/pinned contract. TEPP #637 remains blocked from commercial attestation authority until that owner path exists.

The owner quality gate covers the reader and its hostile-file contracts at 100% owned line/branch/docstring coverage. The tests exercise valid exact bytes, per-file size refusal before semantic parsing, missing/symlink/non-regular/FIFO/ancestor-symlink objects, identical paths, semantic failure after bounded intake, stable CLI exit behavior, executable dispatch, and immutable-sibling bootstrap refusal.
