# GitHub REST URL authority boundary for central CI clients

Status: Proposed repair for `.github` issue #2248.

## Problem

Protected `.github/main` at `64aa08d7fa487deacd41c761c36277ca68cab6c9` contains two central CI HTTP clients that pass dynamic `urllib` request objects to `urlopen`:

- `scripts/ci/codeql_ghas_configuration_identity.py` for CodeQL analyses;
- `scripts/ci/strix_evidence_binding.py` for pull-request changed-file evidence.

The whole-tree Semgrep gate reports `python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected` at both sites, and Bandit B310 reports the same dynamic-URL class. The existing Strix call carried only a Ruff/flake8 `# noqa: S310`, which is not a Bandit or Semgrep suppression. This baseline finding blocks otherwise unrelated central PRs, including #2271 and stacked #2275.

The scanner warning is syntactic, but simply suppressing it would not prove the security premise that both clients are restricted to GitHub HTTPS. The repair therefore makes that premise executable first and binds narrowly scoped scanner annotations to the proven call sites.

## Structural RED

Commit `4732f3e29ab8cd0b88506beecd4e70bdfaafb8da` adds `tests/test_github_api_url_boundary.py`. Each client must reject these authorities before the opener can run:

- `http://api.github.com/...`;
- `https://api.github.com.evil.example/...`;
- `https://api.github.com@evil.example/...`;
- `file:///etc/passwd`.

The predecessor has no such authority predicate, so the contract is intentionally RED there. Positive production URLs remain `https://api.github.com/...`.

## Minimal production repair

`codeql_ghas_configuration_identity.py` and `strix_evidence_binding.py` now validate the parsed URL before building or opening a request. The invariant is:

- scheme exactly `https`;
- network authority exactly `api.github.com`;
- absolute path present;
- no fragment.

Only after that predicate succeeds may the dynamic `urllib` call execute. The retained `nosemgrep`/`nosec B310` annotations are attached only to those proved call sites; they do not disable either rule repository-wide or exclude `scripts/ci` from scanning.

A temporary shared helper candidate was created in `31b9b9c57da96c16b447e9678d4b589daf410221` and removed by `93282660d5f57dbd351eb0acfbe32dd788ce389c`. The CodeQL helper is fetched by `codeql-scan-dispatch.yml` into `$RUNNER_TEMP` and executed as a standalone file, so a new repository-local import would create a runtime dependency that the workflow does not materialize. Keeping the small fail-closed predicate local to each executable boundary avoids that mutable/import coupling.

## Alternatives rejected

Broad `--exclude-rule`, directory exclusion, Bandit-wide B310 skip, or accepting the warning were rejected because they weaken unrelated security coverage. A comment-only suppression was rejected because it would encode the assumption without proving the runtime authority. Replacing these callers with another HTTP client was also rejected: that changes transport behavior without addressing the bounded authority contract.

## Evidence and acceptance

Primary scanner rule inspected at Semgrep rules revision `40b8c63f75dc7c22c8a77482d73bfb864b146f7e`: `python/lang/security/audit/dynamic-urllib-use-detected.yaml`. The rule flags dynamic urllib targets because urllib can handle non-HTTP schemes and does not model this application-specific authority predicate.

Acceptance requires all of the following on the exact PR head:

1. `tests/test_github_api_url_boundary.py` passes for both clients;
2. existing CodeQL GHAS identity and Strix evidence-binding suites remain green;
3. Semgrep and Python/Bandit security gates no longer report the two #2248 baseline findings;
4. no other Medium+ finding is suppressed by this change;
5. independent review confirms the URL predicate cannot be bypassed through userinfo, lookalike hostnames, non-HTTPS schemes, fragments, or alternate URL schemes.

Hosted exact-head evidence is mandatory. Source inspection and the structural RED/repair lineage are not substitutes for repository/security GREEN.
