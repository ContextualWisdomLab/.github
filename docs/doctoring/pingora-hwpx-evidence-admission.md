# Pingora edge policy admits HWPX evidence documents (#2116)

`scripts/ci/pingora_edge_policy.py` rejected the consumer's HWPX evidence
attachment before a merge verdict. `BINARY_DOCUMENT_MAGIC` only knew
`.pdf`/`.png`, and `_is_binary_documentation_asset` only admitted a
`doc`/`docs`/`documentation` directory, so the ZIP-based `.hwpx` under
`evidence/` matched neither rule and fell through to the strict UTF-8
decode every other candidate gets.

Source baseline: `fb17ef556f94f673234aa557254ae52779e9a7b0`. Consumer
evidence: ContextualWisdomLab/late-life-anxiety-reanalysis#10, head
`a1cd5bc6783c6510dfcf937f523c733366e82213`, run `34700409497`, job
`103571044859`. Reported failure: "Pingora edge policy could not establish
complete evidence: Runtime policy candidate
evidence/reviewer_response_draft.hwpx is not valid UTF-8".

The repair adds `.hwpx` (`PK\x03\x04`) to `BINARY_DOCUMENT_MAGIC` and lets
`_is_binary_documentation_asset` also admit an `.hwpx` under an `evidence`
path segment, gated on a bounded HWPX container check: unprefixed ZIP,
exact EOCD record, unique members with `mimetype` first, a stored (not
deflated) `mimetype` entry exactly `application/hwp+zip`, and a non-empty,
unencrypted `Contents/content.hpf` manifest. Format evidence only -- no
document rendering or malware inspection. The runtime-path guard and the
Nginx-runtime-text fallback scan for disguised/malformed archives are
retained unchanged.

Test evidence (offline, this branch): RED (test-only apply) 3 failing / 19
passing in `tests/test_pingora_hwpx_evidence.py`; GREEN (full patch) 90
passing across that file plus `tests/test_pingora_edge_policy.py` and
`tests/test_pingora_edge_workflow_contract.py`. Branch coverage of the
touched module: 100% (388 statements, 174 branches, 0 missed).
`interrogate scripts/ci -q`: 100.0% docstrings. Full suite passes, no new skips or warnings.

Hosted acceptance still requires a newly loaded central source SHA to
re-run the consumer's exact head bootstrap; local tests prove the declared
classification and container logic, not a hosted admission outcome.

## Reference

Hancom. (n.d.). *한/글 문서 파일 형식: HWPX 포맷 구조 살펴보기*. https://tech.hancom.com/hwpxformat/
