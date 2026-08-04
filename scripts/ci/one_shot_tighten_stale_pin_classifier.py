"""Apply and validate the one-use stale-pin classifier hardening patch."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    """Replace one exact reviewed fragment or fail without modifying the tree."""
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one {label} fragment")
    return text.replace(old, new, 1)


def patch_source() -> None:
    """Require paired exact-requirement diagnostics for stale-pin deferral."""
    path = Path("scripts/ci/install_base_python_locks.py")
    source = path.read_text(encoding="utf-8")

    concrete_pattern = dedent(
        '''\
            # A base lock can pin a version that has since been yanked or that offers no
            # wheel for the pinned coverage-image interpreter. pip proves the index was
            # reachable only when it lists at least one concrete version. Empty lists,
            # ``none``, and unreachable-index diagnostics remain fatal.
            re.compile(
                r"Could not find a version that satisfies the requirement[^\\n]*"
                r"\\(from versions:\\s*(?!none\\b)(?=[A-Za-z0-9])[^)\\n]+\\)",
                re.IGNORECASE,
            ),
        '''
    )
    source = replace_once(
        source,
        concrete_pattern,
        "",
        label="broad concrete-version pattern",
    )

    runner_anchor = ")\nRunner = Callable[..., subprocess.CompletedProcess[str]]\n"
    requirement_patterns = dedent(
        '''\
        )
        UNSATISFIED_REQUIREMENT_RE = re.compile(
            r"^ERROR:\\s*Could not find a version that satisfies the requirement "
            r"(?P<requirement>[^\\s(]+)[^\\n]*"
            r"\\(from versions:\\s*(?!none\\b)(?=[A-Za-z0-9])[^)\\n]+\\)",
            re.IGNORECASE | re.MULTILINE,
        )
        NO_MATCHING_DISTRIBUTION_RE = re.compile(
            r"^ERROR:\\s*No matching distribution found for (?P<requirement>\\S+)",
            re.IGNORECASE | re.MULTILINE,
        )
        Runner = Callable[..., subprocess.CompletedProcess[str]]
        '''
    )
    source = replace_once(
        source,
        runner_anchor,
        requirement_patterns,
        label="classifier constant boundary",
    )

    helper_anchor = "def _contains_unclassified_error(output: str) -> bool:\n"
    helper = dedent(
        '''\
        def _matching_binary_unavailability_requirements(output: str) -> set[str]:
            """Return exact pins paired across pip binary-unavailability diagnostics."""
            unsatisfied = {
                match.group("requirement").rstrip(".,")
                for match in UNSATISFIED_REQUIREMENT_RE.finditer(output)
            }
            unmatched = {
                match.group("requirement").rstrip(".,")
                for match in NO_MATCHING_DISTRIBUTION_RE.finditer(output)
            }
            return unsatisfied if unsatisfied and unsatisfied == unmatched else set()


        '''
    )
    source = replace_once(
        source,
        helper_anchor,
        helper + helper_anchor,
        label="unclassified-error helper boundary",
    )

    old_unclassified = dedent(
        '''\
        def _contains_unclassified_error(output: str) -> bool:
            """Return whether pip emitted an error outside the deferable contract."""
            for line in output.splitlines():
                normalized_line = line.strip()
                if not normalized_line.casefold().startswith("error:"):
                    continue
                if any(pattern.search(normalized_line) for pattern in DEFERABLE_ERROR_LINES):
                    continue
                return True
            return False
        '''
    )
    new_unclassified = dedent(
        '''\
        def _contains_unclassified_error(output: str) -> bool:
            """Return whether pip emitted an error outside the deferable contract."""
            matching_requirements = _matching_binary_unavailability_requirements(output)
            for line in output.splitlines():
                normalized_line = line.strip()
                if not normalized_line.casefold().startswith("error:"):
                    continue
                binary_match = UNSATISFIED_REQUIREMENT_RE.search(normalized_line)
                if binary_match is None:
                    binary_match = NO_MATCHING_DISTRIBUTION_RE.search(normalized_line)
                if binary_match is not None:
                    requirement = binary_match.group("requirement").rstrip(".,")
                    if requirement in matching_requirements:
                        continue
                    return True
                if any(pattern.search(normalized_line) for pattern in DEFERABLE_ERROR_LINES):
                    continue
                return True
            return False
        '''
    )
    source = replace_once(
        source,
        old_unclassified,
        new_unclassified,
        label="unclassified-error implementation",
    )

    old_decision = dedent(
        '''\
                and any(
                    pattern.search(normalized_output)
                    for pattern in DEFERABLE_PREFLIGHT_FAILURES
                )
        '''
    )
    new_decision = dedent(
        '''\
                and (
                    any(
                        pattern.search(normalized_output)
                        for pattern in DEFERABLE_PREFLIGHT_FAILURES
                    )
                    or bool(
                        _matching_binary_unavailability_requirements(normalized_output)
                    )
                )
        '''
    )
    source = replace_once(
        source,
        old_decision,
        new_decision,
        label="deferability decision",
    )
    path.write_text(source, encoding="utf-8")


def patch_tests() -> None:
    """Add positive and adversarial exact-pair regression coverage."""
    path = Path("tests/test_install_base_python_lock_missing_pin.py")
    tests = path.read_text(encoding="utf-8")
    if "def test_mismatched_binary_diagnostics_remain_fatal" in tests:
        return
    tests += dedent(
        '''\


        def test_atheris_binary_wheel_unavailability_is_deferable(tmp_path: Path) -> None:
            """The real Python 3.14 binary-only diagnostic is a visible skipped lock."""

            output = (
                "ERROR: Could not find a version that satisfies the requirement "
                "atheris==3.0.0 (from versions: 3.1.0)\\n"
                "ERROR: No matching distribution found for atheris==3.0.0"
            )

            result, stdout, stderr = _run_preflight_failure(tmp_path, output)

            assert result == 0
            assert "candidates=1 installed=0 skipped=1" in stdout
            assert "atheris==3.0.0" in stderr


        def test_mismatched_binary_diagnostics_remain_fatal(tmp_path: Path) -> None:
            """Two resolver lines for different exact pins cannot authorize deferral."""

            output = (
                "ERROR: Could not find a version that satisfies the requirement "
                "pypdf==6.13.3 (from versions: 6.14.2)\\n"
                "ERROR: No matching distribution found for atheris==3.0.0"
            )

            result, stdout, stderr = _run_preflight_failure(tmp_path, output)

            assert result == 1
            assert "preflight failed" in stderr
            assert "installed=" not in stdout


        @pytest.mark.parametrize(
            "output",
            [
                (
                    "ERROR: Could not find a version that satisfies the requirement "
                    "atheris==3.0.0 (from versions: 3.1.0)"
                ),
                "ERROR: No matching distribution found for atheris==3.0.0",
            ],
        )
        def test_single_binary_diagnostic_remains_fatal(
            tmp_path: Path,
            output: str,
        ) -> None:
            """Neither half of pip binary-unavailability evidence is sufficient alone."""

            result, stdout, stderr = _run_preflight_failure(tmp_path, output)

            assert result == 1
            assert "preflight failed" in stderr
            assert "installed=" not in stdout
        '''
    )
    path.write_text(tests, encoding="utf-8")


def patch_doctoring() -> None:
    """Keep the evidence record synchronized with the stricter classifier."""
    path = Path("docs/doctoring/central-security-and-review-baseline.md")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        (
            "   incomplete closures, interpreter incompatibility, or stale pins proven by a\n"
            "   reachable index; mixed integrity, transport, or unknown errors fail closed."
        ),
        (
            "   incomplete closures, interpreter incompatibility, or binary-unavailable and\n"
            "   stale pins proven by paired diagnostics for the same exact requirement on a\n"
            "   reachable index; mixed integrity, transport, or unknown errors fail closed."
        ),
        label="doctoring decision",
    )
    text = replace_once(
        text,
        "- stale-pin deferral accepts only concrete reachable-index evidence;",
        (
            "- stale-pin deferral requires concrete reachable-index evidence and matching\n"
            "  exact-requirement resolver diagnostics;"
        ),
        label="doctoring verification contract",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    """Apply all reviewed one-use transformations."""
    patch_source()
    patch_tests()
    patch_doctoring()


if __name__ == "__main__":
    main()
