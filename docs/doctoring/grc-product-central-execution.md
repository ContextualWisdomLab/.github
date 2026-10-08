# GRC Product central execution — staged rollout

Status: **Implemented source / cloud policy-tested / not activated**.

## Ownership and existing delivery

The GRC policy/control/evidence kernel remains in
`ContextualWisdomLab/governance-risk-compliance`. This control plane owns only
`.github/workflows/grc-product.yml`, its policy tests, `.github/actionlint.yaml`
(custom label validation), and the thin-caller template.
There is no new identity, risk, audit, scanner, database, or officer UI body here.

- `ContextualWisdomLab/.github#2565` already owns conversion of all existing
  central workflows to self-hosted. Do not duplicate its 73-job change.
- `ContextualWisdomLab/linux-cluster-ops#326` owns S1 placement, registration,
  access custody, image provisioning, reset and actual canary.
- `ContextualWisdomLab/quarantine-sandbox-runtime#136` and
  `ContextualWisdomLab/quarantine-sandbox-runtime#137` own reachability-attestation
  contracts. Limited point probes are not complete CIDR or clean-job evidence.
- GRC privacy #69/#70; Keyverse #38, #55–#58, revision #73 and coverage #74;
  PostgreSQL #18; version-one API #53; officer workspace #34/#54; readiness #17;
  domain roadmap #27–#30; and baseline refresh #75 retain their existing owners.
  All those references are in `ContextualWisdomLab/governance-risk-compliance`.

A useful commercial GRC must distinguish artifact presence from tested control
operating effectiveness. The existing roadmap's dependency sequence remains:
identity/tenancy, PostgreSQL, evidence recovery, operations and stable API;
then internal controls, obligations/catalog, risk/audit and connected officer
workflows. This CI increment does not close any of those product issues.

## Central contract

The workflow accepts no executable caller input or secret inheritance. It runs
only the fixed GRC repository on same-repository PRs, pushes and manual runs.
Foreign callers, external PR heads, missing PR repository identity and unsupported
events fail in an actual pre-checkout shell; they are not skipped into success.
This guard executes after runner assignment and is not pre-lease isolation proof.

Only `CWL CI isolated` AND `[self-hosted, Linux, X64, cwlab-ci-isolated]` may run
the product job. No hosted fallback, control/scanner pool or existing runner
relabeling is introduced. The original exact-head checkout, immutable Actions,
`contents: read`, no persisted Git credentials, Python 3.12, locked uv install,
Ruff, docstrings 100%, production statement/branch coverage 100%, compile, lock
freshness and dirty-tree gates remain. UV cache is job-private, not shared or
uploaded, and cleanup runs even on failure. VM cancellation/termination reset,
HOME/tool-cache/workspace cleanup and network isolation remain operator gates.

StepSecurity harden-runner is retained, not silently removed. Its self-hosted
agent and subscription/image acceptance must be established by the operator;
a successful/no-op action is not monitoring or isolation evidence. No subscription
purchase is authorized here. References: GitHub's reusable-workflow runner context
reference and StepSecurity's self-hosted/how-it-works documentation.

## Consumer rollout, without dangling remote pins

`docs/templates/grc-product.yml.in` preserves GRC trigger/path exclusions and
workflow-scope PR-only cancellation. ARCHITECTURE.md is deliberately not ignored.
Do not add the same concurrency group to the reusable workflow: it can cancel
its calling run. Changing to a reusable job may change check-context display
names; inspect actual contexts and reconcile through the existing protection owner,
never remove required gates as a shortcut.

1. Independently review and publish this central source through the ordinary
   protected path. This session does not authorize commit, push or merge.
2. Obtain a real accepted isolated group, caller repository/workflow/ref/event/fork
   eligibility, disposable image and cleanup proof under ops #326 and QSR.
   Runner availability and central workflow availability are separate gates.
3. Replace `__CENTRAL_PRODUCT_COMMIT__` in the template with the exact reviewed,
   published 40-hex central commit. Verify that commit contains this workflow.
   Copy only the rendered caller to GRC `.github/workflows/product.yml` in an
   owner-reviewed PR; do not use a fabricated hash, mutable ref or unresolved pin.
4. Update GRC's dirty-tree workflow regression to validate the released central
   contract rather than require execution commands in the caller. Keep its
   concurrency regression and all product quality thresholds unchanged.
5. Have existing #18, #34 and #17 owners inventory and migrate PostgreSQL, UI
   and readiness executable jobs using independently reviewed central contracts.
   Those contracts are not implemented by this initial Product slice.
6. Inspect GitHub-managed dynamic CodeQL/Code Quality configuration through its
   current owner. Moving YAML cannot move those platform-managed jobs.
7. On the unchanged caller/central source pair, record actual run/job ID, runner
   name/group, tool-image identity, all executed checks, cleanup and qualifying
   independent approval. Only that evidence permits a runtime-complete claim.

## Observed boundary — October 5, 2026

The initial GRC branch is `529cf321f134e26c0cd379ee53c06ab5297363b6`.
Central baseline is `37b10243cec3d160ecc9c1be75c71428b160a703`.
The GRC repository runner inventory returned zero. The original GRC worktree is
unchanged. Central preparation is in a dedicated cloud clone on S1, not another
writer's checkout. The operator infrastructure and production containers were
not modified. No remote central approval, protected integration, self-hosted
GitHub Product run, full-organizational migration or release is claimed.

## Execution evidence

New central-contract existence test first failed with
`GRC Product execution must be centrally owned`. The implemented workflow then
passed 8 policy tests normally and 8 with `GITHUB_ACTIONS=true` on S1. The
admission regression executes the actual shell for allowed and rejected tuples.
This is cloud source validation, not registered runner execution.

Additional actual S1 acceptance: actionlint 1.7.12 (official archive digest verified),
new policy-test Ruff E9/F/I and `git diff --check` pass. The unchanged GRC baseline
ran in a resource-bounded, non-root, read-only Python 3.12.15 container with no
host socket, service mounts or credentials. Locked uv 0.12.5 installation,
Ruff, docstrings, compile and lock freshness pass; 48 tests cover all 769
production statements and 152 branches. The run emitted 36 existing dependency
deprecation warnings (Starlette HTTPX and SQLite datetime adapter), which remain
visible rather than being suppressed. The product tree remains clean and the
container was removed. The bootstrap uv package was fetched by exact version,
not a hash-locked bootstrap; this receipt is not runner-image supply-chain approval.
Full central repository tests, actual GitHub Actions, protected integration and
release remain NOT_RUN. Further gate
results must be reported from their actual command output, not inherited from
central #2565 or any product feature PR.
