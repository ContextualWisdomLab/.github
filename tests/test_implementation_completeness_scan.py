from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

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


def binary_op():
    return NotImplemented
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
        ("binary_op", "returns NotImplemented"),
    ]
    report = scan.render_report(findings, errors, checked_count=1)
    assert "- Result: FAIL" in report
    assert "service/merge_engine.py:2 `create_user` - pass-only body" in report


def test_rust_placeholder_macros_fail_with_line_reasons(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        """pub fn implemented() -> &'static str {
    "todo!() in a string is not executable"
}
// todo!() in a comment is not executable
pub fn missing() {
    todo!("merge path not ported yet");
}

impl Engine {
    pub fn run(&self) {
        unimplemented!()
    }
}
""",
        encoding="utf-8",
    )
    changed = write_changed_files(tmp_path, "src/lib.rs")

    findings, errors = scan.scan_changed_paths(
        tmp_path, scan.changed_paths_from_file(changed)
    )

    assert errors == []
    assert [(finding.line, finding.symbol, finding.reason) for finding in findings] == [
        (6, "missing", "`todo!` macro placeholder"),
        (11, "run", "`unimplemented!` macro placeholder"),
    ]
    report = scan.render_report(findings, errors, checked_count=1)
    assert "- Result: FAIL" in report
    assert "src/lib.rs:6 `missing` - `todo!` macro placeholder" in report


def test_rust_scanner_ignores_comments_and_strings(tmp_path: Path) -> None:
    source = tmp_path / "src" / "module.rs"
    source.parent.mkdir()
    todo_macro = "to" + "do!()"
    source.write_text(
        f"""/* outer comment starts
/* nested comment mentions {todo_macro} */
still only a comment with unimplemented!()
*/
{todo_macro}("module-level unfinished work");

pub fn implemented() {{
    let text = "escaped \\\" {todo_macro} stays in the string";
}}
""",
        encoding="utf-8",
    )

    findings = scan.scan_rust_file(tmp_path, Path("src/module.rs"))

    assert [(finding.line, finding.symbol, finding.reason) for finding in findings] == [
        (5, "rust module", "`todo!` macro placeholder")
    ]


def test_tests_and_missing_files_are_ignored(tmp_path: Path) -> None:
    source = tmp_path / "tests" / "test_merge_engine.py"
    source.parent.mkdir()
    source.write_text("def fake():\n    pass\n", encoding="utf-8")
    changed = write_changed_files(
        tmp_path,
        "tests/test_merge_engine.py",
        "tests/test_lib.rs",
        "deleted_runtime_file.py",
    )

    runtime_paths = [
        path
        for path in scan.changed_paths_from_file(changed)
        if scan.is_runtime_source_path(path) and (tmp_path / path).is_file()
    ]
    findings, errors = scan.scan_changed_paths(tmp_path, runtime_paths)

    assert runtime_paths == []
    assert findings == []
    assert errors == []


def test_changed_files_tolerates_utf8_bom(tmp_path: Path) -> None:
    changed = tmp_path / "changed-files.txt"
    changed.write_text("\ufeffapp/main.py\n", encoding="utf-8")

    assert scan.changed_paths_from_file(changed) == [Path("app/main.py")]


def test_helpers_cover_dotted_names_and_non_placeholders() -> None:
    tree = ast.parse(
        """
import abc
import typing
from abc import abstractmethod


class Api(typing.Protocol[int]):
    def declared(self) -> None:
        ...


class Base(abc.ABC):
    def helper(self) -> None:
        value = 1
        return None


def raises_other_error():
    raise ValueError("not a stub")


class Concrete:
    @abstractmethod
    def declared_abstract(self):
        pass


class Decorated:
    @staticmethod
    def concrete(self):
        return None
"""
    )

    assert scan.dotted_name(tree.body[3].bases[0]) == "typing.Protocol"
    assert scan.dotted_name(ast.Tuple()) == ""
    assert scan.is_protocol_or_abc_base(tree.body[4].bases[0])
    helper = tree.body[4].body[0]
    other_error = tree.body[5]
    abstract_method = tree.body[6].body[0]
    decorated_method = tree.body[7].body[0]
    assert isinstance(helper, ast.FunctionDef)
    assert isinstance(other_error, ast.FunctionDef)
    assert isinstance(abstract_method, ast.FunctionDef)
    assert isinstance(decorated_method, ast.FunctionDef)
    assert scan.is_abstract_or_overload(abstract_method)
    assert not scan.is_abstract_or_overload(decorated_method)
    assert scan.placeholder_reason(helper) is None
    assert scan.placeholder_reason(other_error) is None
    assert scan.strip_docstring([]) == []
    assert not scan.is_runtime_python_path(Path("README.md"))
    assert scan.is_runtime_rust_path(Path("src/lib.rs"))
    assert not scan.is_runtime_source_path(Path("tests/lib.rs"))


def test_scan_reports_parse_errors_and_skips_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "pkg" / "broken.py"
    source.parent.mkdir()
    source.write_text("def broken(:\n", encoding="utf-8")
    changed = write_changed_files(
        tmp_path,
        "pkg/broken.py",
        "pkg/broken.py",
        "/absolute.py",
        "notes.txt",
        "pkg/missing.py",
    )

    changed_paths = scan.changed_paths_from_file(changed)
    findings, errors = scan.scan_changed_paths(tmp_path, changed_paths)

    assert findings == []
    assert errors == ["pkg/broken.py:1 could not be parsed: invalid syntax"]
    report = scan.render_report(findings, errors, checked_count=1)
    assert "- Result: FAIL" in report
    assert "Parse errors:" in report


def test_missing_changed_file_list_and_main_return_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert scan.changed_paths_from_file(tmp_path / "missing.txt") == []

    source = tmp_path / "app.py"
    source.write_text("def implemented():\n    return 1\n", encoding="utf-8")
    changed = write_changed_files(tmp_path, "app.py")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "implementation_completeness_scan.py",
            "--repo-root",
            str(tmp_path),
            "--changed-files",
            str(changed),
        ],
    )

    assert scan.main() == 0
    assert "- Result: PASS" in capsys.readouterr().out

    source.write_text("def missing():\n    pass\n", encoding="utf-8")
    assert scan.main() == 1
    assert "pass-only body" in capsys.readouterr().out
