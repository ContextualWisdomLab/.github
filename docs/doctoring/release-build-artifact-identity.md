# Immutable same-run build artifact intake

Base: 1916e95a8ee3b0dbd1c84011d88fc580700430e3. Previously the dependency
gate selected the caller's build artifact by name only. The gate now requires
`build_artifact_id` and `build_artifact_digest` as well as the expected name.
The producer must pass its upload result ID and `sha256:`-prefixed digest.
Missing values cannot fall back to name selection.

The shipped shell reuses the existing exact-artifact-sbom-attestation workflow's
same-repository/same-run metadata comparison and the same pinned download action.
It also checks the returned ID explicitly and requires canonical positive
decimal ID and sha256 digest input. Metadata identity, name, digest, run and
unexpired status must agree before download. An API error blocks consumption.
No second generic verifier, new token, or helper revision is introduced.

The gate requests only the additional `actions: read` permission required by
the metadata API. The caller must grant it; a called workflow cannot elevate
the caller's token permissions. Existing name-only callers must provide both
new required inputs when adopting this revision. Repository-local inspection
finds no executable caller of this reusable workflow; external caller adoption
is not exhaustively verified. FMLS's trusted matrix aggregation remains unwired.

## Pinned download action contract, source inspection only

The actual pinned revision is
`actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c`.
Its action.yml lines42–46 declare `digest-mismatch: error` as the default;
this candidate explicitly selects error. Its src/download-artifact.ts
lines94–136 select immutable IDs from current-run artifacts, lines171–183 pass
the selected artifact's digest as expectedHash, and lines215–231 throw and fail
the action on mismatch. A single requested ID avoids the multi-ID partial-match
warning path. A single selected artifact uses the existing destination root.

Primary sources opened directly:
https://raw.githubusercontent.com/actions/download-artifact/3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c/action.yml
https://raw.githubusercontent.com/actions/download-artifact/3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c/src/download-artifact.ts

The pre-download API comparison is not an independent hash of downloaded
bytes. Byte verification relies on this pinned action's implementation; its
download library/bundled execution and hosted transport are not executed in
the local tests. No warning-only revision is treated as equivalent. The API
record and downloaded record must refer to the same immutable ID; this does
not establish a release-source build proof or trusted gate success by itself.

## Scoped evidence and remaining holds

Tests execute the actual shell with inert gh output and installed jq. They
cover a valid record, same-name different ID, different run, absent/modified
digest, expiry, absent ID, invalid expected digest, different repository and
API failure. Rejected cases cannot reach the next-step marker. Static checks
bind download to ID and error-on-digest-mismatch; no real download occurs.
The first test run failed10 cases because its declaration extractor split at
child indentation; after anchoring the next input key correctly, the same
cases execute the shipped shell. This is a test harness repair, not acceptance
of the failed run.

Source/control equality, fixed helper00c655, full licence/Strix policy,
platform closure, same-run trusted success aggregation, resource bounds, and
final R5 HOLD remain unchanged. API rate exhaustion prevents a fresh broad
external ownership/Project census; no inference of absent external callers or
approval follows. CodeGraph indexed38 workflow files with0nodes/edges, so all
workflow call paths are inspected as source rather than graph completeness.
