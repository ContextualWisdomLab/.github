# awesome-copilot review input contract

## Requirement and source boundary

Every substantive central OpenCode, Noema and Strix review agent must receive
the pinned engineering, test-gap and security methods, including delegated reviewers. Ineligible/draft/skipped
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
| OpenCode | A verified read-only file is supplied through native global `instructions`; individual host prompts retain their original bytes | Configured and native delegated reviewers receive shared methods. Task delegation is enabled, including recursion; global read-only permissions remain enforced. Failed assembly aborts before model execution. |
| Noema | `call_llm` system message | Imported central loader runs before constructing/sending the request; target title/diff remains user data. |
| Strix | Native scan-mode registration through a trusted launcher | The sealed entrypoint selects its installed Python environment; the launcher verifies and registers the complete bundle before scanner startup, including retries and delegated agents. |

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

Strix representative success, corrupted-source rejection (zero scanner calls)
and a two-invocation fallback case passed with exact whole-argument equality.
The fallback is a local existing harness scenario, not permission to change
production `orchestrator/free` routing. Independent source review also confirmed
all eight upstream hashes and the original license.

The vendored upstream bytes intentionally retain four trailing-whitespace lines.
`.gitattributes` disables only end-of-line whitespace checks for the vendored
`references/*.md` files; the normal whole-PR `git diff --check` remains enabled.
Other whitespace checks and every first-party path keep their normal behavior.
Do not trim upstream bytes and silently invalidate source hashes.

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

The initial Project #1 CLI read on 2026-09-08 failed for missing `read:project`.
The authenticated browser subsequently showed the live roadmap. PR #2034 was
added and its `In Progress` status visibly verified there. Existing PR #2012
is complementary and retains its full delta and independent lifecycle.

Latest focused verification: 10 bundle tests passed with 100% statement/branch
coverage; 54 existing OpenCode agent contracts passed. Standard Strix entrypoints
also passed (including their preceding static checks):

```sh
STRIX_TEST_CASE_FILTER=success bash scripts/ci/test_strix_quick_gate.sh
STRIX_TEST_CASE_FILTER=tampered-review-skills bash scripts/ci/test_strix_quick_gate.sh
```

The full Python suite completed with 3,001 passed, one skipped and two failures.
Both failures detected the stale independent dispatch-workflow blob pin after the
prompt change. The pin now matches the inspected workflow bytes; both affected
contract files pass (31 passed, one skipped). This is a targeted repair result,
not a second whole-suite pass.

## Full-suite timeout fixture repair

The next full Python run at `28d89eb1` passed 3,011 tests, skipped one and failed
one existing sandbox timeout-output test. The same file passed 27 tests in
isolation. Its one-second deadline assumed the child had started printing;
furthermore, its stdout substring assertion matched the echoed command even when
the child produced no output. An isolated no-output timeout reproduced that false
positive. No production output-loss defect was established.

The test now supplies explicit timeout payloads to exercise the real sandbox
preparation and error-reporting path deterministically, asserting whole output
lines. A separate real subprocess check retains timeout enforcement without a
startup-output assumption. The repaired file passes 28 tests; production timeout
behavior is unchanged. This focused result does not claim another full-suite pass.

## Open Strix delegated-agent propagation defect

The installed `strix-agent==1.5.3` source shows that CLI instructions enter the
root task (`interface/cli.py:90`, `core/inputs.py:156`). However,
`tools/agents_graph/tools.py:408` permits `inherit_context=False` and line 485
then omits parent history. `core/execution.py:311` constructs the child without
the mandatory instructions; `core/inputs.py:285` builds child input from the
delegated task and optional history. Even inherited history is marked background
only at line 308. Shared target scope does not carry these instructions.

The original Strix CLI receipt proves root delivery only. The selected repair
uses the published `register_skill_dir` extension, rather than changing or
monkeypatching the upstream runtime. Every agent loads `scan_modes/<mode>`;
trusted shadows preserve original quick/standard/deep bytes and append the whole
verified bundle. The launcher rejects missing, mismatched or incompletely
rendered content before entering the unchanged CLI, and keeps the read-only
extension directory alive until that CLI returns. Each new process registers
the extension again, including when resuming a scan.

The standalone probe ran against the actual installed pinned 1.5.3 distribution:
all three modes, both parent-history settings, root, child, grandchild and
resumed-child construction received the entire verified bundle. Original mode
bytes and prefix hashes remained intact. Only model-loop startup was replaced;
the graph tool and agent factories were real. The probe made no model call.
The launcher unit tests passed 10 checks with 100% statement/branch coverage.

The shared gate invokes this launcher using the sealed executable's
Python interpreter; registration in an unrelated process would have no effect.
Validation resolves the interpreter to check its target, but execution retains
the original virtual-environment path. A real installed-package check reproduced
`PackageNotFoundError` when execution used the resolved base Python instead;
the original path retains the pinned Strix installation. The final 12-case
integration group passed, covering this symlink-path regression, success, bundle
tampering, interpreter boundaries, executable seals, retries and fallback. The
actual installed 1.5.3 launcher also completed `--help` after native registration. The previous full
gate harness was explicitly cancelled (exit 143) after its root-only delivery
and task-denial expectations were superseded. It is not reported as passing. The hosted post-install probe
is configured but not yet observed. Local integration is verified; required
hosted checks remain pending. No new upstream runtime release is necessary
for this supported extension; protected central release and live adoption remain
required. Native API reuse supersedes the earlier upstream-code-change proposal.

OpenCode delegation correction: the existing configuration's blanket task denial
is an implementation restriction, not an owner-approved prohibition. On
2026-09-08 the owner explicitly rejected treating delegation as forbidden.
The original goal requires useful agent delegation with complete skill delivery;
retaining denial is not a solution to propagation. The revised configuration enables delegation, including general, explore and
recursive review, while preserving read-only permissions. Native global
`instructions` supplies one verified file to every substantive reviewer without
duplicating it in individual prompts. Title/summary/compaction operations remain distinct auxiliary work.
This correction supersedes the earlier claim that a disabled delegation path
establishes satisfactory coverage.

## Vendor-hosted review boundary

At PR #2034 head `48ae1b1513fe40808f55b9e6ce2d6cf149c281c8`, CodeRabbit
reported review in progress. Devin reported success but explicitly skipped the
full review because its trial expired and no credits remained; that status is
not review evidence. No Copilot review execution was verified. Its standard base-branch entrypoint
`.github/copilot-instructions.md` now directs the same review methods and remains
below the documented 4,000-character instruction limit.

CodeRabbit and Devin document root `AGENTS.md`/`CLAUDE.md` instruction support.
Those existing entrypoints now explicitly require the same trusted-base wrapper
and manifest sources. This is an instruction contract pending merge and observed
consumption, not a claim that vendor configuration or model behavior is verified.
No vendor credentials, credit purchases or alternate model routes were added.

## APA 7th references

GitHub. (2026). *Awesome Copilot* [Agent skills, commit 3a19ac80c2c21f4088417c121cff0d06eadfbee8]. https://github.com/github/awesome-copilot/tree/3a19ac80c2c21f4088417c121cff0d06eadfbee8

GitHub. (2026). *Test gap audit* [Agent skill]. https://github.com/github/awesome-copilot/blob/3a19ac80c2c21f4088417c121cff0d06eadfbee8/skills/test-gap-audit/SKILL.md

GitHub. (2026). *Security review* [Agent skill]. https://github.com/github/awesome-copilot/blob/3a19ac80c2c21f4088417c121cff0d06eadfbee8/skills/security-review/SKILL.md

CodeRabbit. (n.d.). *Code guidelines*. https://docs.coderabbit.ai/knowledge-base/code-guidelines

Cognition. (n.d.). *Devin Review*. https://docs.devin.ai/work-with-devin/devin-review

GitHub. (n.d.). *Using GitHub Copilot code review*. https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review

Hosted run `34187470404` at `a17a249c` passed all 125 bundle/Noema tests
with 100% loader statement/branch coverage, then failed two obsolete harness
assertions requiring OpenCode delegation denial. The harness now requires
allowed delegation; the policy correction is preserved. This failed historical
run is not evidence that the final head passed hosted verification.

## Owner-requested current skill propagation

On 2026-09-08 the owner additionally required every skill currently used in
this implementation to reach the review agents. The fixed session inventory
contains ten distinct SKILL.md sources: autoresearch, humanize-korean (im-not-ai
is the same source), adr-author, ponytail, protected-merge-verification, and five
Superpowers methods (using-superpowers, writing-plans, systematic-debugging,
test-driven-development, verification-before-completion). Required textual
references, agent instructions and source license notices accompany them.
The existing awesome-copilot inventory remains intact.

Sources are pinned to the exact applied versions, including ADR Author's
historical commit rather than a newer mismatched upstream file. The protected
merge method is an explicitly requested user-local source snapshot; it is not
attributed to an upstream project or assigned an invented license. The session
manifest identifies each source and SHA-256 without publishing workstation paths
or unrelated private memory.

One shared loader verifies both fixed inventories and appends every source's
full text to the existing host contract. OpenCode global instructions, Noema's
system message and Strix's native delegated/resumed scan modes therefore use
the same complete bundle. No additional engine-specific delivery mechanism is
needed. The combined body digest covers the expanded content. Skills remain
bounded by the existing capabilities, output schemas, evidence requirements and
free routing; vendor-specific tool names and workflow examples cannot authorize
history resets, paid calls, secret disclosure or approval bypass. Delegation is
still allowed. Text delivery does not assert execution of optional skill scripts.

Verification must cover full source-byte delivery, missing and altered session
assets, symlink substitutions and exact inventory rejection; then repeat the
actual installed Strix hierarchy/resume probe with the expanded bundle. Earlier
61b5bac0 results establish the previous bundle only, not this expanded inventory.


Additional pinned sources (APA 7th):

- GitHub. (n.d.). *Autoresearch* [Agent skill, commit 3a19ac80c2c21f4088417c121cff0d06eadfbee8]. https://github.com/github/awesome-copilot/blob/3a19ac80c2c21f4088417c121cff0d06eadfbee8/skills/autoresearch/SKILL.md
- epoko77-ai. (n.d.). *Im not AI* [Agent skills, commit 31a66d165a9cc6c26c4c1246553f95d0468d27fb]. https://github.com/epoko77-ai/im-not-ai/tree/31a66d165a9cc6c26c4c1246553f95d0468d27fb
- Microsoft. (n.d.). *ADR author* [Agent skill, commit a4769a029bccc1720fb8d5ac50950dfea5e4d917]. https://github.com/microsoft/hve-core/tree/a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author
- Gebert, D. (n.d.). *Ponytail* [Agent skill, commit 356918eba965ee1eac64bd3a7f0dd02108350de5]. https://github.com/DietrichGebert/ponytail/tree/356918eba965ee1eac64bd3a7f0dd02108350de5
- Vincent, J. (n.d.). *Superpowers* (Version 6.3.0) [Agent skills, commit b36e0829c6d0140e93cfef2ca599b1b07d4a7797]. https://github.com/obra/superpowers/tree/b36e0829c6d0140e93cfef2ca599b1b07d4a7797


Expanded-bundle validation: 132 bundle/Noema tests passed with 100% loader
statement/branch coverage (38 statements, 18 branches); 54 OpenCode contract
tests passed. Actual installed Strix 1.5.3 delivered all 531,933 bytes to root,
child, grandchild and resumed agents in every mode and both inheritance settings.
The combined body SHA-256 is
`b8f47227cfe7e3a07b9f9db6e83b89461ded684a6417d52ea7ef66a342d097b9`.
These are local delivery checks, not hosted model application or release proof.
The test scanner compares complete files rather than passing the larger text
as one command argument; production already uses native skill files. No source
text is truncated to satisfy operating-system argument limits. One original
trailing-space line in the Korean rewriting reference is preserved by a
file-specific whitespace attribute, keeping its pinned digest unchanged.

The expanded bundle also passed the standard filtered Strix `success` and
`tampered-review-skills` harness commands (both exit 0), plus all ten native
launcher unit tests. These complete the local integration checks for this
source expansion; protected merge and hosted use remain pending.

## Review follow-up on the expanded inventory

Hosted runtime-quality run [34191903107](https://github.com/ContextualWisdomLab/.github/actions/runs/34191903107)
passed at `709dc916e25fe3c3ac38cf08325248f472e08b09`, including pinned skill
delivery. This establishes that candidate's CI result, not protected-main
adoption or a later revision's checks. The default-timeout `slow-timeout`
fixture also exited 0 at that revision. An older full harness at `61b5bac0`
used a 3-second override and reported only two recorded scanner starts instead
of three. Its deadline includes interpreter and bundle preparation before the
scanner records a call; that shortened run is not a clean full-suite pass.

CodeRabbit reviewed `709dc916` and identified one active prompt contradiction
and several contradictions in imported source examples. Keep the immutable
source snapshots and their digests unchanged. The host's explicit conflict
rules govern their use; this does not assert that upstream documents were fixed.

| Review comments | Disposition and applicable boundary |
| --- | --- |
| 3954856207 | Remove stale delegation-denial prose from the supplied reviewer prompts and generated workspace instructions; test consistency with allowed native and recursive delegation. |
| 3954856073, 3954856084, 3954856092, 3954856095, 3954856104 | ADR source examples disagree on autonomy, lineage, disclaimer/adoption state and required rubric fields. No authoring state machine or validator is installed here. The host now explicitly assesses the repository's actual schema and template without inventing additional requirements from those examples. |
| 3954856112 | Autoresearch's reset example cannot authorize mutation by a read-only reviewer. The host explicitly requires attribution to the actual experiment revision and forbids staging/resetting/deleting user work. |
| 3954856119, 3954856149, 3954856156, 3954856174 | Chunk thresholds, declared pattern counts, optional script names and file-agent argument examples disagree upstream. This bundle reads the full sources, deploys none of those scripts/file workflows and claims no metric execution. The host explicitly prevents these examples from limiting the rules reviewed. |
| 3954856161 | The host explicitly preserves actors, modality, claims and logical relations, overriding sentence-insertion and fixed-percentage deletion prescriptions. |
| 3954856170 | The web cache is an imported proposed service specification, not a service deployed or called by this integration. Do not claim a cache correction or deployment. |
| 3954856182 | The wait snippet is not executable repository code; host guidance now explicitly distinguishes failure sentinels from valid falsy results before recommending an implementation. |
| 3954856187, 3954856199 | Adding fence languages would change the expressly requested source bytes. Preserve the upstream snapshots; these formatting observations do not establish a runtime defect. |

The accompanying test-file encoding observation is corrected with explicit
UTF-8. Review dispositions do not dismiss the underlying upstream inconsistencies
or substitute for current-head CI, resolved review threads and protected merge.
