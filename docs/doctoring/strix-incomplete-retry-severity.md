# Strix incomplete-retry severity neutralization

검토 기준일: **2026-08-13**

## Incident

Required `Strix Security Scan` on ContextualWisdomLab/.github#930 exact head
`f745422e0eabd1aac92c3be0e6cee92385c365e4` (run `31665090829`) selected NVIDIA
NIM as the primary provider. The first Nemotron attempt reported zero
vulnerabilities. A midstream retry then printed boxed TUI lines
`Severity: HIGH`, `Severity: MEDIUM`, and `Vulnerabilities 2` and failed
before writing a vulnerability report artifact. The later Llama fallback
reported zero vulnerabilities. GitHub Models fallbacks then returned HTTP
410 `github_models_retirement_brownout`.

The trusted gate printed its incomplete-evidence verdict:

> No Strix vulnerability report artifact was produced; log-only severity
> markers are incomplete evidence, so the scan is failing closed.

and

> Strix reported zero vulnerabilities before provider infrastructure
> failure; failing closed because provider infrastructure failures are not
> clean scan evidence.

The outer workflow still grepped the full console tee for
`severity[[:space:]]*:` and `Vulnerabilities[[:space:]]+[1-9]`. Those leftover
TUI lines from the incomplete retry matched, so the backend-unavailable
neutral skip did not run and the required check failed for a non-backend
reason.

The same GitHub Models 410 brownout appeared on #949, #941, and #934. Those
runs are not independently mergeable while the leftover-TUI override remains.

## Decision

Keep accepted findings fail-closed. Honor the trusted gate when it has
already classified leftover console severity as incomplete log-only
evidence.

1. Classify `github_models_retirement_brownout` and the gate sentence
   `failed after provider infrastructure or failure-signal output` as
   backend unavailability.
2. Introduce `incomplete_log_only_signal` bound to the two exact gate
   sentences above.
3. Neutralize only when a backend-unavailable signal is present and either
   no vulnerability signal exists or the incomplete-log-only gate verdict
   is present.
4. A console `Vulnerabilities 1` / `Severity: HIGH` pair without that gate
   verdict remains blocking.

Do not lower the two-approval ruleset. Do not treat provider brownout as
approval evidence. Review agents remain `edit: deny`.

## Trust boundary

The incomplete-log-only phrases are printed by the trusted `strix_quick_gate.sh`
on the base branch. Scanner stdout can still include repository text, so the
override requires those exact gate sentences rather than a generic
`Vulnerabilities 0` match. A later incomplete fallback cannot hide an
accepted finding that never received that gate verdict.

## Verification contract

`tests/test_strix_nvidia_nim_not_found_fallback.py` executes the production
outer-workflow regular expressions against synthetic logs:

1. NVIDIA NIM same-line catalog 404 without findings remains neutral.
2. `Vulnerabilities 1` without the incomplete-evidence sentence remains
   blocking.
3. The live #930 leftover-TUI shape (`Severity: HIGH`, `Vulnerabilities 2`,
   incomplete-evidence sentence, 410 brownout) is neutral.
4. `tests/test_required_workflow_queue_contract.py` pins the new signal name
   and GitHub Models brownout marker.

## Inline Python quoting

`strix.yml` previously used indented `<<'PY'` heredocs inside YAML `run: |`
blocks. GitHub Actions strips the common indent before bash runs, so those
closers were valid in CI. A raw `bash -n` of the workflow file does not strip
indent and reported an unclosed heredoc from the trusted-source resolver to
EOF. The three inline Python programs are now quoted `python3 -c` programs,
which close independently of column 0. The trusted-source resolver still runs
before checkout and therefore stays inline.

## Rollback

If a run with a real vulnerability report artifact is neutralized because
the incomplete-evidence sentence also appears, remove the
`incomplete_log_only_signal` override and restore the previous
`backend && ! vulnerability` conjunction. Do not delete the brownout
classifier unless GitHub Models is again a live, non-retired provider.

## References (APA 7th)

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved
August 13, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

GitHub. (n.d.). *REST API endpoints for GitHub Models*. GitHub Docs. Retrieved
August 13, 2026, from
https://docs.github.com/en/rest/models

OpenAI. (n.d.). *API errors*. OpenAI Platform. Retrieved August 13, 2026,
from https://platform.openai.com/docs/guides/error-codes

Free Software Foundation. (n.d.). *3.6.6 Here documents*. Bash Reference
Manual. Retrieved August 13, 2026, from
https://www.gnu.org/software/bash/manual/html_node/Redirections.html#Here-Documents
