# Orphaned GitHub Actions workflow-lifecycle inventory

검토 기준일: **2026-08-16**

## Incident

Live Actions inventories showed the same recurrence in multiple
ContextualWisdomLab repositories (ContextualWisdomLab/.github#945):

- AppGuardrail advertised dozens of historical `apply-*`, `finalize-*`,
  and `*-once.yml` identities as `state: active` while sampled default-branch
  paths returned 404 (ContextualWisdomLab/appguardrail#929);
- Clearfolio retained `one-shot-*` and PR-specific repair identities after
  the YAML had left the protected default branch (ContextualWisdomLab/clearfolio#423);
- DiskSage retained PR-specific finalizers in the same shape
  (ContextualWisdomLab/disksage#191).

Source deletion is not a complete workflow lifecycle. GitHub persists
registry records independently of the default-branch tree, so a buyer or
reviewer cannot treat "the YAML is gone" as "no writer remains enabled."

## Decision

1. The central `.github` repository owns a **read-only** inventory that
   binds every advertised workflow identity to the exact protected
   default-branch SHA observed at the start and re-read at the end.
2. Classification is evidence-based: `present_active`, `present_disabled`,
   `orphan_active`, `orphan_disabled`, `dynamic_owned`, or `unresolved`.
   A file named `once` is not alone proof of invalidity. A benign name
   does not hide a missing source file.
3. Incomplete visibility (401/403/404), a 5xx after one retry, pagination
   truncation, `total_count` drift, reused workflow IDs, percent-encoded
   paths, and default-branch movement fail closed.
4. This scanner never disables, deletes, or recreates workflows. Disablement
   remains a separately reviewed operator step after the ledger is
   revalidated.
5. `NVIDIA_NIM_API_KEY` may exist elsewhere in the control plane. This
   inventory never reads `COPILOT_GITHUB_TOKEN`.
6. CSAP and SOC 2 are design constraints (access visibility, change
   management, evidence retention). This record is not a certification
   claim. Operational identities (repository, workflow path, workflow ID)
   are not masked as PII.
7. Confirmed repository owner routes are maintained as an explicit,
   linkable registry from live fleet evidence. Repository slugs are matched
   case-insensitively, and both `orphan_active` and `orphan_disabled`
   classifications retain the route. The scanner does not infer issue
   numbers, create issues, or convert an absent owner route into a passing
   result.

## Trust boundary

The production CLI uses `--live` with the established central `GH_TOKEN`
transport. It paginates all visible repositories and workflows, rejects a
truncated recursive tree, and re-reads each default-branch head. A mandatory
API receipt file content-binds every read. Fixture input remains available for
deterministic tests. Neither boundary receives `secrets: inherit` or a guessed PAT.
GitHub-owned `dynamic/` identities are never treated as deleted repository
files.

The ledger improves operational visibility into enabled control-plane writers;
that visibility gap is not itself CWE-200 sensitive-information exposure.
CWE-862 describes missing authorization when a registry mutation is performed
without a reviewed operator path. This increment closes the visibility gap and
refuses the mutation.

## Prevention contract for repository workflows

A bounded repair workflow must take one of two paths before its PR is merged:

1. Keep the workflow on a short-lived branch, complete its work through a normal
   PR, and remove the YAML before it reaches the protected default branch. It
   never acquires a default-branch workflow registry identity.
2. If the workflow must reach the protected default branch, record its lifecycle
   owner and expiry condition in the PR. The owner must arrange a separately
   reviewed, exact-ID registry-disable action after use, then retain the API
   receipt and a fresh inventory showing the identity disabled.

Deleting the YAML alone does not satisfy the second path. A later inventory
finding remains open until the owner either completes that disablement or
documents an explicit reviewed exception. Neither a workflow name nor a
missing source file authorizes disablement by the read-only scanner.

## Operator contract

For a live read-only sweep, run:

```bash
python3 scripts/ci/inventory_orphaned_workflows.py --live \
  --output /tmp/workflow-lifecycle-ledger.json \
  --receipt-output /tmp/workflow-lifecycle-api-receipts.json \
  --failure-output /tmp/workflow-lifecycle-failure.json
```

The protected-default-branch integration is
`.github/workflows/workflow-lifecycle-inventory.yml`. Its scheduled runs have
read-only repository permissions, verify the checked-out SHA, and
retain completed API receipts plus either the immutable ledger or structured
failure evidence for 30 days. The live collector proves fleet completeness by
matching the paginated repository list to authenticated organization-wide
public/private totals; pagination alone is not accepted. It contains no disable endpoint;
operator mutation remains a later reviewed action.

For fixture verification, feed a JSON payload with `organization`, `observed_at`,
`repository_inventory_complete: true`, and one object per visible non-archived
repository. The completeness flag is mandatory: a partial repository list must
fail closed instead of producing a ledger that overstates fleet coverage. Each
repository must include the
start and end default-branch SHAs, the exact tree paths at that SHA, and
complete workflow pages (`total_count`, `workflows`, and either `_link_next`
or a GitHub `Link` header). Archived repositories are skipped.

```bash
python3 scripts/ci/inventory_orphaned_workflows.py \
  --payload schemas/examples/cwl-workflow-lifecycle-ledger-v1.example.json \
  --output /tmp/workflow-lifecycle-ledger.json
```

The scanner and owner-issue publisher expose no workflow-state mutation.
Disablement needs a separate reviewed operator path that rechecks the live
default-branch SHA, exact workflow ID, source absence, owner intent, active
runs, and reusable-workflow callers immediately before the API write. After a
reviewed operator pass, rerun the organization sweep and retain both receipt sets.
Known AppGuardrail, Clearfolio, and DiskSage owner routes bind the same live
evidence to their governance issues without heuristic issue creation.
The separately invoked owner-issue publisher verifies that each finding belongs
to the supplied ledger, then rechecks the live repository, default-branch SHA,
workflow ID/path/state, and complete source tree before posting. A changed
identity or restored source file stops publication. The publisher computes the
ledger's digest and scans existing owner issues before creating one for a
repository without a known route. It does not run in the read-only inventory
job.
Each owner issue is matched to the exact workflow ID and path. Before posting,
the publisher checks the open issue and every comment for the exact evidence
body, so retrying the same ledger does not duplicate a comment or hide another
workflow from that ledger.

For one separately reviewed finding, the operator supplies the exact ledger
digest, repository, and workflow ID:

```bash
python3 -m scripts.ci.workflow_lifecycle_operator \
  --ledger /tmp/workflow-lifecycle-ledger.json \
  --expected-ledger-sha256 "$REVIEWED_LEDGER_SHA256" \
  --repository appguardrail --workflow-id "$REVIEWED_WORKFLOW_ID"
```

The digest binds the reviewed file; it is not approval or fleet-completeness
proof by itself. Review the ledger and its API receipts first. The command
accepts one identity, requires the canonical ledger and its completeness
marker, and reads live GitHub evidence again before its issue write. It never
disables a workflow.

## Rollback

Rollback removes the inventory script, focused tests, schema example,
architecture entry, changelog entry, and this doctoring record together. No
registry state is mutated, so rollback does not re-enable or disable workflows.

## References

GitHub. (2026). *REST API endpoints for workflows*. GitHub Docs.
https://docs.github.com/en/rest/actions/workflows

GitHub. (2026). *Security hardening for GitHub Actions*. GitHub Docs.
https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions

MITRE. (2026a). *CWE-200: Exposure of sensitive information to an unauthorized actor*.
https://cwe.mitre.org/data/definitions/200.html

MITRE. (2026b). *CWE-862: Missing authorization*.
https://cwe.mitre.org/data/definitions/862.html
