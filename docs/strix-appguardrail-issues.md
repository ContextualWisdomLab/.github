# Source-side security findings → appguardrail issue emitter

The central Strix security workflow (`.github/workflows/strix.yml`) runs as a
required org workflow across (nearly) all repositories. Each run writes one
Markdown report per vulnerability under `strix_runs/<run>/vulnerabilities/*.md`.
This system turns those reports and every open **GitHub Code Scanning alert**
into per-finding GitHub issues in the `ContextualWisdomLab/appguardrail`
tracker, deduplicated and lifecycle-managed so the tracker reflects both
runtime Strix findings and SARIF-backed repository alerts. Code Scanning
governance findings such as the Low-severity OpenSSF/CII badge alert stay
visible; the Medium-or-higher cutoff applies only to Strix reports.

It **replaces** the previous approach, where `appguardrail` polled failed runs
and opened one coarse issue per failed run with no close-on-fix. That collector
also never worked because its GitHub App identity was never provisioned.

## Components

| File | Role |
| ---- | ---- |
| `scripts/ci/strix_emit_appguardrail_issues.py` | Parses Strix reports and Code Scanning alerts, then plans and applies issue operations. Pure parsing/planning + thin `gh api` clients. |
| `tests/test_strix_emit_appguardrail_issues.py` | Unit tests: parsing, dedup hashing, op planning, close-on-fix set difference, incomplete-scan guard, dry-run and live execution. |
| `.github/workflows/strix.yml` (final steps) | Runs the emitter after the scan/gate with a repository-scoped Noema App token. Missing credentials or failed issue reads/writes fail visibly. |

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

When `--include-code-scanning` is set, the emitter also performs a complete,
paginated read of the source repository's open Code Scanning alerts. It
preserves the tool/rule, security severity, current location, message,
description, remediation, and a direct alert URL. Generic `error`, `warning`,
and `note` severities map to High, Medium, and Low only when GitHub does not
provide a security severity.

### Deduplication

The stable identity of a finding is:

```
dedup_key = sha256(source_repo + "\n" + finding_title + "\n" + normalized_code_location)
```

Titles are whitespace-collapsed. The full hash is stored in a hidden issue-body
marker `<!-- strix-finding: <hash> -->`. Existing issues (open **or** closed) are
looked up by this hash before anything is created. Because the location is part
of the key, a finding that moves to a different line is a **new identity**: the
new location gets a fresh issue and the stale one is closed on fix.

Code Scanning findings instead use `source_repo + source_kind + alert_number`
as their stable identity. A GitHub alert therefore stays attached to one
AppGuardrail issue when its message, severity, or current location changes.

### Issue shape

- **Title**: `[strix|code-scanning] <repo> <SEVERITY>: <title> (<path>:<line>)`
- **Labels**: source label (`strix` or `code-scanning`), `security`,
  `repo:<name>`, `severity:<level>`
- **Body**: full finding details, source repo/PR/head/run links, and three
  hidden markers (`strix-finding`, `strix-severity`, `strix-location`) that drive
  reconciliation.

The full finding identity is kept in the hidden body marker instead of creating
one repository label per finding; this prevents unbounded label growth as the
organization-wide tracker accumulates findings.

### Lifecycle

| Situation | Action |
| --------- | ------ |
| Finding has no existing issue | **Create** an issue. |
| Finding matches an open issue | **Update** the body (refresh run/head/PR, CVSS, remediation). **Comment** only if severity changed. |
| Finding matches a closed issue | **Reopen** (update to `state: open`) and refresh. |
| Open issue's finding absent from a **complete** scan | **Close** with a `Resolved on <head_sha>` comment. |

### Close-on-fix guard

Close-on-fix runs **only when the scan completed cleanly**. In the workflow this
is gated on the explicit `steps.run_strix.outputs.scan_complete == 'true'`
signal, and only a whole-repository `push`, `schedule`, or non-PR manual scan
uses `--scope full`. A provider-neutral skip deliberately exits the required
step successfully but keeps `scan_complete=false`; a failed or incomplete scan
does the same. Those runs may create/update findings already present in their
reports, but **never close** an issue. PR scans always use `--scope pr` and never
close issues because absence from changed files is not proof of resolution. The
emitter defaults both guards to their safe values.

### Authentication and DRY-RUN

The emitter needs **Issues: write** on `appguardrail`; a required workflow's
ordinary `github.token` cannot write cross-repository issues. The workflow uses
the existing organization-owned **cwl-noema-review** GitHub App and mints an
installation token with `actions/create-github-app-token`, explicitly scoped to
the single `appguardrail` repository and `permission-issues: write`. The App
client ID and private key remain in the existing
`NOEMA_GITHUB_APP_CLIENT_ID` organization variable and
`NOEMA_GITHUB_APP_PRIVATE_KEY` organization secret. The short-lived token is
passed only as `STRIX_ISSUE_APP_TOKEN` and token-like output is redacted.

A second short-lived token is scoped to the source repository with
`security-events: read` and passed only as `CODE_SCANNING_SOURCE_TOKEN`. The
source repository name is validated against `ContextualWisdomLab/<safe-name>`
before it is used as an App-token scope. Alert reads and issue writes therefore
remain separately least-privileged.

This path is intentionally fail-closed. Missing credentials, token-mint
failure, issue-list failure, label bootstrap failure, and every rejected issue
mutation produce `::error::` output and a nonzero step result. There is no
implicit live-run fallback to dry-run, so a green workflow cannot silently lose
findings. `--dry-run` remains an explicit local/test-only mode.

## One-time enablement

The existing Noema App and organization credentials are reused. Complete these
permission checks once before merging the workflow change:

1. **Grant cwl-noema-review `Issues: Read and write`.**
   `github.com/organizations/ContextualWisdomLab/settings/apps` → open the
   **cwl-noema-review** app → **Permissions & events** → **Repository
   permissions** → set **Issues** to **Read and write** → **Save changes**.
2. **Ensure the App is installed on `appguardrail`.**
   `github.com/organizations/ContextualWisdomLab/settings/installations` → open
   the **cwl-noema-review** installation → **Repository access** → confirm
   **appguardrail** is included → **Save**. Accept the pending permission change
   on the installation if GitHub requests it.
3. **Grant cwl-noema-review `Code scanning alerts: Read-only`.** The App must be
   installed organization-wide (or at least on every source repository) so the
   source-scoped alert token can be minted without widening `github.token`.

Until both hold, collection fails visibly with the exact configuration or API
reason in the run log. The next scan after the permission is accepted emits and
reconciles issues without another code deployment.

## Retiring the old collector (do this after this lands)

The previous per-failed-run collector in **`ContextualWisdomLab/appguardrail`**,
`.github/workflows/org-security-failure-collector.yml`, must be **disabled or
removed** once this source-side emitter is live, otherwise the two systems will
file duplicate/overlapping issues. That change lives in the `appguardrail` repo
and cannot be made from this repository — remove the workflow (or set it to
`workflow_dispatch`-only / delete it) as a follow-up PR there. The
`ORG_SECURITY_FAILURE_APP_ID` / `ORG_SECURITY_FAILURE_APP_PRIVATE_KEY` secrets it
depended on can also be retired.
