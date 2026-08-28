#!/usr/bin/env python3
"""Classify missing PyO3 extensions and verify exact-head native peer checks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility lane.
    import tomli as tomllib


MAX_LOG_BYTES = 2_000_000
MAX_METADATA_BYTES = 262_144
MAX_CHECK_BYTES = 1_000_000
DOTTED_MODULE_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z"
)
MISSING_MODULE_RE = re.compile(
    r"ModuleNotFoundError:\s+No module named ['\"]([^'\"]+)['\"]"
)
PARTIAL_NATIVE_IMPORT_RE = re.compile(
    r"^E\s+ImportError:\s+cannot import name ['\"]([^'\"]+)['\"] "
    r"from partially initialized module ['\"]([^'\"]+)['\"] "
    r"\(most likely due to a circular import\)",
    re.MULTILINE,
)
COLLECTION_ERROR_RE = re.compile(
    r"^_+\s+ERROR collecting\s+.+?\s+_+\s*$", re.MULTILINE
)
INTERRUPTED_RE = re.compile(
    r"Interrupted:\s+(\d+)\s+errors?\s+during\s+collection", re.IGNORECASE
)
EXCEPTION_LINE_RE = re.compile(
    r"^E\s+([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))(?::|\s*$)",
    re.MULTILINE,
)
FORBIDDEN_LOG_MARKERS = (
    " output truncated:",
    "INTERNALERROR>",
    "Fatal Python error",
    "Segmentation fault",
    "ERROR at setup",
    "ERROR at teardown",
    "=== FAILURES ===",
)
LOCK_FILE_NAMES = {
    "Cargo.lock",
    "Pipfile.lock",
    "poetry.lock",
    "pylock.toml",
    "uv.lock",
}
PACKAGING_FILE_NAMES = {
    "MANIFEST.in",
    "build.rs",
    "setup.cfg",
    "setup.py",
}


def _regular_path_stat(path: Path) -> os.stat_result | None:
    """Return a regular-file stat only when every lexical path component is safe."""

    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            return None
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return metadata if stat.S_ISREG(metadata.st_mode) else None


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    """Return whether two stats identify the same filesystem object."""

    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _metadata_signature(metadata: os.stat_result) -> tuple[int, ...]:
    """Return metadata that must remain stable while evidence is read."""

    return (
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_bounded_regular(path: Path, maximum: int) -> bytes | None:
    """Return bounded regular-file bytes, or ``None`` for unsafe input."""

    try:
        if maximum < 0:
            return None
        candidate = path.absolute()
        live_before_open = _regular_path_stat(candidate)
        if live_before_open is None:
            return None
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate, flags)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > maximum
                or not _same_file(live_before_open, metadata)
            ):
                return None
            initial_signature = _metadata_signature(metadata)
            payload = bytearray()
            while len(payload) <= maximum:
                chunk = os.read(descriptor, maximum + 1 - len(payload))
                if not chunk:
                    metadata_after_read = os.fstat(descriptor)
                    live_after_read = _regular_path_stat(candidate)
                    if (
                        _metadata_signature(metadata_after_read)
                        != initial_signature
                        or live_after_read is None
                        or not _same_file(live_after_read, metadata_after_read)
                    ):
                        return None
                    return bytes(payload)
                payload.extend(chunk)
                if len(payload) > maximum:
                    return None
            return None  # pragma: no cover - every read iteration returns above.
        finally:
            os.close(descriptor)
    except OSError:
        return None


def _read_text(path: Path, maximum: int) -> str | None:
    """Return bounded UTF-8 text, rejecting malformed or unsafe input."""

    payload = _read_bounded_regular(path, maximum)
    if payload is None:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _safe_relative_path(raw_path: str) -> PurePosixPath | None:
    """Return a normalized repository-relative POSIX path when safe."""

    if not raw_path or "\x00" in raw_path or "\\" in raw_path:
        return None
    segments = raw_path.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        return None
    return PurePosixPath(raw_path)


def _maturin_contract(
    pyproject: Path,
) -> tuple[str, PurePosixPath, PurePosixPath] | None:
    """Return the native module, Cargo manifest, and Python source directory."""

    payload = _read_bounded_regular(pyproject, MAX_METADATA_BYTES)
    if payload is None:
        return None
    try:
        metadata = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    build_system = metadata.get("build-system")
    tool = metadata.get("tool")
    if not isinstance(build_system, dict) or not isinstance(tool, dict):
        return None
    maturin = tool.get("maturin")
    if not isinstance(maturin, dict):
        return None
    if build_system.get("build-backend") != "maturin":
        return None
    if maturin.get("bindings") != "pyo3":
        return None

    module_name = maturin.get("module-name")
    manifest_value = maturin.get("manifest-path", "Cargo.toml")
    python_source_value = maturin.get("python-source", ".")
    if (
        not isinstance(module_name, str)
        or DOTTED_MODULE_RE.fullmatch(module_name) is None
        or not isinstance(manifest_value, str)
        or not isinstance(python_source_value, str)
    ):
        return None
    manifest_path = _safe_relative_path(manifest_value)
    python_source = (
        PurePosixPath(".")
        if python_source_value == "."
        else _safe_relative_path(python_source_value)
    )
    if (
        manifest_path is None
        or manifest_path.name != "Cargo.toml"
        or python_source is None
    ):
        return None
    return module_name, manifest_path, python_source


def _read_changed_files(path: Path) -> tuple[PurePosixPath, ...] | None:
    """Return validated changed paths from a bounded newline-delimited file."""

    text = _read_text(path, MAX_METADATA_BYTES)
    if text is None:
        return None
    paths: list[PurePosixPath] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        raw_path = raw_line.strip()
        if not raw_path:
            continue
        parsed = _safe_relative_path(raw_path)
        if parsed is None or parsed.as_posix() in seen:
            return None
        seen.add(parsed.as_posix())
        paths.append(parsed)
    return tuple(paths)


def _repository_contract_paths(
    *,
    repo_root_path: Path | None,
    pyproject_path: Path,
    logical_pyproject_path: Path | None = None,
    manifest_path: PurePosixPath,
    python_source: PurePosixPath,
) -> tuple[PurePosixPath, PurePosixPath, PurePosixPath] | None:
    """Return repository-relative PyO3 paths without rereading mutable metadata."""

    candidate_root = pyproject_path.parent if repo_root_path is None else repo_root_path
    try:
        if not candidate_root.is_dir() or candidate_root.is_symlink():
            return None
        repository_root = candidate_root.resolve()
    except (OSError, ValueError):
        return None

    if logical_pyproject_path is not None:
        if repo_root_path is None:
            return None
        relative_pyproject = _safe_relative_path(logical_pyproject_path.as_posix())
        if relative_pyproject is None:
            return None
        project_prefix = relative_pyproject.parent
    else:
        try:
            project_root = pyproject_path.parent.resolve()
            resolved_pyproject = pyproject_path.resolve()
            if resolved_pyproject.parent != project_root:
                return None
            project_prefix_path = project_root.relative_to(repository_root)
        except (OSError, ValueError):
            return None
        project_prefix = (
            PurePosixPath(".")
            if not project_prefix_path.parts
            else PurePosixPath(project_prefix_path.as_posix())
        )
        relative_pyproject = project_prefix / pyproject_path.name
    if relative_pyproject.name != "pyproject.toml":
        return None
    relative_manifest = project_prefix / manifest_path
    relative_python_source = (
        project_prefix
        if python_source == PurePosixPath(".")
        else project_prefix / python_source
    )
    return relative_pyproject, relative_manifest, relative_python_source


def _touches_native_or_trust_boundary(
    changed_paths: tuple[PurePosixPath, ...],
    *,
    pyproject_path: PurePosixPath,
    manifest_path: PurePosixPath,
    module_name: str,
    python_source: PurePosixPath,
) -> bool:
    """Return whether changed files invalidate unchanged-extension deferral."""

    manifest_parent = manifest_path.parent
    module_stub = (
        python_source / PurePosixPath(*module_name.split("."))
    ).with_suffix(".pyi")
    for path in changed_paths:
        if path == pyproject_path or path == manifest_path:
            return True
        if path.name in LOCK_FILE_NAMES or path.name in PACKAGING_FILE_NAMES:
            return True
        if path.name == "Cargo.toml" or path.suffix == ".rs":
            return True
        if path == module_stub:
            return True
        if path.parts[:2] in {(".github", "workflows"), (".github", "actions")}:
            return True
        if path.name.startswith(("requirements", "constraints")) and path.suffix in {
            ".in",
            ".txt",
        }:
            return True
        if "requirements" in path.parts and path.suffix in {".in", ".txt", ".lock"}:
            return True
        if manifest_parent != PurePosixPath(".") and path.is_relative_to(manifest_parent):
            return True
        if path.name == "pyproject.toml":
            return True
    return False


def classify_pytest_failure(
    log_text: str,
    *,
    module_name: str,
) -> bool:
    """Return whether pytest failed only because one declared module was absent."""

    if not log_text or any(marker in log_text for marker in FORBIDDEN_LOG_MARKERS):
        return False
    if re.search(r"^FAILED\s+", log_text, re.MULTILINE):
        return False

    missing_modules = MISSING_MODULE_RE.findall(log_text)
    partial_native_imports = PARTIAL_NATIVE_IMPORT_RE.findall(log_text)
    collection_errors = COLLECTION_ERROR_RE.findall(log_text)
    interruptions = INTERRUPTED_RE.findall(log_text)
    if (
        not missing_modules and not partial_native_imports
        or not collection_errors
        or len(interruptions) != 1
    ):
        return False
    if missing_modules and partial_native_imports:
        return False
    if int(interruptions[0]) != len(collection_errors):
        return False

    escaped_module = re.escape(module_name)
    if missing_modules:
        if (
            len(missing_modules) != len(collection_errors)
            or any(name != module_name for name in missing_modules)
        ):
            return False
        imported_module_count = len(
            re.findall(
                rf"^\s*(?:from\s+{escaped_module}\s+import|import\s+{escaped_module}(?:\s|$))",
                log_text,
                re.MULTILINE,
            )
        )
        if imported_module_count < len(collection_errors):
            return False
        expected_exception = "ModuleNotFoundError"
    else:
        if len(partial_native_imports) != len(collection_errors):
            return False
        try:
            expected_parent, expected_leaf = module_name.rsplit(".", 1)
        except ValueError:
            return False
        if any(
            (leaf, parent) != (expected_leaf, expected_parent)
            for leaf, parent in partial_native_imports
        ):
            return False
        imported_module_count = len(
            re.findall(
                rf"^\s*(?:from\s+\.\s+import\s+{re.escape(expected_leaf)}|"
                rf"from\s+{re.escape(expected_parent)}\s+import\s+{re.escape(expected_leaf)}|"
                rf"import\s+{escaped_module})(?:\s|$)",
                log_text,
                re.MULTILINE,
            )
        )
        if imported_module_count < len(collection_errors):
            return False
        expected_exception = "ImportError"

    exception_types = EXCEPTION_LINE_RE.findall(log_text)
    return bool(exception_types) and all(
        exception_type == expected_exception for exception_type in exception_types
    )


def classify_pytest_inputs(
    *,
    log_path: Path,
    pyproject_path: Path,
    logical_pyproject_path: Path | None = None,
    changed_files_path: Path,
    repo_root_path: Path | None = None,
) -> str | None:
    """Return the safely deferred module name, or ``None`` when blocking."""

    contract = _maturin_contract(pyproject_path)
    log_text = _read_text(log_path, MAX_LOG_BYTES)
    changed_paths = _read_changed_files(changed_files_path)
    if contract is None or log_text is None or changed_paths is None:
        return None

    module_name, manifest_path, python_source = contract
    repository_paths = _repository_contract_paths(
        repo_root_path=repo_root_path,
        pyproject_path=pyproject_path,
        logical_pyproject_path=logical_pyproject_path,
        manifest_path=manifest_path,
        python_source=python_source,
    )
    if repository_paths is None:
        return None
    relative_pyproject, relative_manifest, relative_python_source = repository_paths
    if _touches_native_or_trust_boundary(
        changed_paths,
        pyproject_path=relative_pyproject,
        manifest_path=relative_manifest,
        module_name=module_name,
        python_source=relative_python_source,
    ):
        return None
    if not classify_pytest_failure(log_text, module_name=module_name):
        return None
    return module_name


def _workflow_name(check: dict[str, Any]) -> str | None:
    """Return a normalized workflow name from one check-run record."""

    workflow = check.get("workflow")
    if isinstance(workflow, str):
        return workflow
    suite = check.get("checkSuite")
    if not isinstance(suite, dict):
        return None
    workflow_run = suite.get("workflowRun")
    if not isinstance(workflow_run, dict):
        return None
    nested = workflow_run.get("workflow")
    if not isinstance(nested, dict):
        return None
    name = nested.get("name")
    return name if isinstance(name, str) else None


def _read_checks(path: Path) -> list[dict[str, Any]] | None:
    """Return a bounded list of normalized check-run records."""

    text = _read_text(path, MAX_CHECK_BYTES)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        return None
    return payload


def has_required_exact_head_checks(
    checks: list[dict[str, Any]],
    *,
    head_sha: str,
    required_checks: tuple[tuple[str, str], ...],
) -> bool:
    """Return whether every trusted exact-head check completed successfully."""

    if re.fullmatch(r"[0-9a-fA-F]{40}", head_sha) is None or not required_checks:
        return False
    if len(set(required_checks)) != len(required_checks):
        return False

    for workflow, name in required_checks:
        matches = [
            check
            for check in checks
            if check.get("__typename") == "CheckRun"
            and _workflow_name(check) == workflow
            and check.get("name") == name
            and check.get("head_sha") == head_sha
        ]
        if not matches:
            return False
        if any(
            str(check.get("status") or "").upper() != "COMPLETED"
            or str(check.get("conclusion") or "").upper() != "SUCCESS"
            for check in matches
        ):
            return False
    return True


def _parse_required_check(value: str) -> tuple[str, str]:
    """Parse one trusted ``WORKFLOW::CHECK`` requirement."""

    workflow, separator, name = value.partition("::")
    if not separator or not workflow.strip() or not name.strip():
        raise argparse.ArgumentTypeError(
            "required checks must use non-empty WORKFLOW::CHECK syntax"
        )
    return workflow.strip(), name.strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the native-extension peer-gate command line."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify = subparsers.add_parser("classify-pytest")
    classify.add_argument("--log", type=Path, required=True)
    classify.add_argument("--pyproject", type=Path, required=True)
    classify.add_argument("--logical-pyproject", type=Path)
    classify.add_argument("--changed-files", type=Path, required=True)
    classify.add_argument("--repo-root", type=Path)

    require = subparsers.add_parser("require-checks")
    require.add_argument("--checks-json", type=Path, required=True)
    require.add_argument("--head-sha", required=True)
    require.add_argument(
        "--required-check",
        action="append",
        type=_parse_required_check,
        required=True,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected fail-closed native-extension peer gate."""

    args = parse_args(argv)
    if args.command == "classify-pytest":
        module_name = classify_pytest_inputs(
            log_path=args.log,
            pyproject_path=args.pyproject,
            logical_pyproject_path=args.logical_pyproject,
            changed_files_path=args.changed_files,
            repo_root_path=args.repo_root,
        )
        if module_name is None:
            print("pytest failure is not safely deferrable", file=sys.stderr)
            return 1
        print(
            "pytest collection failed exclusively because unchanged declared "
            f"native module {module_name} was absent"
        )
        return 0

    checks = _read_checks(args.checks_json)
    required_checks = tuple(args.required_check)
    if checks is not None and has_required_exact_head_checks(
        checks,
        head_sha=args.head_sha,
        required_checks=required_checks,
    ):
        print("all required exact-head native peer checks succeeded")
        return 0
    print("required exact-head native peer checks were not proven", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised by workflow entrypoint.
    raise SystemExit(main())
