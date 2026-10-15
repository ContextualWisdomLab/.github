# Naruon central reusable CI suppliers — source candidate

## Source and ownership

This additive supplier lane starts at central commit
`58d12a9f1b46d611f75cfcf3e6c5a3fe19a55f96`. Its product workload reference is
`ContextualWisdomLab/naruon@042b0c70531b229af3acbd0421a2f23098d848b3`:
`.github/workflows/app-ci.yml` and `.github/workflows/bandit.yml`, read from
actual Git objects, not report placeholders. Parent composition owns publication,
consumer pinning, remote overlap checking, required-check reconciliation and merge.
Noema/OpenCode sources and their existing auto/LiteLLM owners are unchanged.

The three new workflows accept only `workflow_call`: no command/runner inputs,
no declared secrets and no `secrets: inherit`. Their jobs use only `CWL CI isolated`
with `[self-hosted, linux, x64, cwlab-ci-isolated]`; no privileged control pool or
GitHub-hosted fallback is present. The first step follows
`pg-erd-cloud-quality.yml`'s inline pre-checkout fixed-caller pattern. It rejects
foreign repositories, forks, foreign PR bases and `pull_request_target` before
any action or checkout. Checkout remains full-SHA pinned, selects the caller's event SHA (the synthetic PR
merge commit for pull-request validation) and sets `persist-credentials: false`. All action pins retain
the consumer's exact revisions and trailing version comments.

### Admission and concurrency

| Supplier | PR base branches | Push branches | Manual dispatch |
|---|---|---|---|
| backend/frontend | develop, master, release/** | develop, master | rejected (application predecessor has none) |
| Bandit | develop, master | develop, master | develop/master only |

Same-repository stacked PRs are admitted when their base matches the existing
branch contract. Bandit's formerly unfiltered manual dispatch is deliberately
narrowed to the maintained develop/master refs, matching the fixed-ref admission
boundary rather than permitting arbitrary branch code on self-hosted capacity.
Keep `application-ci-${{ github.event.pull_request.number || github.ref }}` and
`cancel-in-progress: true` in the application caller. Suppliers add no concurrency
namespace that could cancel their caller. Do not activate an unpublished SHA or
mutable-branch supplier ref.

## Preserved workloads and thresholds

- **Backend:** Python 3.14, existing pip cache/dependency path, core hash-locked
  dependency install, second combined core+optional agent hash-locked install,
  `python -m ruff check .`, and `python -m pytest -q` through `tee` with pipefail.
  `PYTHONWARNINGS=error`, `DISABLE_BACKGROUND_WORKERS=1`, and the case-insensitive
  `timeout|fatal|warn|denied` output rejection remain unchanged. No agent dependency
  is omitted or replaced with a skip.
- **Frontend:** Node 24, pnpm 11.5.3 from the product packageManager contract,
  frozen lock install, full tests, lint, exact Next.js cache key/restore key,
  build, `playwright install --with-deps chromium`, and `full:smoke` against
  `http://127.0.0.1:3001`. All original build resource flags remain. No typecheck,
  test filter, substitute browser or reduced smoke is substituted.
- **Bandit:** Python 3.14, unchanged hash lock, exact
  `bandit -r backend/ -x backend/tests/ -f sarif -o bandit-results.sarif`, unchanged
  severity/default exit policy and SARIF category. Scanner findings remain
  blocking. Upload still uses `always()` after successful admission, including
  failed scans; a rejected caller cannot run the post-admission uploader.

## Necessary self-hosted exceptions

Exact workload preservation is not an arbitrary exact-step-count requirement.
The reference has backend 7, frontend 11 and Bandit 6 steps. Safety preparation
adds steps and groups Python commands inside one shell, preserving their order
and terminal failures rather than installing into shared Python.

1. **Private Python:** backend and Bandit allocate unique mode-private RUNNER_TEMP
   roots, venvs, HOME and TMP/TMPDIR/TEMP, unset inherited Python path overrides,
   disable pip configuration/cache reuse for installs, and clean their root on
   EXIT, including nonzero tool exits. The existing setup-python pip cache
   declaration remains, but candidate dependency installs never use shared Python.
2. **Owned HOME and browser output:** frontend exports a unique HOME, temporary,
   npm cache, Corepack prefix and Playwright browser directory. It selects
   `NARUON_FULL_PRODUCT_SCREENSHOT_PROFILE=/tmp/naruon-full-product-smoke`, a
   supported **profile identifier**, not an output pathname. The exact consumer's
   `createFullProductArtifactDirectory` uses `mkdtemp` beneath `os.tmpdir()`;
   private TMPDIR places the actual uniquely named artifacts under the job root.
   The legacy `NARUON_FULL_PRODUCT_SCREENSHOT_DIR` arbitrary-directory export is
   removed. The predecessor's shared-home deletion `rm -f ~/package-lock.json`
   is replaced by `rm -f -- "$HOME/package-lock.json"` inside that owned HOME.
   No shared-home file is deleted or fixed `/tmp` artifact directory written.
   Always-cleanup uses the exact runtime output plus the owned-root name pattern;
   empty outputs are a no-op and foreign paths are refused. Cleanup preserves
   unrelated runner files on success and failure. Abrupt runner loss still
   requires disposable-runner reclamation; shell cleanup is not isolation proof.
3. **Prerequisite order:** Node 24 is installed with package-manager caching
   disabled first. A real executable Corepack prerequisite is required next;
   missing Corepack, Node mismatch, preparation failure or pnpm mismatch fails
   explicitly. Corepack creates pnpm shims in the private prefix, activates
   11.5.3 and publishes that prefix through GITHUB_PATH. Only then does the
   original setup-node pnpm-cache action execute. No unpinned npm-install
   fallback or borrowed runner is supplied.
4. **Cache post lifecycle:** the pinned setup-node action discovers the pnpm
   store by `pnpm store path --silent` and saves its stored paths in its post-job
   action. `PNPM_CONFIG_STORE_DIR` selects `.naruon-pnpm-store` in the job's
   checkout; pnpm 11.5.3 does **not** recognize `npm_config_store_dir` for this
   setting. After version admission, before setup-node's cached action, the
   workflow executes the real store-path command from the checkout root and
   explicitly refuses an empty, foreign or traversal path outside that cache
   root. Command failure remains terminal. The discovered versioned store
   survives HOME cleanup through setup-node post, like preserved `.next/cache`;
   the disposable runner must reclaim checkout bytes after all action posts.
   Private HOME/browser/tmp files are removed at terminal cleanup. This is
   cooperative pathname admission, not a defense against malicious same-UID
   symlink replacement or a proof of a completed Actions cache post.
5. **Temporary-root admission:** nonsymlink, canonical RUNNER_TEMP is checked
   explicitly before allocation. A rejected symbolic-link root reaches no
   workload tool. This is a cooperative filesystem boundary, not protection
   against same-UID malicious peers on a shared host.
6. **Persistent Node environment:** frontend defaults to `NODE_ENV=test` and
   scopes `NODE_ENV=production` to build, so inherited production settings cannot
   remove test development dependencies. There is no failure suppression.

The predecessor safety probes reproduce missing venvs, shared-home deletion,
fixed screenshot path and the absence of a prior Node bootstrap. Those probes
were retained as additional predecessor characterization; the actual supplier
missing-file RED was observed before supplier implementation. Additional
supplier regressions observed RED before their fixes for SARIF admission and
symlink RUNNER_TEMP. The original cache-post probe fabricated a directory from
an unsupported environment key and did not establish pnpm behavior; it is
superseded, not counted as native evidence. Independent review identified two
frontend defects in that 78-case candidate. This successor observed the exact
consumer's approved-profile exception before fixing the export, the native
pinned pnpm HOME-store discovery before changing to `PNPM_CONFIG_STORE_DIR`,
and five false-success store-admission controls before adding the guard.
Additional approved/invalid profile and native pnpm-prefix controls are
first-GREEN characterization, not new product RED claims.

## Local acceptance and unresolved execution gates

Executed logs, JUnit, exact consumer snapshots, source hashes, full additive diff
and command receipts are under the implementation report packet supplied by the
parent. The permanent contracts execute the actual admission and workload shell
bytes with inert tool adapters, checking command order, real shell exit
propagation, strict output rejection, directory custody, missing prerequisites
and cleanup. The screenshot contracts execute byte-verified declarations from
`full-product-ui-smoke.mjs` with native Node filesystem APIs; they do not run
its server, browser or routes. The store contracts execute locally provisioned
pnpm 11.5.3 (retained bundle SHA-256
`db24b8f44a6438e100eab2e690464b971d35ee3c9af4638dcab3af7ee90c8cdd`),
not a fabricated store path. Node24 and that pnpm executable must be on PATH;
missing prerequisites fail instead of downloading or skipping. This hash binds
the inspected retained distribution, not independent registry provenance.
Product dependencies/tests, Playwright installation, setup-node cache transport
and GitHub SARIF APIs remain unexecuted in this offline repair lane.

Actionlint validates all three supplier files. The historical 78-case supplier
cohort passed despite the two defects. The successor preserves all 78 identities,
strengthens the old cache-store oracle and adds 15 cases (93 total), under
network-denied, minimal secret-free environment with warnings fatal. The repair
packet binds argv/environment, native exits, raw logs, JUnit and before/after
source hashes; final normal and `GITHUB_ACTIONS=true` results are recorded there.
The combined successor cohort has 197 cases: 195 pass and the same two inherited
failures remain, so it is **NONPASS**. The inherited 104-case cohort and exact-base
reproduction remain preserved in the predecessor packet: k-csap's existing list
runner selector is rejected by the all-runner oracle, and Noema's publication
permission test expects read rather than write. Neither owner is edited or waived.
No whole-repository suite, hosted execution or approval is claimed.

An additional real local Corepack run installs/activates pnpm 11.5.3 in a private
prefix and exits 0. This is macOS prerequisite evidence, not Linux/x64 runner
parity or Actions execution. Publication must still establish:

- Naruon repository and reusable-workflow access to the isolated group;
- an actual disposable Linux/x64 runner assignment and canonical temporary root;
- supported Actions runner/Node24 runtime and setup-python toolcache access;
- preprovisioned executable Corepack (Node 24 bootstrap alone is not proof);
- package/scanner/browser installation egress, Playwright Linux libraries and
  the existing `--with-deps` privilege contract on isolated capacity;
- successful unchanged product workloads, cache posts, SARIF and full cleanup;
- independent exact-head review, formal approval and protected merge.

No secrets were read, no remote was mutated and no commit/push/merge was
performed in this supplier lane. Source-contract GREEN cannot close these
operational gates.

## Primary source references

- `pg-erd-cloud-quality.yml` and `test_pg_erd_quality_workflow.py` at the exact
  central base provide the fixed-caller/private-venv pattern.
- Naruon app/Bandit workflows and frontend/package.json at the exact consumer
  SHA provide workload, action and package-manager requirements.
- `actions/setup-node@820762786026740c76f36085b0efc47a31fe5020`:
  `src/cache-utils.ts`, `src/cache-save.ts` and `action.yml` provide the cache
  discovery/post lifecycle and Node24 action-runtime contract. Exact copies are
  retained in the implementation packet.

## 2026-10-15 checkout parity repair

The original supplier explicitly selected the PR head while the product's
`app-ci.yml` and `bandit.yml` retained checkout's event default. That silently
changed integration validation to head-only validation. All three suppliers now
select `github.sha`, preserving the PR merge commit, push commits, and Bandit-only manual event commits.
The parsed-workflow regression failed for all three predecessors before repair.
No caller activation, runner admission, credential or required-check change is
included. Runtime parity and exact-head checks remain independent acceptance
requirements.

Source: GitHub, [Events that trigger workflows: pull_request](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request).

Validation: the changed checkout/admission cohort passes 36 cases with
`GITHUB_ACTIONS=true PYTHONWARNINGS=error python -m pytest
tests/test_naruon_reusable_ci_contract.py -q -k
'fixed_isolated_runner or actual_precheckout_admission'`. actionlint passes all
three supplier workflows. The complete supplier cohort reports 88 passed and
5 failed both before and after this repair in the same environment: five native
pnpm tests require the unavailable exact pnpm 11.5.3 installation layout. This
is not a full-suite pass; the existing pnpm provisioning and pip-cache review
findings remain open.
