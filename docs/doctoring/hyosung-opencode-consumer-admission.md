# Hyosung OpenCode intake candidate

Status: Proposed. Base: fb17ef556f94f673234aa557254ae52779e9a7b0.

MLLO console and its design owner cannot use the canonical OpenCode intake:
the required caller and dispatch receiver reject their organization even when
the exact repository is configured in the dispatch allowlist. Four extracted
intake tests failed on the base. This candidate admits only
`HYOSUNG-ITX-AI-Business-Department/llm-gateway-console` and
`HYOSUNG-ITX-AI-Business-Department/llm-gateway-console-design`.

The existing dispatch actor and sender must still match the same configured
identity. An empty or missing live target allowlist remains denied. Live PR
base/head, visibility and state checks remain authoritative. OIDC exchange,
metadata access, private-target ZDR, review publication identity and separate
status permissions are unchanged. The canonical workflow continues to use its
existing CO free route; no paid route or consumer workflow copy is introduced.

## Remaining deployment prerequisites

The JSON target inventory is a proposed configuration delta, not evidence that
the live repository variable changed. After protected owner review and merge,
reconcile the live variable without dropping concurrent entries. This candidate
does not change any GitHub variable or installation permission.

Before consumer adoption, establish the OIDC-exchanged App identity can read each
private target and its live PR metadata; separately verify review publication and
status-write authority. A repository name match cannot prove any of those
capabilities. Verify one exact-head dispatch per consumer, matching private
visibility and immutable source/base/head, followed by an actual formal review
and required status. Missing App access must fail closed rather than widening
installation scope or substituting an unverified credential. Current tests use
local extracted guards and do not establish cross-organization runtime access.

The organization scheduler/mention router retain their existing CWL-only scope;
this candidate enables the required-caller/direct authenticated-dispatch path,
not an unverified cross-organization scheduler rollout. Consumer installation of
the reviewed workflow contract remains separate work. Existing edge policy also
remains active; any policy conflict requires an explicit owner decision, not a
bypass in this admission change.

Local validation: 128 passed, 1 skipped across intake, agent contract, Rust
coverage pin, live-Draft and required-verdict regressions under
`GITHUB_ACTIONS=true`. The dispatch content hash was recomputed with
`git hash-object`; no action/version pin was substituted. Hosted verification
and actual permission evidence remain outstanding.

## Local lint process diagnosis

Homebrew actionlint 1.7.12 blocked before starting ShellCheck on macOS. Its
upstream `process.go` writes the entire script into `StdinPipe` before calling
`Output`; scripts exceeding the pipe capacity deadlock. PID 35499 had no child
processes and its SIGQUIT dump showed two writes blocked with 130814 and 67165
byte inputs. The process was terminated diagnostically, not treated as success.

Official tag v1.7.12 (914e7df21a07ef503a81201c76d2b11c789d3fca) was cloned into
an isolated temporary directory. Replacing only that pipe write with
`cmd.Stdin = strings.NewReader(e.stdin)` allowed full lint to finish; upstream
`TestProcess` tests passed. No installed binary or workflow gate was changed.
Native actionlint with ShellCheck disabled passed workflow validation. Full
repaired-tool lint remained nonzero: its output exactly matched the clean
fb17ef556 baseline, with no admission-delta findings. These existing ShellCheck
findings remain unresolved and must not be reported as full lint success.
