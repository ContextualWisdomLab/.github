# Source-side Strix → appguardrail issue emitter

The central Strix security workflow (`.github/workflows/strix.yml`) runs as a
required org workflow across (nearly) all repositories. Each run writes one
Markdown report per vulnerability under `strix_runs/<run>/vulnerabilities/*.md`.
This system turns those reports into **per-finding GitHub issues** in the
`ContextualWisdomLab/appguardrail` tracker, deduplicated and lifecycle-managed
so the tracker always reflects the current state of each repository's findings.

It **replaces** the previous approach, where `appguardrail` polled failed runs
and opened one coarse issue per failed run with no close-on-fix. That collector
also never worked because its GitHub App identity was never provisioned.

## Components

| File | Role |
| ---- | ---- |
| `scripts/ci/strix_emit_appguardrail_issues.py` | Parses reports, plans and applies issue operations. Pure parsing/planning + a thin `gh api` client. |
| `tests/test_strix_emit_appguardrail_issues.py` | Unit tests: parsing, dedup hashing, op planning, close-on-fix set difference, incomplete-scan guard, dry-run and live execution. |
| `.github/workflows/strix.yml` (final steps) | Runs the emitter after the scan/gate, best-effort, reusing the OpenCode App token the job already OIDC-exchanges. |

## How it works

### Parsing

Each `vulnerabilities/*.md` report is parsed into a normalized `Finding`:
`title`, `severity` (CRITICAL/HIGH/MEDIUM/LOW/NONE), `cvss` + vector, `target`,
`endpoint`, `method`, `model`, `code_location` (`path:line[-range]`),
`description`, `impact`, `remediation`. Field lines tolerate plain
(`Severity: HIGH`) and Markdown-bold (`- **Severity:** HIGH`) styles, and code
locations are recovered from a `Code Locations` section, a labelled line, or a
prose reference. `/workspace/<repo>/` and PR-scope sandbox prefixes are stripped
so a file hashes identically across runs.

### Deduplication

The stable identity of a finding is:

```
dedup_key = sha256(source_repo + "\n" + finding_title + "\n" + normalized_code_location)
```

Titles are whitespace-collapsed. The full hash is stored in a hidden issue-body
marker `<!-- strix-finding: <hash> -->`; the first 12 hex chars also become a
label `strix-finding:<shorthash>`. Existing issues (open **or** closed) are
looked up by this hash before anything is created. Because the location is part
of the key, a finding that moves to a different line is a **new identity**: the
new location gets a fresh issue and the stale one is closed on fix.

### Issue shape

- **Title**: `[strix] <repo> <SEVERITY>: <title> (<path>:<line>)`
- **Labels**: `strix`, `security`, `repo:<name>`, `severity:<level>`,
  `strix-finding:<shorthash>`
- **Body**: full finding details, source repo/PR/head/run links, and three
  hidden markers (`strix-finding`, `strix-severity`, `strix-location`) that drive
  reconciliation.

### Lifecycle

| Situation | Action |
| --------- | ------ |
| Finding has no existing issue | **Create** an issue. |
| Finding matches an open issue | **Update** the body (refresh run/head/PR, CVSS, remediation). **Comment** only if severity changed. |
| Finding matches a closed issue | **Reopen** (update to `state: open`) and refresh. |
| Open issue's finding absent from a **complete** scan | **Close** with a `Resolved on <head_sha>` comment. |

### Close-on-fix guard

Close-on-fix runs **only when the scan completed cleanly**. In the workflow this
is gated on `steps.run_strix.outcome == 'success'` (`STRIX_SCAN_COMPLETE=true`).
A failed or skipped Strix step — which includes provider/infra errors and
incomplete scans — leaves the flag `false`, so issues are created/updated but
**never closed** on a partial scan. The emitter defaults `--scan-complete` off,
so the safe behaviour is the default.

### Authentication and DRY-RUN

The emitter needs a token with **Issues: write** on `appguardrail` (the org
`github.token` cannot create issues cross-repo). Instead of provisioning a new
GitHub App, the workflow **reuses the OpenCode GitHub App token it already
obtains** — the same token minted by the `Exchange OpenCode app token for target
repository reads` step (`steps.target_app_token`), which the job already uses for
cross-repo reads and status writes. That token is exchanged over OIDC
(`POST https://api.opencode.ai/exchange_github_app_token`) with **no stored
secret** and passed to the emitter via the `STRIX_ISSUE_APP_TOKEN` environment
variable. **No new GitHub App and no new org secrets are created.**

If that variable is empty — because the OIDC exchange was unavailable — the
emitter runs in **DRY-RUN**: it parses, plans, and logs every intended
create/update/close operation, mutates nothing, and exits 0. If the token is
present but lacks Issues: write on `appguardrail`, the emitter degrades the same
way: a failed issue *list* read plans in DRY-RUN, and any individual write that
is rejected is logged as a warning and swallowed. Either way the Strix gate
result is never affected. `--dry-run` forces DRY-RUN for local use and tests, and
anything resembling a token is redacted from log output.

## One-time enablement (manual, tiny — no new App or secret)

The emitter reuses the **existing** OpenCode GitHub App, so there is nothing to
provision. It writes real issues as soon as that App can write issues to
`appguardrail`. Verify the two conditions below once; each is a couple of clicks
and neither creates a new App or secret:

1. **Grant the OpenCode App `Issues: Read and write`.**
   `github.com/organizations/ContextualWisdomLab/settings/apps` → open the
   **OpenCode** app → **Permissions & events** → **Repository permissions** →
   set **Issues** to **Read and write** → **Save changes**. (If the App is owned
   by OpenCode rather than the org, this permission is already part of the
   `opencode-github-action` App and no action is needed; an org-owned install
   just needs the permission accepted.)
2. **Ensure the App is installed on `appguardrail`.**
   `github.com/organizations/ContextualWisdomLab/settings/installations` → open
   the **OpenCode** installation → **Repository access** → confirm **appguardrail**
   is included (either **All repositories** or **Only select repositories** with
   `appguardrail` checked) → **Save**. If a permission change from step 1 is
   pending, an org owner accepts it on this same screen.

Until both hold, the emitter stays in DRY-RUN and only logs intended operations —
the Strix gate is unaffected. No code change or redeploy is needed to switch out
of DRY-RUN; the next scan after the App can write issues begins emitting for real.

## Retiring the old collector (do this after this lands)

The previous per-failed-run collector in **`ContextualWisdomLab/appguardrail`**,
`.github/workflows/org-security-failure-collector.yml`, must be **disabled or
removed** once this source-side emitter is live, otherwise the two systems will
file duplicate/overlapping issues. That change lives in the `appguardrail` repo
and cannot be made from this repository — remove the workflow (or set it to
`workflow_dispatch`-only / delete it) as a follow-up PR there. The
`ORG_SECURITY_FAILURE_APP_ID` / `ORG_SECURITY_FAILURE_APP_PRIVATE_KEY` secrets it
depended on can also be retired.
