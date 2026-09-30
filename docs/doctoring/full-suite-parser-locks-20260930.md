# Full-suite parser dependency admission

## Incident

At protected `main@37b10243cec3d160ecc9c1be75c71428b160a703`, the common
OpenCode quality lock did not install the parsers imported by repository test
collection. Agent Mention Router Quality run
[36443475158](https://github.com/ContextualWisdomLab/.github/actions/runs/36443475158)
and source-repair run
[36443475290](https://github.com/ContextualWisdomLab/.github/actions/runs/36443475290)
reported `ModuleNotFoundError: No module named 'defusedxml'` and 13 collection
errors. The newer main additionally has four workflow tests importing `yaml`.
These are environment failures before test execution, not product findings or
passing coverage measurements.

## Repair boundary

The shared tooling input reuses `requirements-noema-document-ci.txt` for the
existing `defusedxml==0.7.1` pin and adds the existing security-tooling
`PyYAML==6.0.3` pin. The generated lock is rebuilt only with
`./scripts/ci/compile_opencode_review_lock.sh` (Python 3.14, Linux target,
`--upgrade`, hashes). The required upgrade also resolves Hypothesis 6.168.3
instead of 6.168.0. No hashes are edited by hand.

Installing the entire Bandit lock alongside this lock is not the repair: their
Pygments pins differ. The common quality environment instead resolves its own
complete, consistent dependency closure. Hash checking remains mandatory.
PyYAML's repository reports MIT. GitHub reports NOASSERTION for defusedxml,
so its installed hash-pinned 0.7.1 wheel's LICENSE was read directly and confirms
Python Software Foundation License Version 2; a missing SPDX detection is not
interpreted as missing permission.

A contract regression requires both parser packages in the installed lock.
RED: one failing test because both packages were absent. GREEN: 36 tests passed
and two optional document-format tests skipped after hash-locked installation.
The full repository suite is a separate verification step, not implied by that
focused result.

## Verification environment

The first YAML-present full run on source-repair head `deb47f8db` finished with
5,232 passed, seven failed, five skipped and 40 subtests passed. Two failures
were a locally unseeded virtualenv lacking pip; five used pytest temporary
paths beneath the host home, which the sandbox correctly refuses. Installing
project-pinned pip 26.2.1 and using an isolated `/tmp` basetemp made all seven
reproductions pass. These local environment corrections do not weaken sandbox
validation and are not changes to production code.

Source-repair's own two scripts separately measured 100% statement/branch
coverage and 100% docstrings. Neither those measurements nor the parser repair
constitute hosted exact-head approval or merge authorization.

## Consumers and limits

Quality workflows install `requirements-opencode-review-ci-hashes.txt` directly.
The central OpenCode coverage image also consumes it in
`.github/workflows/opencode-review-dispatch.yml`, together with the existing
Noema document lock. No exact-head fast-mlsirm Noema HTTP 400 or Strix report
scope failure is claimed resolved by this dependency change. Those incidents
require their own current-head transport/report evidence and independent review.

## References

Python Packaging Authority. (n.d.). *Secure installs*. Retrieved September 30,
2026, from https://pip.pypa.io/en/stable/topics/secure-installs/

The pip documentation requires every dependency in hash-checking mode to be
pinned and hashed. The repair preserves that contract rather than adding an
unhashed installation fallback.
