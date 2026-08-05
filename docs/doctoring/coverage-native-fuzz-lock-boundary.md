# Generic coverage versus native fuzz-engine lock boundary

## Decision

The central OpenCode coverage image materializes immutable, hash-pinned dependencies needed to import selected production modules and run their ordinary tests. It does not install native coverage-guided fuzz engines that are executed only by dedicated repository fuzz workflows.

`requirements-atheris.txt` is therefore classified as a native fuzz-engine lock and excluded from generic coverage materialization. The classification is exact-name based and path-independent. Hash-pinned property and regression locks such as `requirements-property.txt` and `requirements-fuzz-regression.txt` remain eligible.

## Technical rationale

Atheris is a coverage-guided native Python fuzzer built on libFuzzer. Its runtime role is to instrument and repeatedly execute fuzz targets, not to provide application imports required by an ordinary coverage.py test run. Installing an interpreter- and platform-specific native fuzz runtime in every generic coverage image adds an unrelated native artifact compatibility gate before application coverage begins.

Coverage.py measures execution of Python programs and can report statement and branch coverage for the selected test process without Atheris. The central reviewer therefore preserves two independent verification layers:

1. repository Fuzz workflows install and execute the native fuzz engine against real fuzz targets;
2. central OpenCode coverage evidence installs ordinary import/test dependencies and measures the selected production surface.

Separating these layers avoids converting a native fuzz toolchain mismatch into a source-coverage review failure while retaining both gates.

## Trust boundary

The materializer still reads every candidate only from the exact validated pull-request base commit. Pull-request-mutated dependency files never enter the networked image-build stage. Every included lock must remain hash-pinned, and malformed Git metadata, unsafe paths, non-blob entries, unpinned requirements, and unsafe output destinations remain fail-closed.

The exclusion reduces trusted inputs. It does not introduce an unhashed fallback, download a replacement package, or suppress an application/test import failure. Dedicated Fuzz required workflows continue to install `requirements-atheris.txt` directly.

## Verification evidence

A real temporary Git repository fixture contains:

- `fuzz/requirements-atheris.txt`;
- `fuzz/requirements-property.txt`;
- `services/example_service/requirements-fuzz-regression.txt`.

The test commits these files as the immutable base, materializes that exact revision, and proves that only the property and regression locks appear in the generated manifest. A second contract proves exact-name classification so a substring or directory name cannot broaden the exclusion.

The changed helper and integration path are subject to the central 100% statement, branch, and docstring gates.

## Operational limits

The exact-name set initially contains only `requirements-atheris.txt`. Another native engine must not be added through a wildcard or informal comment. It requires separate artifact-role evidence, a regression fixture, review, and changelog entry.

This boundary does not claim that Atheris is optional for fuzzing. It is optional only for the generic OpenCode import/coverage image. Repositories remain responsible for realistic dedicated fuzz execution and crash-regression evidence.

## Rollback

Rollback removes the exact-name classifier and its fixture. Before rollback, operators must confirm that every supported central coverage interpreter can install every repository's Atheris lock and that doing so provides coverage evidence not already supplied by the dedicated Fuzz workflow. Otherwise rollback recreates the false-negative review condition documented here.

## APA 7 references

Batchelder, N. (2026). *Coverage.py documentation*. https://coverage.readthedocs.io/

Google. (2026). *Atheris: A coverage-guided, native Python fuzzer* [Computer software]. GitHub. https://github.com/google/atheris

Python Packaging Authority. (2026). *Dependency specifiers*. Python Packaging User Guide. https://packaging.python.org/en/latest/specifications/dependency-specifiers/

Semgrep, Inc. (2026). *Sample continuous integration configurations*. https://semgrep.dev/docs/semgrep-ci/sample-ci-configs
