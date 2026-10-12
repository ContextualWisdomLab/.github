"""A built PyO3 extension must be importable from the source tree pytest actually imports."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.ci import place_maturin_extension as placer

_SO = "_core.cpython-314-x86_64-linux-gnu.so"


def _project(tmp_path: Path, python_source: str | None) -> Path:
    project = tmp_path / "project"
    maturin = f'[tool.maturin]\npython-source = "{python_source}"\n' if python_source else ""
    (project).mkdir()
    (project / "pyproject.toml").write_text(
        '[build-system]\nbuild-backend = "maturin"\n' + maturin, encoding="utf-8"
    )
    package = project / (python_source or ".") / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from . import _core\n", encoding="utf-8")
    return project


def _wheel(tmp_path: Path, members: dict[str, bytes]) -> Path:
    wheel = tmp_path / "pkg-0.1.0-cp314-cp314-linux_x86_64.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return wheel


@pytest.mark.parametrize("python_source", ["python", None])
def test_extension_lands_in_the_imported_source_package(
    tmp_path: Path, python_source: str | None
) -> None:
    project = _project(tmp_path, python_source)
    wheel = _wheel(
        tmp_path,
        {
            f"pkg/{_SO}": b"ELF",
            "pkg/__init__.py": b"# wheel copy must not overwrite the PR source\n",
            "pkg-0.1.0.dist-info/RECORD": b"",
        },
    )
    placed = placer.place(wheel, project)
    target = project / (python_source or ".") / "pkg" / _SO
    assert placed == [target.resolve()]
    assert target.read_bytes() == b"ELF"
    assert (project / (python_source or ".") / "pkg/__init__.py").read_text(
        encoding="utf-8"
    ) == "from . import _core\n"


def test_python_source_outside_the_project_is_rejected(tmp_path: Path) -> None:
    project = _project(tmp_path, "python")
    (project / "pyproject.toml").write_text(
        '[tool.maturin]\npython-source = "../outside"\n', encoding="utf-8"
    )
    wheel = _wheel(tmp_path, {f"pkg/{_SO}": b"ELF"})
    with pytest.raises(ValueError):
        placer.place(wheel, project)


def test_traversing_wheel_member_is_rejected(tmp_path: Path) -> None:
    project = _project(tmp_path, "python")
    wheel = _wheel(tmp_path, {f"../../{_SO}": b"ELF"})
    with pytest.raises(ValueError):
        placer.place(wheel, project)
    assert not (tmp_path / _SO).exists()


def test_extension_for_a_package_absent_from_the_source_tree_is_skipped(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "python")
    wheel = _wheel(tmp_path, {f"other/{_SO}": b"ELF"})
    assert placer.place(wheel, project) == []
    assert not (project / "python/other").exists()


def test_offline_maturin_build_places_the_extension_for_pytest() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/opencode-review-dispatch.yml"
    ).read_text(encoding="utf-8")
    build = workflow.split("build_maturin_extension_if_needed() {", 1)[1].split("\n          }", 1)[0]
    assert 'python3 "$2" "$dist_dir"/*.whl .' in build
    assert '"${GITHUB_WORKSPACE}/scripts/ci/place_maturin_extension.py"' in build


def test_extension_cli_and_configuration_failures(tmp_path, monkeypatch, capsys):
    """The CLI preserves validation failures and prints only placed source paths."""
    import runpy
    import sys
    project = _project(tmp_path, "python")
    wheel = _wheel(tmp_path, {f"pkg/{_SO}": b"ELF"})
    assert placer.main([]) == 2
    assert placer.main([str(wheel), str(tmp_path / "absent")]) == 1
    assert placer.main([str(wheel), str(project)]) == 0
    assert "Placed built extension" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["place", str(wheel), str(project)])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(placer.__file__, run_name="__main__")
    assert result.value.code == 0
    (project / "pyproject.toml").write_text('[tool.maturin]\npython-source = 3\n')
    with pytest.raises(ValueError, match="must be a string"):
        placer.place(wheel, project)
