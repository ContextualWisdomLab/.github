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
| `.github/workflows/strix.yml` (final steps) | Mints the App token and runs the emitter after the scan/gate, best-effort. |

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

The emitter needs a GitHub App installation token with **Issues: write** on
`appguardrail` (the org `github.token` cannot create issues cross-repo). The
workflow mints one with `actions/create-github-app-token` and passes it via the
`STRIX_ISSUE_APP_TOKEN` environment variable.

If that variable is empty — because the App/secrets are not provisioned, or the
mint step failed — the emitter runs in **DRY-RUN**: it parses, plans, and logs
every intended create/update/close operation, mutates nothing, and exits 0. The
Strix gate result is never affected. `--dry-run` forces this for local use and
tests. Anything resembling a token is redacted from log output.

## Provisioning (manual, one-time)

The emitter is dormant (DRY-RUN) until a human provisions the GitHub App and
secrets. Do this once:

1. **Create a GitHub App** in the `ContextualWisdomLab` org (Settings → Developer
   settings → GitHub Apps → New GitHub App). Suggested name:
   `strix-issue-emitter`.
   - **Repository permissions → Issues: Read and write.** (No other permissions
     are required.)
   - No webhook needed; uncheck "Active".
2. **Install the App** on the org, scoped at minimum to the `appguardrail`
   repository (Install App → select `appguardrail`, or all repositories).
3. **Generate a private key** for the App (Private keys → Generate). Download the
   `.pem`.
4. **Set two secrets** at the organization level (or on the `.github` repo) so
   the required Strix workflow can read them:
   - `STRIX_ISSUE_APP_ID` — the App's numeric App ID.
   - `STRIX_ISSUE_APP_PRIVATE_KEY` — the full contents of the downloaded `.pem`.

Once both secrets exist, the next Strix run mints a token and begins emitting
real issues. No code change is required to switch out of DRY-RUN.

## Retiring the old collector (do this after this lands)

The previous per-failed-run collector in **`ContextualWisdomLab/appguardrail`**,
`.github/workflows/org-security-failure-collector.yml`, must be **disabled or
removed** once this source-side emitter is live, otherwise the two systems will
file duplicate/overlapping issues. That change lives in the `appguardrail` repo
and cannot be made from this repository — remove the workflow (or set it to
`workflow_dispatch`-only / delete it) as a follow-up PR there. The
`ORG_SECURITY_FAILURE_APP_ID` / `ORG_SECURITY_FAILURE_APP_PRIVATE_KEY` secrets it
depended on can also be retired.
