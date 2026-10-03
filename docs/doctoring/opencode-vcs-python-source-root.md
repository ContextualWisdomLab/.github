# OpenCode immutable VCS `python/` source-root RCA

Status: **Source repaired on protected `main` via #2123 (`ebc69a401`); image-path resolver extracted and contract-proven under #2157 follow-up.** Hosted consumer `coverage-evidence` past docker step #17 remains the issue-closure gate when a post-merge run is linked.

## Incident and user-visible failure

On 2026-09-12 UTC, central OpenCode dispatch [run 34701472466](https://github.com/ContextualWisdomLab/.github/actions/runs/34701472466) validated `ContextualWisdomLab/contextual-orchestrator#1149` at exact head `684cf28fa59e800c0db4886a08f25dd2edd156fc`. Its `coverage-source-tree` job succeeded, but `coverage-evidence` job `103574547257` failed while building the trusted tool image, before any pull-request test or coverage command ran. OpenCode therefore published only a non-approving COMMENTED review, and the required receipt remained fail-closed.

The failing dependency was the exact VCS pin `fast-mlsirm@09f762ded35786dd1078222a4577ff09d649816f` from the consumer's validated `pyproject.toml`. That commit contains `python/fast_mlsirm/__init__.py`; it does not expose the import package at repository root or under `src/`.

## Root cause and boundary

`opencode-review-dispatch.yml` enumerated only four trusted candidates: `src/<import>`, `src/<import>.py`, `<import>`, and `<import>.py`. The materializer had already authenticated the target repository, bound the dependency to an immutable commit, fetched that commit without tags, and verified `FETCH_HEAD` and `HEAD`; the failure was solely an incomplete source-layout contract in the central owner.

#2123 added only `python/<import>` and `python/<import>.py`, then mapped a match to the repository's `python/` directory. It preserved the invariant that exactly one candidate may exist and continued to reject symlinked/namespace imports, any symlink layout, compiled extensions, installed distribution metadata, and ambiguous roots. It did not infer arbitrary paths from untrusted packaging metadata and did not execute dependency lifecycle code.

The #2157 follow-up extracts that same admission logic into
`scripts/ci/resolve_opencode_base_vcs_import_root.sh`, which the coverage Dockerfile
`COPY`s and executes. Offline fixtures in
`tests/test_opencode_vcs_python_source_root_contract.py` prove the `python/` layout
succeeds, `src/` and root layouts still succeed, and missing/ambiguous/namespace/compiled
trees still fail closed — so the image-path algorithm no longer depends solely on an
untested HEREDOC.

Rejected alternatives were: changing the consumer's valid immutable dependency pin; copying `fast-mlsirm` into the consumer; adding the whole repository to `PYTHONPATH`; recursively searching for a matching directory; or weakening/bypassing the OpenCode coverage gate. Each would move ownership, admit ambiguity, or hide the central defect.

## RED → repair → verification gate

- RED commit `b1fe97c477b56e148afbeeaed9a6b74338994b6b` requires both package and single-module `python/` candidates in the published workflow contract.
- Repair commit `af04581cea4ffc038c881c6ad101ea3e5842a664` adds those candidates and the corresponding `python_root` mapping.
- Hosted Runtime Quality [job `103581110552`](https://github.com/ContextualWisdomLab/.github/actions/runs/34704176931/job/103581110552) then failed the independent pairing contract because the changed workflow blob `f315683208d57ba89a2942502c525abe7355e2fd` no longer matched the reviewed predecessor pin. Commit `683cb053b3c6f1c7b3f293a74263ac9b13e9bdf1` advances only that exact pin; no hash check is removed or relaxed.
- #2123 merged to protected `main` as `ebc69a401` (2026-09-13).
- #2157 follow-up moves the resolver into `scripts/ci/resolve_opencode_base_vcs_import_root.sh` with executable fixtures and re-pins `REVIEW_DISPATCH_BLOB_SHA`.

## Follow-up

Rerun only consumer failures whose cause changed, beginning with `contextual-orchestrator` PRs that previously died at step #17. Verify that the trusted image builds from the same `fast-mlsirm` commit, the PR sandbox remains networkless and credential-free, coverage/docstring evidence executes, and a substantive exact-head review is published. Link that `coverage-evidence` job on #2157 before closing the issue. If any additional conventional source root is needed, add it through its own immutable fixture and one-root regression rather than generalized path discovery.
