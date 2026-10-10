# CGC central CI producer — source and activation boundary

The reusable workflow is `.github/workflows/context-graph-contracts-ci.yml` in the organization `.github` repository. It is **only** `workflow_call`; this source staging neither calls it from ContextualWisdomLab/context-graph-contracts nor enables an organization required-workflow ruleset, provisions a runner, or proves a hosted run. A separate, reviewed caller/activation must select this reusable workflow. No `workflow_dispatch`, caller inputs, `secrets: inherit`, executable caller path, or hosted-runner fallback is exposed. Its isolated runner group is `CWL CI isolated` with labels `self-hosted`, `Linux`, `X64`, `cwlab-ci-isolated`; unavailable runners leave the checks queued instead of silently substituting a hosted runner.

Before **each** checkout, an executable shell admission step requires exact `ContextualWisdomLab/context-graph-contracts`, an event of `push` or same-repository `pull_request`, and a lowercase 40-hex candidate SHA. Any fork, missing head repository, wrong repo, other event, or malformed SHA fails before candidate checkout. Checkouts explicitly bind repository and `github.event.pull_request.head.sha || github.sha` with `persist-credentials: false`; jobs verify the checked-out head (both heads for the reproducibility job). Scope is caller-repository read-only permissions. This does **not** prove that a push SHA belongs to a particular protected ref; it is validation, not release authorization.

The producer carries the product source's five non-signing jobs (product source `c2f9802e47c1722773f038a4c68be8d59bda6538`):

| Central job | Source job / gate |
|---|---|
| `test` | `ci.yml`: Python 3.11–3.14, pinned setup-python and uv 0.11.32, lock/sync, compileall, Ruff, tests and coverage; coverage report explicitly enforces 100% |
| `package` | `ci.yml`: wheel/sdist resource assertions, offline installed-wheel schema/conformance/fixture checks and installed conformance commands |
| `installed-wheel` | `receipt-package-smoke.yml`: installed Context Assertion admission, bundle and complete release-evidence smoke |
| `release-package-reproducibility` | `reproducibility.yml`: two exact-source clean checkouts, fixed source epoch, byte comparison and checksum artifact |
| `package-evidence` | `supply-chain.yml`: independent reproducibility witness, installed-wheel SPDX 3.0.1 SBOM, checksum and package-evidence verifier |

Actions are pinned to the product's exact revision. Builds retain source lock and verified evidence artifacts only on successful producers (`if-no-files-found: error`). Workspace-owned outputs are removed after admission, before checkout, and in a final step gated by successful private initialization. Pre-checkout cleanup never deletes an inherited `PRIVATE_ROOT`. Per-job uv/TMP/cache state and a fresh HOME/config directory are mode 0700 under canonical `RUNNER_TEMP`; inherited `PYTHONPATH`, `PYTHONHOME`, and `PYTHONOPTIMIZE` are cleared and user site imports disabled. Final private cleanup accepts only a direct, nonsymlink `cgc-ci.` directory with the initializer's eight-character suffix; traversal and nested paths fail closed. These guards do not provide protection against a concurrent hostile process changing filesystem names or candidate code rewriting Actions environment files.

Installed package/receipt smoke invokes both Python and console entrypoints through the installed venv interpreter with `-I`, preserving all original semantic assertions while excluding cwd/PYTHONPATH source leakage. The result-only `required` job (`CGC required validation`) runs with `always()` and requires literal `success` from all five producers; failure, skipped, cancelled, or missing results cannot pass. It performs no checkout or candidate execution. Concurrency remains caller-only.

The product's protected-main `attest-protected-main` signing job is intentionally **not** moved: this producer grants no `id-token`, attestation, release-environment, or write permissions. Existing product CI and its protected release authorization are not replaced or disabled by this file alone.

## Offline verification and limitations

From the central repository root, run `env -u PYTHONPATH python3 -m pytest tests/test_context_graph_contracts_ci_contract.py -q` to execute parsed admission, private initialization/cleanup, source-poisoning and aggregate result regressions. Run actionlint without ignores using the actual custom label catalog:

```sh
actionlint -config-file /Users/seonghobae/.hermes/cache/scratch/cgc-ai-review-auto-20261008/actionlint-labels.yaml .github/workflows/context-graph-contracts-ci.yml
```

Local macOS replay against an archive of product `c2f9802` exercised the actual package and installed-wheel shell blocks, including wheel/sdist resource inspection, offline installation, installed module-origin checks, conformance, bundle and complete release-evidence semantics. The product test lane passed 794 tests with 2,168 statements and 660 branches at 100% on Python 3.14.7 using uv 0.11.32 and the frozen lock. This does not establish Python 3.11–3.13 or Linux acceptance, real Anchore SBOM generation, artifact uploads, runner registration/isolation, checkout action lifecycle, release signing, or hosted CI execution.

The local full central suite returned 9 failures, 5,190 passes, 4 skips and 40 passing subtests before the additional runner-alias regression. All nine failures reproduced in the same three modules from the exact central baseline archive: two date-sensitive CodeQL coverage checks, two local OpenCode gateway integration checks with no request observed, and five isolation-path checks rejecting scratch paths under the host HOME. No unrelated repairs or criteria reductions were made. Full central coverage has not been cleared. Independent exact-byte review and a formal App approval remain separate from this repair; no approval, activation or merge is inferred from local passes.
