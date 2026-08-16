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

## Trust boundary

The inventory consumes only a caller-supplied fixture or a least-privilege
read of the Actions registry and git tree. It does not receive repository
write permission, `secrets: inherit`, or a guessed PAT. GitHub-owned
`dynamic/` identities are never treated as deleted repository files.

MITRE CWE-200 describes exposure of sensitive information when an observer
cannot tell which control-plane writers are enabled. CWE-862 describes
missing authorization when a registry mutation is performed without a
reviewed operator path. This increment closes the visibility gap and
refuses the mutation.

## Operator contract

Feed a JSON payload with `organization`, `observed_at`, and one object
per visible non-archived repository. Each repository must include the
start and end default-branch SHAs, the exact tree paths at that SHA, and
complete workflow pages (`total_count`, `workflows`, and either `_link_next`
or a GitHub `Link` header). Archived repositories are skipped.

```bash
python3 scripts/ci/inventory_orphaned_workflows.py \
  --payload schemas/examples/cwl-workflow-lifecycle-ledger-v1.example.json \
  --output /tmp/workflow-lifecycle-ledger.json
```

`--fail-on-orphan-active` is reserved for a later reviewed live sweep.
This increment's default is to emit the ledger so CI can prove
classification without disabling sibling-repository writers.

## Rollback

Delete `scripts/ci/inventory_orphaned_workflows.py` and its tests. No
registry state is mutated, so rollback does not re-enable or disable
workflows.

## References

GitHub. (2026). *REST API endpoints for workflows*. GitHub Docs.
https://docs.github.com/en/rest/actions/workflows

GitHub. (2026). *Security hardening for GitHub Actions*. GitHub Docs.
https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions

MITRE. (2026a). *CWE-200: Exposure of sensitive information to an unauthorized actor*.
https://cwe.mitre.org/data/definitions/200.html

MITRE. (2026b). *CWE-862: Missing authorization*.
https://cwe.mitre.org/data/definitions/862.html
