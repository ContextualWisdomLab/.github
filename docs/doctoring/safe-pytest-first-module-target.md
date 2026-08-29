# Safe pytest first-module-target binding

## Incident and buyer impact

`scripts/ci/safe_pytest_command.py` discovers pytest commands from `ci.yml`
and executes them with `shell=False`. Flag-tolerant matching treated any later
`-m pytest` pair as sufficient, so `python attacker.py -m pytest` and
`coverage run attacker.py -m pytest` were classified as pytest. A
pull-request-controlled workflow line could therefore execute a file the
reviewer never approved as the test runner.

## Decision

The first execution target after recognized interpreter or `coverage run`
flags must be `-m`/`--module pytest`. Versioned interpreters matching
`python3.<digits>` (the CI pins `python3.12` / `python3.13` / `python3.14`)
are the same runner class as `python3`. `python -m coverage run … -m pytest`
remains allowed because the first `-m` is `coverage` and `run` then invokes
pytest. File operands, `-c`, `--`, and earlier modules fail closed.

The security boundary is the locally demonstrated `shell=False` execution,
first-module-target binding, and the regression tests in
`tests/test_safe_pytest_command.py`. A file operand before `-m pytest`
therefore cannot become the test runner under this parser's contract.
