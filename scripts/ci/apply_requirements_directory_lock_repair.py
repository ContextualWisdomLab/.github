#!/usr/bin/env python3
"""Apply the reviewed requirements-directory lock materialization repair.

This branch-only helper is executed by a same-repository pull-request workflow.
It edits only the permanent materializer, its permanent quality workflow,
doctoring, and changelog, then removes all temporary repair machinery before the
verified product commit is published.
"""

from __future__ import annotations

from pathlib import Path

MATERIALIZER = Path("scripts/ci/materialize_base_python_requirements.py")
QUALITY_WORKFLOW = Path(".github/workflows/trusted-uv-materializer-quality-ci.yml")
DOCTORING = Path("docs/doctoring/trusted-requirements-directory-lock-discovery.md")
CHANGELOG = Path("CHANGELOG.md")
TEMPORARY_PATHS = (
    Path(".github/workflows/repair-requirements-directory-locks.yml"),
    Path(".github/workflows/reopen-requirements-directory-locks.yml"),
    Path("scripts/ci/apply_requirements_directory_lock_repair.py"),
)


def replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    """Replace one exact reviewed fragment or fail closed on source drift."""
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one {label}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def repair_materializer() -> None:
    """Recognize only direct text children of a requirements directory."""
    old_function = '''def _is_candidate_lock_name(name: str) -> bool:
    """Return whether a file name is a possible pip requirements lock."""
    return name == "requirements.lock" or (
        fnmatch.fnmatch(name, "requirements*.txt")
        and not fnmatch.fnmatch(name, "requirements-*-ci-hashes.txt")
    )
'''
    new_function = old_function + '''

def _is_candidate_lock_path(path: pathlib.PurePosixPath) -> bool:
    """Return whether one safe tracked path can name a pip requirements lock.

    In addition to conventional ``requirements*.txt`` names, repositories often
    keep concrete environment closures as direct children such as
    ``requirements/ci.txt`` or ``service/requirements/package.txt``. Only direct
    ``.txt`` children of a directory named ``requirements`` gain this path-based
    eligibility; content must still pass the independent complete hash-pin
    validation before it reaches the trusted image build context.
    """
    return _is_candidate_lock_name(path.name) or (
        path.suffix == ".txt" and path.parent.name == "requirements"
    )
'''
    replace_once(
        MATERIALIZER,
        old_function,
        new_function,
        label="candidate-name function",
    )
    replace_once(
        MATERIALIZER,
        "        if _is_candidate_lock_name(candidate.name):\n",
        "        if _is_candidate_lock_path(candidate):\n",
        label="candidate-path call",
    )


def repair_quality_workflow() -> None:
    """Keep the new regression in every trigger, test, and compile gate."""
    workflow = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    direct_path = '      - "tests/test_requirements_directory_lock_materialization.py"\n'
    if workflow.count(direct_path) == 0:
        anchor = '      - "tests/test_materialize*.py"\n'
        if workflow.count(anchor) != 2:
            raise RuntimeError("expected two materializer path-filter anchors")
        workflow = workflow.replace(anchor, anchor + direct_path)
    elif workflow.count(direct_path) != 2:
        raise RuntimeError("requirements-directory path filter is incomplete")

    test_target = "            tests/test_requirements_directory_lock_materialization.py \\\n"
    if test_target not in workflow:
        anchor = "            tests/test_materialize_uv_export_hash_contract.py \\\n"
        if workflow.count(anchor) != 2:
            raise RuntimeError("expected test and compile materializer anchors")
        first = workflow.index(anchor) + len(anchor)
        workflow = workflow[:first] + test_target + workflow[first:]

    if workflow.count(test_target) == 1:
        compile_heading = "      - name: Compile production and quality contracts\n"
        compile_start = workflow.index(compile_heading)
        compile_anchor = "            tests/test_materialize_uv_export_hash_contract.py \\\n"
        anchor_index = workflow.index(compile_anchor, compile_start) + len(compile_anchor)
        workflow = workflow[:anchor_index] + test_target + workflow[anchor_index:]
    if workflow.count(test_target) != 2:
        raise RuntimeError("requirements-directory test target is incomplete")

    QUALITY_WORKFLOW.write_text(workflow, encoding="utf-8")


def write_doctoring() -> None:
    """Record the trust boundary and APA 7 primary-source evidence."""
    DOCTORING.write_text(
        """# Trusted requirements-directory lock discovery

## Decision

The central OpenCode coverage image materializes dependency closures only from
regular files in the authenticated pull-request base commit. In addition to the
conventional `requirements*.txt` and `requirements.lock` names, it recognizes a
`.txt` file that is a **direct child** of a directory named `requirements`, such
as `requirements/ci.txt` or `services/scoring_service/requirements/package.txt`.

The path rule grants candidate status only. The existing content boundary still
requires nonempty hash-pinned logical requirements, records the exact trusted
source path in the manifest, and preflights each candidate as an independently
installable `pip --require-hashes` closure. Unpinned notes, input files, nested
descendants, symbolic links, pull-request-only files, and malformed Git tree
entries remain excluded.

## Operational reason

Concrete environment locks are frequently organized below a `requirements`
directory and use role names such as `ci.txt` or `package.txt`. Ignoring those
safe base-owned locks leaves isolated coverage without runtime dependencies even
when the repository maintains a complete generated closure. The resulting import
failure measures the coverage image rather than the changed production code.

## Verification

- A failing contract first proved that `requirements/ci.txt` was undiscoverable.
- Direct `requirements/*.txt` and nested-service equivalents are accepted.
- A deeper `requirements/nested/ci.txt` path and unrelated `docs/ci.txt` remain
  ineligible.
- Only the hash-pinned candidate is emitted from a realistic temporary Git base;
  unpinned `.in` and human-readable `.txt` files remain absent.
- The focused materializer suite, complete central suite, statement and branch
  coverage, docstring gate, compilation, and exact-head security workflows are
  required before merge.

## References

Python Packaging Authority. (2026). *Install requires vs requirements files*.
Python Packaging User Guide.
https://packaging.python.org/en/latest/discussions/install-requires-vs-requirements/

Python Packaging Authority. (2026). *Repeatable installs*. pip documentation.
https://pip.pypa.io/en/stable/topics/repeatable-installs/

Python Packaging Authority. (2026). *Requirements file format*. pip
documentation.
https://pip.pypa.io/en/stable/reference/requirements-file-format/
""",
        encoding="utf-8",
    )


def update_changelog() -> None:
    """Record the coverage-environment compatibility repair under Unreleased."""
    bullet = (
        "- Materialize complete hash-pinned `requirements/ci.txt` and other "
        "direct `requirements/*.txt` base-owned closures so isolated OpenCode "
        "coverage imports repository runtime dependencies without trusting "
        "pull-request metadata or broadening network access.\n"
    )
    changelog = CHANGELOG.read_text(encoding="utf-8")
    if bullet in changelog:
        return
    anchor = "### Fixed\n\n"
    if changelog.count(anchor) != 1:
        raise RuntimeError("expected one Unreleased Fixed heading")
    CHANGELOG.write_text(changelog.replace(anchor, anchor + bullet, 1), encoding="utf-8")


def remove_temporary_paths() -> None:
    """Delete all branch-only repair workflows and this transformer."""
    for path in TEMPORARY_PATHS:
        if path.exists():
            path.unlink()


def main() -> None:
    """Apply the permanent repair and leave a workflow-free product tree."""
    repair_materializer()
    repair_quality_workflow()
    write_doctoring()
    update_changelog()
    remove_temporary_paths()


if __name__ == "__main__":
    main()
