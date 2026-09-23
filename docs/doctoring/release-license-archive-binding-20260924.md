# Archive-bound license evidence candidate

Base: `a78b1c9f788d1a89fd7c8ab39d6347152b7e3065`.

## Reproduced defect

`/private/tmp/pr2347-archive-binding-repro.py` exercises the real capture, license
gate and install-lock binder. Its synthetic wheel contains academic-only terms,
while the separately supplied raw `licenses/LICENSE` contains the reviewed pytest
MIT text. The wheel and lock SHA-256 both equal
`659169bde33b6d27bf4cf927c01d69418cc97241bf728627448542f781c2771d`.
The base gate returns PASS and the binder writes that restrictive archive's hash.
This is a synthetic exploit, not a claim about any upstream package.
The raw receipt is `/private/tmp/pr2347-archive-binding-repro.md`.

## Candidate contract

- Raw capture retains `source.archive` for both wheel and crate inputs.
- One bounded byte read supplies both the archive digest and in-memory license
  extraction. No archive extraction or package execution occurs in this helper.
- Conventional license/notice names at every depth and declared custom
  `License-File` / Cargo `license-file` members are inspected. Missing declared
  members, duplicate normalized paths, traversal, archive links, invalid text
  and malformed archives refuse the capture.
- Separate raw license sidecars no longer supply the license decision.
- The gate reopens the retained archive and compares the source digest, full
  license text mapping and raw member SHA-256 mapping against the evidence.
- The install binder verifies those member hashes against the collected wheel
  and repeats the license decision on its actual member bytes before writing
  the pinned install lock. Forged permissive report fields cannot authorize
  an unrecognized restrictive body.

## Verification

The existing eight targeted test files plus
`tests/test_release_dependency_archive_binding.py` produce **296 passed,
1 skipped**, raw exit **0**, in 4.67 seconds. The skip is the existing GNU-find
Linux capture integration case; it is not a new skip.

The 16 added cases cover Python/Cargo sidecar forgery, evidence alteration,
archive replacement, archive absence, duplicate archive members, nested/raw-byte
hash preservation, custom wheel license paths and missing declarations, plus
two real shell install-binder refusals. A fake pip recorder establishes zero
install calls in both new install-negative cases. No real install or download
is used. Existing fixture archives now carry the same source-bound full texts
used by their license tests; one formerly permissive missing-archive capture
expectation changes to an explicit refusal.

`git diff --check` and shell syntax checking also return 0. This is a selected
regression result, not full-suite, coverage, hosted execution or release approval.

## Remaining boundaries

Raw shell capture still performs its existing extraction/native/hook collection
before assembly. Those scanners and separate metadata are not all reconstructed
from the retained snapshot by this patch. This candidate closes the demonstrated
license-sidecar binding defect; it does not certify every captured evidence field
or shell extraction as safe. The final install trusts the protected workflow
workspace to prevent mutation between binding and pip's hash-checked read.

Only the previously reviewed exact full texts are recognized. Unsupported texts,
MPL/BSL complex provenance, NumPy bundle questions, tools/sidecar pre-install
coverage and complete dependency closure remain held. No license exception or
legal conclusion follows from this candidate.
