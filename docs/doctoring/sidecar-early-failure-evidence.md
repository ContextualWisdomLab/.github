# Sidecar evidence after an early failure

## Observed failure

On 2026-09-27, Strix job `108516387538` in run `36261129443` for
`.github#2111` failed during dependency installation, before model work.
Its self-hosted runner was `1061765`. The compiler reported
`fatal error: Python.h: No such file or directory` for Python 3.13.
The setup action reported its installation under the runner's `_work/_tool`
cache, while the compiler referenced `/opt/hostedtoolcache`. Inspecting the
runner's installed headers and Python build configuration is still necessary
before changing its deployment; no provider failure is established here.

The uploaded `strix-reports` artifact included a prior sidecar response lasting
1,419,683.4 ms, although this job lasted 59 seconds. That response cannot prove
this job's provisioning succeeded. Raw logs were inspected locally without
publishing provider bodies or credentials.

## Repair

The shared sidecar shell now resets its six named evidence outputs before
credential admission or dependency installation. It also resets the three
producer-owned staging reports copied by the failure publisher, so a launcher
exit cannot restore older discovery, catalog, or policy evidence. Previously, early failures
occurred before log/preflight initialization and could leave older discovery,
catalog, policy, and log files in a reused self-hosted workspace.

Only these producer-owned outputs and staging reports are reset. Unrelated workspace files are
preserved, symbolic links or non-regular output paths fail closed, and file creation
keeps the private umask inside a subshell. Empty reports mean unavailable
current evidence; they are not successful readiness or model evidence.
No provider route, model deadline, credential authority, or runner policy changes.

## Verification

`tests/test_sidecar_early_failure_evidence.py` executes the actual shell against
pre-seeded older outputs. Credential failure and dependency failure must leave
all six outputs and three staging reports empty. Launcher failure must not
re-publish older staging data. Linked evidence outputs, staging reports, or
work directories must fail without modifying their targets; unrelated files
must survive. The credential, dependency, and launcher cases failed before
the staging repair and pass afterward.
