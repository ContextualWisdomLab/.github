# Gyeot central reusable CI — 2026-10-08

## Scope and source identity

This is an additive, unpublished implementation based on central protected-source
commit `7554587c2e3106a388998bcad048a3d7121de25e`, in branch
`feat/gyeot-central-self-hosted`. It changes only this document,
`.github/workflows/gyeot-ci.yml`, `scripts/ci/gyeot_*` and
`tests/test_gyeot_central_ci.py`. Product source is read-only input.

Central migration PR #2565 owns existing workflows, runner-routing policies and
shared actionlint configuration. Its freshly read head on 2026-10-08 was
`6e924f32a2dbaa0950709c6d8f1391fc1058ef43`, superseding the supplied historical
`62c051bd2668cee351a1648aba3d8e72af774f20` checkpoint. Issue #2560 owns the
personal LiteLLM relay, service-key custody and deployed review routing. Neither
lane is changed here. Security, independent conditional AI approval, model
selection and merge gates remain their owners' responsibilities.

The process was derived from the actual canonical product files at
`/Users/seonghobae/orca/workspaces/gyeot/fulmar/.github/`: `app-ci.yml`,
`verify_app.sh`, `verify_server.sh`, `verify_export.sh`, `check_export.cjs`, and
all five policy/behavioral test files. The new central shell scripts accept only
one internal positional argument: the admitted product checkout root. Shell
source/helper paths are anchored to `BASH_SOURCE`, independent of cwd.

## Contract

- Only `workflow_call`, no inputs, declared secrets, inherited secrets, release
  environment or writable token. Caller template passes neither `with` nor `secrets`.
- Each job's first inline shell rejects every caller except
  `ContextualWisdomLab/gyeot`. Only same-repository `pull_request`, `push` and
  `workflow_dispatch` are admitted. Unsupported sources fail instead of skip.
- `CWL Gyeot CI` plus `[self-hosted, Linux, X64, gyeot-ci]`, 30-minute job bounds,
  no hosted fallback. Fork admission is defense in depth, not host isolation.
- Product checkout is the fixed repository at `github.sha` (PR merge candidate
  for `pull_request`, event commit otherwise); both checkouts disable credential
  persistence. No caller-controlled ref or executable command is accepted.
- Actions reuse the canonical immutable checkout/setup-node/upload pins. Node 24
  is selected and checked by the processes. No global package/tool install,
  sudo/apt or runner registration is performed.
- Concurrency belongs to the caller only. PR groups omit SHA so successive heads
  coalesce; non-PR events use an explicit event/ref fallback.
- App: clean owned coverage, initialize readiness false, locked installs, product
  policy tests/actionlint/types, Jest coverage, then Android/iOS production exports.
  Re-clear coverage immediately before Jest. Readiness requires a current nonempty
  nonsymlink `coverage/lcov.info` and nonsymlink coverage root. Jest's actual failure
  status is retained; current failed-test coverage can still be uploaded.
- Upload requires successful admission, product checkout, central checkout and
  current producer readiness. Early failures cannot upload a previous candidate.
- Export outputs are requested under a unique `RUNNER_TEMP` directory, with cleanup
  limited to that invocation's private root. Before accepting metadata, the checker
  requires real, nonsymlink private/platform directories, the exact requested
  platform child path, and the matching resolved parent/child relation. Its internal
  CLI is `node gyeot_check_export.cjs OUTPUT PLATFORM PRIVATE_EXPORT_ROOT`; the shell
  supplies the trusted root created by `mktemp`, never a producer-derived root.
  Version-0 Metro metadata, nonempty JS/Hermes bundles/assets and relative-path /
  resolved-reference containment remain required. This does not prove native boot,
  signing, hostile-producer write isolation or race-free filesystem access.
- Server: pre-provisioned PostgreSQL/non-root check, locked server install,
  typecheck, four unit entrypoints, serial RLS and API integration. Product
  `server/db/test_migrations.sh` is picked up only when its owning PR lands;
  it was absent in the measured snapshot, not counted as executed.

## Immutable central helper source and publication gate

Use the already established **fixed, independently reviewed helper snapshot**
pattern from `.github/workflows/exact-artifact-sbom-attestation.yml:78-109`.
The caller's `github.workflow_sha` is not a central helper revision, and
`job.workflow_sha`/`job.workflow_repository` are not supported expression fields.
No OIDC permission, invented context resolver or mutable main fallback is added.
The official GitHub reuse-workflows/context references and exact Expo v57 index
were fetched on 2026-10-08; these describe caller syntax/context availability,
not evidence that this unpublished workflow has remotely run. Source URLs are
retained in the scratch `primary-docs.json` receipt.

`GYEOT_HELPER_COMMIT: UNPUBLISHED_GYEOT_HELPER_COMMIT` deliberately blocks
execution before central checkout. It is not a nonexistent hexadecimal ref or
an executable input. Publication requires two reviewed stages:

1. Publish the new helper snapshot through normal central protection; record the
   actual immutable commit containing all four helpers.
2. Replace the sentinel with that exact lowercase 40-hex commit, independently
   review the workflow, publish it, and record its *different* central commit.
   Identity checks bind helper HEAD, fixed origin, tracked clean helper paths and
   required nonsymlink helper files. Never replace the sentinel with this baseline
   commit, which does not contain the new helpers.
3. Only after both stages, replace the consumer template placeholder below with
   the actual reviewed workflow commit and let the product owner integrate it.
   Reconcile displayed required-check contexts with their policy owner before
   replacing the product's current `verify` / `server-verify` caller.

Neither publication stage is performed by this task. No commit, push, remote
configuration, key/secret access, product caller edit or merge is authorized here.

## Consumer template — NOT installed

Keep the existing product caller until an actual reviewed central commit exists.
`UNPUBLISHED_CENTRAL_COMMIT` must remain explicit in this template until then.
No mutable `main`, fabricated SHA or `secrets: inherit` is acceptable.

```yaml
name: App CI
on:
  pull_request:
  push:
    branches: [develop]
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: gyeot-ci-${{ github.repository }}-${{ github.workflow }}-${{ github.event.pull_request.number && format('pr-{0}', github.event.pull_request.number) || format('{0}-{1}', github.event_name, github.ref) }}
  cancel-in-progress: true
jobs:
  gyeot:
    uses: ContextualWisdomLab/.github/.github/workflows/gyeot-ci.yml@UNPUBLISHED_CENTRAL_COMMIT
```

## Runner handoff and remote limits

The canonical product receipt records group 9 with **zero runners**; this is a
historical local receipt, not a fresh runner-inventory query. This candidate is
**not remotely executed**. Group-plus-label routing, repository/workflow access,
runner online capacity and actual execution are distinct acceptance gates.
Do not claim an empty group can execute remotely or solve capacity with hosted
fallback. Assignment/execution remains unperformed.

Custodian must provide a disposable isolated non-root Linux X64 image, a runner
version supporting pinned Node-24 actions, Node 24/npm, actionlint, PostgreSQL
`initdb`, `pg_ctl`, `psql`, `createdb`, sufficient temporary disk and approved
npm/action fetch access. The image must not expose production databases, backup
volumes, signing credentials, host Docker sockets or private networks. Product
SQL fixtures still use legacy short `/tmp/gyeot_*` socket directories; the image
must isolate that temporary filesystem. This lane does not edit those product
fixtures. Do not relax existing group restrictions or reuse a signing worker.

The shared `.github/actionlint.yaml` belongs to PR #2565. This task used a private
scratch config declaring only `gyeot-ci` for targeted lint, without editing that
owner's config or ignoring expression errors. The owner must admit the custom
label in its normal shared configuration before whole-repository lint is claimed.

## Local execution and evidence

Raw logs and per-command receipts:
`/Users/seonghobae/.hermes/cache/scratch/gyeot-central-ci-evidence-20261008/`.
Final hashes and owned-file list are recorded in `final-manifest.json` there.

TDD checkpoints (actual failures, not collection errors):

- Admission: 24 missing-workflow failures, then 24 passes.
- Snapshot/wiring: 2 failures / 24 passes, then 26 passes.
- App/server processes: 19 missing-helper failures / 26 passes.
- Export: 34 additional missing-helper failures (53 total / 26 passes), then
  79 passes after implementing the processes and checker.
- Consumer template: 1 missing-document failure / 79 deselected, before writing
  this document. Initial combined result: **80 passed** normally and **80 passed**
  with `GITHUB_ACTIONS=true`; both commands exited 0. Raw outputs are
  `final-pytest-corrected.log` and `final-pytest-actions-corrected.log`, with JUnit.
  An earlier final-harness PATH selected Homebrew Python without pytest; those
  two collection failures are retained, then corrected by explicitly invoking
  `/Users/seonghobae/.pyenv/versions/3.14.5/bin/python3` on unchanged source.
  `red-export-full.log` preserves the complete 70,747-byte original RED output;
  its earlier truncated tool capture is retained separately.
- A supplementary behavioral identity test found a real shell-errexit bug:
  `test -f ... && test ! -L ...` inside a loop did not fail for a missing
  non-final helper. The actual shell returned 0 (1 failed / 5 passed controls).
  Separate strict checks repaired it. Final frozen candidate: **86 passed**
  normally and **86 passed** with `GITHUB_ACTIONS=true`; full raw logs and
  JUnit are `handoff-pytest*`. These six identity tests use bounded synthetic Git
  responses, not a fabricated remote checkout or locally created commit.

Targeted actionlint 1.7.12 with the private custom-label config and shellcheck
both exited 0. No whole-central-suite/security acceptance is inferred.
Synthetic policy tests actually execute admission/process shells and the real
Node checker, including wrong caller/event, mutable/unpublished pin, stale or
symlink coverage, install/typecheck/Jest/export failures, serial SQL failures and
both native-platform malformed/missing/escaping-output controls. Synthetic tools
are labeled as such and are not actual application/DB execution.

Separately, the real central app process ran on a copied immutable snapshot of
canonical tracked + dirty source under scratch (684 input files): policy 70/70,
product actionlint/types, Jest 381 tests / 30 suites, 100% *configured pure-layer*
coverage, Android 1569 modules and iOS 1480 modules with real metadata/asset
postconditions; exit 0. App source/UI/device coverage is not 100% by this report.
The first environment probe rejected a non-24 Node; the second real run reached
70 policy passes but failed actionlint because the copy lacked Git metadata.
Both failures are retained. Adding disposable scratch Git metadata and explicit
Node 24 PATH allowed the unchanged script to pass; no source assertion weakened.

The real central server process separately exited 0 with PostgreSQL 18, types,
four unit entrypoints, actual RLS/WITH CHECK and auth/data-rights API integration.
A harness-only `mktemp` shim redirected the two unchanged product SQL fixtures'
legacy `/tmp` templates into a short approved scratch root to meet local workspace
rules and Unix socket-length limits. SQL, fixture code and process behavior were
not replaced. This is local macOS execution, not Linux runner acceptance.

Dependency deprecation/install-script approval warnings are retained in the raw
logs; no vulnerability/security clearance is claimed. npm caches and installs
were confined to scratch. Auth status reported an invalid keyring token, but the
actual REST read returned rate-limit HTTP 403 and authenticated GraphQL PR/Issue/
Project reads succeeded. No credential changes were made. Canonical product dirty
files were hash-inventoried before the scratch run and are rechecked at handoff.

## GYEOT-EXPORT-001 narrow repair

The previous 86-test candidate and reviewer artifacts remain historical evidence,
not acceptance of platform-root ownership. Independent review reproduced the
actual helpers accepting platform directories symlinked to foreign siblings:
`realpathSync(output_directory)` made the foreign directory the checker root;
the exit trap removed only the private root, leaving foreign metadata/bundles.

The repair first added Android and iOS regressions through the actual shell and
checker. Both unchanged helpers returned **0**, with foreign metadata/bundle bytes
surviving cleanup; both tests failed their required exit-1 assertion. Direct CLI
root-admission controls also returned 0 for missing owner, foreign output,
platform-root symlink, wrong platform child, aliased parent and symlink owner.
Combined RED: **14 failed / 2 ordinary-directory controls passed / 86 deselected**.
The initial Android RED stopped at the unexpected continued iOS command; a
subsequent assertion-order correction recorded both explicit exit-0 admissions
before implementation. Both raw RED logs are retained.

Only the export shell, checker, this test file and this document changed. The
checker receives the invocation's trusted private root and validates directory
identity with `lstat`, exact requested paths and resolved parent/child equality
before metadata reads. Existing bundle/asset reference checks and the private-root
cleanup trap are unchanged. Tests assert foreign bytes/sentinels remain intact;
no manual deletion of foreign files is performed.

GREEN: **102 passed** (the original 86 unchanged plus 16 new cases), normally and
with `GITHUB_ACTIONS=true`. Targeted actionlint using the existing private
`actionlint.yaml`, shellcheck on all three shell helpers and Node syntax checking
exited 0. Real Expo Android (1569 modules, 27 assets) and iOS (1480 modules,
23 assets) exports also passed the repaired shell/checker with existing installed
scratch dependencies, no reinstall; the invocation root was cleaned and the
runner sentinel survived. A separate repair-owned source copy reused the existing
scratch `node_modules` by symlink; this is local macOS export acceptance, not a
fresh dependency install, full app/server rerun, remote Linux run or security scan.

New evidence and final file SHA-256 manifest:
`/Users/seonghobae/.hermes/cache/scratch/gyeot-export-001-repair-evidence-20261008-192421558201/`.
Explicit `TMPDIR` and distinct pytest `--basetemp` paths stayed under Hermes scratch.
The checks are postconditions, not an adversarial write sandbox: a producer may
already have written foreign files before rejection. Synchronous path checks do
not prove immunity to concurrent directory replacement / TOCTOU. No workflow
admission, helper publication pin, routing, other-owner configuration, production
canonical file, commit, push or reviewer artifact was changed. Independent review
of these new exact hashes and all publication/remote gates remain outstanding.
