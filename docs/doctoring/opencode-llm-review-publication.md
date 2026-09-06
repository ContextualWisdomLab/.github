# OpenCode LLM review publication

## Decision

OpenCode remains the review reasoner. Deterministic code may repair only the
serialization binding between an LLM-authored adversarial probe's structured
`path`/`line` and the SHA-256 of that exact immutable current-head source line.
It must not create or alter the hypothesis, counterexample, observed result,
outcome, finding, or verdict.

## Root cause

Production run `31310130263` invoked NVIDIA NIM and OpenCode free models, but
several substantive control blocks were discarded even when they carried an exact
source-line receipt because the prose omitted the duplicated `path:line` citation.
Noema is intentionally dispatched only after an exact-head OpenCode approval,
so this publication failure suppressed both review identities.

The model may also copy a trusted bare-digit sentinel into JSON as a number.
The normalizer accepted that equivalent `run_id`/`run_attempt` representation
but originally republished the raw number. The downstream approval gate requires
those identity fields to be strings and therefore rejected the normalized output.

## Safety boundary

Repair is attempted only when original model evidence already contains an
independent proof class and an observed result. The trusted current-head tree
must resolve the structured path and line. A path whose POSIX parts include
`..` is left unchanged (CWE-22; MITRE, n.d.). Changed-file, source-tree,
runtime-receipt, duplicate-probe, outcome, finding-location, coverage,
language, and publication gates still run afterward. Unsupported prose
continues to return `NO_CONCLUSION`.

After numeric identity equality is proven, publication uses the trusted expected
decimal strings rather than the untrusted representation. This changes JSON type,
not identity or verdict, and keeps the independent downstream gate strict.

## Verification

The regression suite proves canonical path/line repair only when an exact receipt
already exists, refusal to invent an observed result, rejection of missing or mismatched
receipts, and preservation of malformed and
unverifiable shapes, full normalizer behavior, branch coverage, docstrings,
compileability, and a clean worktree. An end-to-end regression now passes a
numeric model control through normalization and the real shell approval gate.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange
format* (RFC 8259). Internet Engineering Task Force.
https://doi.org/10.17487/RFC8259

MITRE. (n.d.). *CWE-22: Improper limitation of a pathname to a restricted
directory ('path traversal')*. Retrieved August 13, 2026, from
https://cwe.mitre.org/data/definitions/22.html

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5
