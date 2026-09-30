# Review sidecar venv on persistent runner temp

## Symptom

From 2026-09-27T17:47Z every `opencode-review` job that reached
"Provision contextual-orchestrator review sidecar" on `cwlab-s1-04` failed
within a minute:

```
.../_temp/contextual-orchestrator-review/.venv/bin/python: No module named pip.__main__; 'pip' is a package and cannot be directly executed
```

A 60-run GraphQL sample of dispatch runs from 2026-09-25 to 2026-09-29 shows
the step succeeding up to 2026-09-27T10:36Z and failing in all twelve runs
after that. No OpenCode verdict was published in that window, so every
required `opencode-review` check across the organization failed closed.

## Cause

#2437 (2026-09-27T12:40Z) made the sidecar create
`$RUNNER_TEMP/contextual-orchestrator-review/.venv` with `python -m venv`.
The script already wipes its vendored source directory before each run but
reused this one. The deterministic failure after that merge shows the
environment directory survived between jobs on `cwlab-s1-04`; the stock
runner normally empties `_temp` at job start, and why it did not here
(for example, a deletion error it only logs) was not observed.
`python -m venv DIR` over an existing environment whose `pip` package lost
`__init__.py`/`__main__.py` exits 0 and leaves `pip` as a namespace package,
which matches the production message. The first job that damaged the
environment was not identified: the provisioning-time cancellations found
between the last success and the first failure were dispatched before #2437
and ran the previous script.

Reproduced on Ubuntu 24.04 amd64 with the actions/python-versions
3.12.14 toolcache build at the self-hosted path: the damaged-then-rerun
case prints the exact error above; `--clear` restores a working pip.

## Repair

Create the environment with `python -m venv --clear`. The regression test
builds a real venv, removes pip's `__init__.py` and `__main__.py`, reruns the
script's venv line, and requires `python -m pip --version` to succeed. It
fails on unmodified main with the production message and passes after the
change.

## Not addressed here

Queue latency is a separate capacity problem: one OpenCode runner serves
three `needs`-chained jobs, and about half of sampled dispatches were stale
by the time they ran (median queue wait 2.4 h). This repair only restores
verdict publication.
