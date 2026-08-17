# Strix required-workflow smoke vs NIM-only (chicken-and-egg)

검토 기준일: **2026-08-17**

## Failure

Required `Strix Security Scan / strix` on ContextualWisdomLab/.github#1052
failed in `Self-test Strix required workflow contract` with three needles
from the **base-branch** smoke script:

1. top-level `models: read`
2. `Prepare GitHub Models fallback credentials`
3. `nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5 github_models/openai/o3 github_models/openai/gpt-5-chat`

`pull_request_target` runs `scripts/ci/strix_required_workflow_smoke.sh` from
the required-workflow SHA (main). That script greps the PR-head
`.github/workflows/strix.yml`. GitHub Models is unused in this PR, so the
head workflow no longer contained those strings.

## Decision

Do not re-enable GitHub Models. Update the smoke script in this PR to the
NIM-only contract (`actions: read` + `contents: read`, NIM fallback,
`NVIDIA_NIM_API_KEY` fail-closed, reject `github_models/*`). Keep three
unused compatibility needles in the PR-head workflow so **this** PR can
pass main's still-old smoke:

- unused `models: read` (exact permission line; main's Python checker
  requires it)
- a retired step named `Prepare GitHub Models fallback credentials` with
  `if: false`
- a comment containing the old NIM-then-GitHub-Models fallback list

Runtime fallback stays
`nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5`. No
`STRIX_GITHUB_MODELS_TOKEN`, no `COPILOT_GITHUB_TOKEN`, no GitHub Models
provider.

## Next step (after this PR merges)

Remove the unused `models: read` line and the retired `if: false` step.
The replacement smoke on main will no longer require them.

## Related CodeQL flake

`CodeQL PR / CodeQL merge preview (actions)` failed in
`github/codeql-action/init` with `HttpError: No server is currently
available` while determining feature enablement. Head analysis and the
Python merge preview passed. Both CodeQL jobs now wait for `gh api
rate_limit` before init, and merge preview retries init once after a 30s
wait and database cleanup.
