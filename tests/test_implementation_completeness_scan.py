from __future__ import annotations

from pathlib import Path

from scripts.ci import implementation_completeness_scan as scan


def write_changed_files(tmp_path: Path, *paths: str) -> Path:
    changed = tmp_path / "changed-files.txt"
    changed.write_text("\n".join(paths) + "\n", encoding="utf-8")
    return changed


def test_protocol_and_abstract_placeholders_are_declarations(tmp_path: Path) -> None:
    source = tmp_path / "app" / "keycloak_client.py"
    source.parent.mkdir()
    source.write_text(
        """
from abc import ABC, abstractmethod
from typing import Protocol, overload


class AdminApi(Protocol):
    def get_user(self, user_id: str) -> str:
        \"\"\"Return one user.\"\"\"
        ...


class BaseAdapter(ABC):
    @abstractmethod
    def send(self) -> None:
        pass


@overload
def parse(value: int) -> int: ...
""",
        encoding="utf-8",
    )
    changed = write_changed_files(tmp_path, "app/keycloak_client.py")

    findings, errors = scan.scan_changed_paths(
        tmp_path, scan.changed_paths_from_file(changed)
    )

    assert findings == []
    assert errors == []
    report = scan.render_report(findings, errors, checked_count=1)
    assert "- Result: PASS" in report
    assert "Protocol" in report


def test_runtime_placeholder_functions_fail_with_line_reasons(tmp_path: Path) -> None:
    source = tmp_path / "service" / "merge_engine.py"
    source.parent.mkdir()
    source.write_text(
        """
def create_user():
    pass


class Engine:
    def merge(self):
        \"\"\"Merge account data.\"\"\"
        raise NotImplementedError


async def sync():
    ...
""",
        encoding="utf-8",
    )
    changed = write_changed_files(tmp_path, "service/merge_engine.py")

    findings, errors = scan.scan_changed_paths(
        tmp_path, scan.changed_paths_from_file(changed)
    )

    assert errors == []
    assert [(finding.symbol, finding.reason) for finding in findings] == [
        ("create_user", "pass-only body"),
        ("Engine.merge", "raises NotImplementedError"),
        ("sync", "ellipsis-only body"),
    ]
    report = scan.render_report(findings, errors, checked_count=1)
    assert "- Result: FAIL" in report
    assert "service/merge_engine.py:2 `create_user` - pass-only body" in report


def test_tests_and_missing_files_are_ignored(tmp_path: Path) -> None:
    source = tmp_path / "tests" / "test_merge_engine.py"
    source.parent.mkdir()
    source.write_text("def fake():\n    pass\n", encoding="utf-8")
    changed = write_changed_files(
        tmp_path,
        "tests/test_merge_engine.py",
        "deleted_runtime_file.py",
    )

    runtime_paths = [
        path
        for path in scan.changed_paths_from_file(changed)
        if scan.is_runtime_python_path(path) and (tmp_path / path).is_file()
    ]
    findings, errors = scan.scan_changed_paths(tmp_path, runtime_paths)

    assert runtime_paths == []
    assert findings == []
    assert errors == []


def test_changed_files_tolerates_utf8_bom(tmp_path: Path) -> None:
    changed = tmp_path / "changed-files.txt"
    changed.write_text("\ufeffapp/main.py\n", encoding="utf-8")

    assert scan.changed_paths_from_file(changed) == [Path("app/main.py")]
