# GitHub REST URL authority boundary for central CI clients

Status: Proposed repair for `.github` issue #2248; exact-head hosted security and independent review remain mandatory.

## Problem

Protected `.github/main` at `64aa08d7fa487deacd41c761c36277ca68cab6c9` contains two central CI HTTP clients:

- `scripts/ci/codeql_ghas_configuration_identity.py` for CodeQL analyses;
- `scripts/ci/strix_evidence_binding.py` for pull-request changed-file evidence.

The whole-tree Semgrep gate reported `python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected` at both original dynamic `urlopen` sites, and Bandit B310 reported the same class. A comment-only suppression would not prove the security premise that bearer-authenticated requests stay inside GitHub REST authority.

The first repair made the initial URL predicate executable, but exact-head CodeRabbit review then identified a second authority transition: Python's default `HTTPRedirectHandler` can construct a redirected request from the already-authorized request and preserve request headers, including `Authorization`. Validating only the first `https://api.github.com/...` URL therefore did not prevent a 3xx response from redirecting the bearer token to another authority.

## Initial URL RED → repair

Structural RED `4732f3e29ab8cd0b88506beecd4e70bdfaafb8da` requires both clients to reject, before network/file opener execution:

- `http://api.github.com/...`;
- `https://api.github.com.evil.example/...`;
- `https://api.github.com@evil.example/...`;
- `https://api.github.com:443/...` because the canonical authority is exact;
- an otherwise canonical URL carrying a fragment;
- `file:///etc/passwd`.

The production predicate requires scheme exactly `https`, network authority exactly `api.github.com`, an absolute path, and no fragment. The positive control proves exact `https://api.github.com/...` reaches the injected opener and decodes JSON normally.

A temporary shared helper candidate was removed because `codeql-scan-dispatch.yml` materializes `codeql_ghas_configuration_identity.py` into `$RUNNER_TEMP` and executes it as a standalone file. The CodeQL helper therefore keeps its small fail-closed transport boundary self-contained instead of gaining a repository-local import dependency that the workflow does not materialize.

## Redirect RED → repair

CodeRabbit's current-head review of `9ba43f284da51bfa6aaa389d3fb67f8b232fbba5` correctly rejected the initial-only guard: default `urllib` redirect handling can create a new request after the first authority check and carry the bearer header to the new target.

Structural redirect RED `7a00442cbfd01408068a060c2bebba84041a33eb` adds hostile redirect targets for a lookalike HTTPS host, `http://api.github.com/...`, and `file:///...`. The contract requires both clients' redirect handlers to return no redirected request while the original request retains its bearer header; the repair also blocks same-authority redirects so there is no unreviewed second authority transition at all.

Production repair lineage:

- `a2e9126416c96bb8c5fa1e00190a8eca45758883` replaces CodeQL's default `urlopen` transport with a local `OpenerDirector` whose `_RejectRedirects` handler refuses every redirect;
- `4c7bcbeb06e421b98b0992b62cac06eaae45a98c` applies the same fail-closed boundary to the Strix evidence client;
- `e06b6dd84b012db9c3fafc09d417a85f4aaeff4c` binds the hostile and positive-control tests to the actual no-redirect openers and includes same-authority redirects in the refusal contract.

The redirect repair removes the two dynamic `urlopen` sinks rather than broadening a Semgrep/Bandit suppression. A 3xx response now terminates as the opener's HTTP error path; no second request object is created and the bearer credential cannot be forwarded by redirect machinery.

## Alternatives rejected

Broad Semgrep/Bandit suppression, path exclusion, or threshold weakening were rejected because they hide unrelated findings. Revalidating only the final response URL was rejected because the unauthorized network contact would already have occurred. Preserving redirects while stripping only `Authorization` was rejected because the client would still contact a target outside the stated GitHub REST authority. A custom redirect-following policy was unnecessary for these CI reads; blocking redirects entirely is the smaller authority surface.

## Evidence and acceptance

Primary scanner rule inspected at Semgrep rules revision `40b8c63f75dc7c22c8a77482d73bfb864b146f7e`: `python/lang/security/audit/dynamic-urllib-use-detected.yaml`. Python stdlib `HTTPRedirectHandler` behavior was inspected during review because redirect construction is the second network-authority decision that the original source predicate did not control.

Acceptance requires all of the following on the exact PR head:

1. `tests/test_github_api_url_boundary.py` passes initial hostile-authority, redirect-refusal, and canonical positive-control cases for both clients;
2. existing CodeQL GHAS identity and Strix evidence-binding suites remain green;
3. Semgrep and Python/Bandit no longer report the #2248 baseline findings and introduce no replacement Medium+ finding;
4. no security rule, path, threshold, or required check is weakened;
5. independent current-head review confirms redirects cannot create a second request carrying the bearer token;
6. the standalone `$RUNNER_TEMP` CodeQL materialization contract remains intact.

Hosted exact-head evidence is mandatory. Source inspection, structural RED/repair lineage, and review comments are not substitutes for repository/security GREEN.
