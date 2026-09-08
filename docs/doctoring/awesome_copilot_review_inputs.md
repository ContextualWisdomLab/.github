# awesome-copilot review input contract

## Requirement and source boundary

Every eligible central OpenCode, Noema and Strix model invocation must receive
the pinned engineering, test-gap and security methods. Ineligible/draft/skipped
runs do not count as reviews. Consumer-owned and vendor-hosted bots outside these
three central engines are not yet verified by this change.

Source pin: `github/awesome-copilot@3a19ac80c2c21f4088417c121cff0d06eadfbee8`.
The complete SKILL.md files, five required security references, exact per-file
SHA-256 values and original source paths are under
[the native skill](../../.agents/skills/cwl-awesome-copilot/SKILL.md) and its
[manifest](../../.agents/skills/cwl-awesome-copilot/references/manifest.json).
The adjacent LICENSE preserves the upstream MIT notice. No upstream script,
plugin, hook, package or MCP server is executed or installed.

## Actual consumer paths

| Consumer | Injection point | Trust and failure boundary |
|---|---|---|
| OpenCode | Trusted root reviewer prompts are copied, then common instructions appended to both agent prompt files in `opencode-review-dispatch.yml` | Isolated loader reads central checkout; failed assembly aborts preparation before model execution. Repair calls retain configured agent prompts. |
| Noema | `call_llm` system message | Imported central loader runs before constructing/sending the request; target title/diff remains user data. |
| Strix | `run_strix_once` custom instruction argument | Isolated loader runs by trusted absolute script path before scanner spawn; each retry uses this same path. |

Flow: pinned central files → digest/inventory verification → host contract plus
complete source text → existing agent input → existing verdict validation.
The `CWL_REVIEW_SKILLS` line identifies the source commit and assembled body
SHA-256. It proves supplied methods, not that a model correctly applied them.

## Reproduction and autoresearch measurement

Base central revision: `78a4937c` (2026-09-08 checkout).
RED commit: `439367aa`. The captured Noema request contained only a strict-JSON
system instruction; the new assertion failed (0/1 passing):

```sh
python -m pytest tests/test_noema_review_gate.py::test_call_llm_prompts_with_bounded_exact_changed_locations -q
```

Run from the repository with its dev tooling available. `pyproject.toml` already
sets the test import path. Use a project-local environment; never install into
a system interpreter. Tests inspect actual HTTP request bytes and execute the
OpenCode workflow shell segment; the Strix harness captures actual scanner argv.

```sh
python -m pytest tests/test_review_skill_bundle.py tests/test_noema_review_gate.py -q
bash scripts/ci/test_strix_quick_gate.sh
```

Corruption, removed source inventory and symbolic-link substitution must fail
before a model or scanner starts. A hostile cwd must not select a local module
or skill. The exact verified bytes are reused for assembly. No missing file
fallback is allowed. Shell command substitution strips terminal newlines, so a
host closing sentence follows the raw documents, preserving their bytes in all
consumer inputs and keeping the logged body digest meaningful.

Local verification on 2026-09-08: 8 bundle checks passed with 100% statement
and branch coverage of the loader; the combined bundle, Noema request and
OpenCode shell-syntax selection passed 15 checks after correcting a terminal
newline mismatch. The broader initial Noema/bundle run passed 121 checks with
that one now-fixed OpenCode byte-preservation failure. Loader docstring checking
passed. Workflow validation passed with `actionlint -shellcheck= -pyflakes=`;
the optional-helper invocation stalled and was stopped, so it is not a passed
shellcheck/pyflakes run. Production shell syntax is covered separately.

Context7 lookup returned a monthly-quota error. The pinned Strix CLI contract
was verified from its installed-distribution source by the integration reviewer;
DeepWiki and immutable upstream contents supported skill discovery.

Results are delivery and integrity evidence. They do not measure defect recall,
false positives, token savings, or deployed organization coverage. Those require
live exact-head review outputs and a declared evaluation set with failed runs
kept in the denominator. Do not claim improvement from a prompt assertion alone.

## Operating procedure and remaining rollout

1. Review changes to the wrapper, source inventory and upstream license. Update
   exact commit and every hash together only after inspecting the new text.
2. Run delivery, corruption, Noema, OpenCode shell and Strix invocation checks.
3. Complete independent review and exact-head required Checks; use normal merge.
4. Inspect a real eligible run of each engine from the released central revision,
   including an organization consumer. Match the source/body receipt and verify
   source-backed method application in its output. No synthetic test is live proof.
5. Inventory remaining vendor-hosted reviewers separately and connect their
   authoritative configuration; do not infer their adoption from central jobs.

Project #1 read on 2026-09-08 failed because the active CLI credential lacks
`read:project`. No roadmap state was changed or inferred. Existing PR #2012
is complementary and retains its full delta and independent lifecycle.

## APA 7th references

GitHub. (2026). *Awesome Copilot* [Agent skills, commit 3a19ac80c2c21f4088417c121cff0d06eadfbee8]. https://github.com/github/awesome-copilot/tree/3a19ac80c2c21f4088417c121cff0d06eadfbee8

GitHub. (2026). *Test gap audit* [Agent skill]. https://github.com/github/awesome-copilot/blob/3a19ac80c2c21f4088417c121cff0d06eadfbee8/skills/test-gap-audit/SKILL.md

GitHub. (2026). *Security review* [Agent skill]. https://github.com/github/awesome-copilot/blob/3a19ac80c2c21f4088417c121cff0d06eadfbee8/skills/security-review/SKILL.md
