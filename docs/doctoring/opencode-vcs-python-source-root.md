# OpenCode immutable VCS `python/` source-root RCA

Status: **Proposed** — source repair exists on an open pull request; it is not protected-branch authority until merged.

## Incident and user-visible failure

On 2026-09-12 UTC, central OpenCode dispatch [run 34701472466](https://github.com/ContextualWisdomLab/.github/actions/runs/34701472466) validated `ContextualWisdomLab/contextual-orchestrator#1149` at exact head `684cf28fa59e800c0db4886a08f25dd2edd156fc`. Its `coverage-source-tree` job succeeded, but `coverage-evidence` job `103574547257` failed while building the trusted tool image, before any pull-request test or coverage command ran. OpenCode therefore published only a non-approving COMMENTED review, and the required receipt remained fail-closed.

The failing dependency was the exact VCS pin `fast-mlsirm@09f762ded35786dd1078222a4577ff09d649816f` from the consumer's validated `pyproject.toml`. That commit contains `python/fast_mlsirm/__init__.py`; it does not expose the import package at repository root or under `src/`.

## Root cause and boundary

`opencode-review-dispatch.yml` enumerated only four trusted candidates: `src/<import>`, `src/<import>.py`, `<import>`, and `<import>.py`. The materializer had already authenticated the target repository, bound the dependency to an immutable commit, fetched that commit without tags, and verified `FETCH_HEAD` and `HEAD`; the failure was solely an incomplete source-layout contract in the central owner.

The selected repair adds only `python/<import>` and `python/<import>.py`, then maps a match to the repository's `python/` directory. It preserves the invariant that exactly one candidate may exist and continues to reject symlinked/namespace imports, any symlink layout, compiled extensions, installed distribution metadata, and ambiguous roots. It does not infer arbitrary paths from untrusted packaging metadata and does not execute dependency lifecycle code.

Rejected alternatives were: changing the consumer's valid immutable dependency pin; copying `fast-mlsirm` into the consumer; adding the whole repository to `PYTHONPATH`; recursively searching for a matching directory; or weakening/bypassing the OpenCode coverage gate. Each would move ownership, admit ambiguity, or hide the central defect.

## RED → repair → verification gate

- RED commit `b1fe97c477b56e148afbeeaed9a6b74338994b6b` requires both package and single-module `python/` candidates in the published workflow contract.
- Repair commit `af04581cea4ffc038c881c6ad101ea3e5842a664` adds those candidates and the corresponding `python_root` mapping.
- Hosted current-head tests, security, CodeQL, and independent review remain required. Only after ordinary protected-main integration may affected consumers rerun OpenCode; the predecessor run is never transferable as GREEN evidence.

## Follow-up

After merge, rerun only consumer failures whose cause changed, beginning with `contextual-orchestrator#1149`. Verify that the trusted image builds from the same `fast-mlsirm` commit, the PR sandbox remains networkless and credential-free, coverage/docstring evidence executes, and a substantive exact-head review is published. If any additional conventional source root is needed, add it through its own immutable fixture and one-root regression rather than generalized path discovery.
