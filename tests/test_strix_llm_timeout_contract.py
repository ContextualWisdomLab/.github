"""Regression contract for unbounded Strix inference through contextual-orchestrator."""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
from pathlib import Path
import runpy
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
TOKEN_LOADER = ROOT / "scripts" / "ci" / "load_contextual_orchestrator_token.sh"
INSTALLER = ROOT / "scripts" / "ci" / "install_strix_timeout_compat.py"
LAUNCHER = ROOT / "scripts" / "ci" / "strix_timeout_compat.py"


def _load_module(path: Path, module_name: str):
    """Load one repository module without importing it through package state."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_launcher():
    """Load the compatibility launcher without requiring Strix at test import time."""
    return _load_module(LAUNCHER, "strix_timeout_compat")


def _load_installer():
    """Load the installer without running its CLI entry point."""
    return _load_module(INSTALLER, "install_strix_timeout_compat")


def test_strix_timeout_compat_is_installed_after_the_pinned_runtime() -> None:
    """Keep the upstream 1.5.3 parser value from becoming a real inference deadline."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    token_loader = TOKEN_LOADER.read_text(encoding="utf-8")

    assert "export LLM_TIMEOUT=0" in workflow
    assert 'if [ -n "${STRIX_EXECUTABLE_PATH:-}" ]; then' in token_loader
    assert "install_strix_timeout_compat.py" in token_loader
    assert INSTALLER.is_file()
    assert LAUNCHER.is_file()


def test_compat_launcher_disables_request_and_stream_idle_deadlines() -> None:
    """The launcher maps central review policy to zero/unbounded settings."""
    launcher = _load_launcher()
    environment = {"LLM_TIMEOUT": "300", "LLM_STREAM_IDLE_TIMEOUT": "300"}

    launcher.normalize_inference_timeout_environment(environment)

    assert environment["LLM_TIMEOUT"] == "0"
    assert environment["LLM_STREAM_IDLE_TIMEOUT"] == "0"
    assert launcher.SUPPORTED_VERSION == "1.5.3"


def test_compat_asyncio_proxy_removes_positional_and_keyword_deadlines() -> None:
    """Warm-up wait_for accepts Strix's keyword call and always delegates unbounded."""
    launcher = _load_launcher()
    seen_timeouts: list[object] = []

    class FakeAsyncio:
        marker = "delegated"

        @staticmethod
        async def wait_for(awaitable, timeout):
            seen_timeouts.append(timeout)
            return await awaitable

    async def result(value: str):
        return value

    proxy = launcher.UnboundedInferenceAsyncio(FakeAsyncio())
    assert proxy.marker == "delegated"
    assert asyncio.run(proxy.wait_for(result("positional"), 300)) == "positional"
    assert asyncio.run(proxy.wait_for(result("keyword"), timeout=300)) == "keyword"
    assert seen_timeouts == [None, None]


def test_launcher_version_gate_accepts_only_the_reviewed_version(monkeypatch) -> None:
    """Version drift and missing installation fail closed before runtime mutation."""
    launcher = _load_launcher()

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.5.3")
    launcher._require_supported_version()

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.5.4")
    with pytest.raises(RuntimeError, match="supports exactly 1.5.3"):
        launcher._require_supported_version()

    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing)
    with pytest.raises(RuntimeError, match="is not installed"):
        launcher._require_supported_version()


def test_runtime_compatibility_patches_only_strix_model_boundaries(monkeypatch) -> None:
    """Request and warm-up deadlines are removed without replacing global asyncio."""
    launcher = _load_launcher()
    calls: list[dict[str, object]] = []

    strix_package = types.ModuleType("strix")
    core_package = types.ModuleType("strix.core")
    interface_package = types.ModuleType("strix.interface")
    inputs_module = types.ModuleType("strix.core.inputs")
    scan_setup_module = types.ModuleType("strix.interface.scan_setup")
    main_module = types.ModuleType("strix.interface.main")

    def make_model_settings(*args, **kwargs):
        calls.append({"args": args, "kwargs": dict(kwargs)})
        return kwargs

    inputs_module.make_model_settings = make_model_settings
    scan_setup_module.asyncio = asyncio
    main_module.asyncio = asyncio
    main_module.main = lambda: None
    core_package.inputs = inputs_module
    interface_package.scan_setup = scan_setup_module
    interface_package.main = main_module
    strix_package.core = core_package
    strix_package.interface = interface_package

    monkeypatch.setitem(sys.modules, "strix", strix_package)
    monkeypatch.setitem(sys.modules, "strix.core", core_package)
    monkeypatch.setitem(sys.modules, "strix.core.inputs", inputs_module)
    monkeypatch.setitem(sys.modules, "strix.interface", interface_package)
    monkeypatch.setitem(sys.modules, "strix.interface.scan_setup", scan_setup_module)
    monkeypatch.setitem(sys.modules, "strix.interface.main", main_module)
    monkeypatch.setattr(launcher, "_require_supported_version", lambda: None)
    monkeypatch.setenv("LLM_TIMEOUT", "300")
    monkeypatch.setenv("LLM_STREAM_IDLE_TIMEOUT", "300")

    result = launcher.install_runtime_compatibility()

    assert result is main_module
    assert launcher.os.environ["LLM_TIMEOUT"] == "0"
    assert launcher.os.environ["LLM_STREAM_IDLE_TIMEOUT"] == "0"
    assert isinstance(scan_setup_module.asyncio, launcher.UnboundedInferenceAsyncio)
    assert isinstance(main_module.asyncio, launcher.UnboundedInferenceAsyncio)
    inputs_module.make_model_settings("model", request_timeout=300, other="kept")
    assert calls == [
        {
            "args": ("model",),
            "kwargs": {"request_timeout": None, "other": "kept"},
        }
    ]
    assert asyncio.wait_for is not scan_setup_module.asyncio.wait_for


def test_launcher_main_enters_patched_strix_main(monkeypatch) -> None:
    """CLI main delegates exactly once after installing compatibility."""
    launcher = _load_launcher()
    calls: list[str] = []
    fake_main = types.SimpleNamespace(main=lambda: calls.append("main"))
    monkeypatch.setattr(launcher, "install_runtime_compatibility", lambda: fake_main)

    launcher.main()

    assert calls == ["main"]


def test_installer_sha256_and_regular_file_contract(tmp_path) -> None:
    """Hashing and regular-file admission reject symlinks and preserve bytes."""
    installer = _load_installer()
    source = tmp_path / "source"
    source.write_bytes(b"trusted")
    symlink = tmp_path / "link"
    symlink.symlink_to(source)

    assert len(installer._sha256(source)) == 64
    assert installer._regular_file(source, "source") == source.resolve()
    with pytest.raises(RuntimeError, match="regular, non-symlink"):
        installer._regular_file(symlink, "source")


def test_installer_validates_runtime_identity(monkeypatch, tmp_path) -> None:
    """Executable identity requires trusted root placement and exact SHA-256."""
    installer = _load_installer()
    scripts_root = tmp_path / "scripts"
    scripts_root.mkdir()
    executable = scripts_root / "strix"
    executable.write_bytes(b"binary")
    digest = installer._sha256(executable)

    installer._validate_installation(executable, scripts_root, digest.upper())

    with pytest.raises(RuntimeError, match="64-character"):
        installer._validate_installation(executable, scripts_root, "abc")
    with pytest.raises(RuntimeError, match="hexadecimal"):
        installer._validate_installation(executable, scripts_root, "z" * 64)
    with pytest.raises(RuntimeError, match="changed"):
        installer._validate_installation(executable, scripts_root, "0" * 64)

    outside = tmp_path / "outside"
    outside.write_bytes(b"binary")
    with pytest.raises(RuntimeError, match="outside STRIX_EXECUTABLE_ROOT"):
        installer._validate_installation(outside, scripts_root, installer._sha256(outside))

    root_link = tmp_path / "scripts-link"
    root_link.symlink_to(scripts_root, target_is_directory=True)
    with pytest.raises(RuntimeError, match="regular directory"):
        installer._validate_installation(executable, root_link, digest)


def test_installer_version_gate_accepts_only_reviewed_version(monkeypatch) -> None:
    """Installer refuses missing or unexpected upstream versions."""
    installer = _load_installer()

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.5.3")
    installer._require_supported_version()

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.6.0")
    with pytest.raises(RuntimeError, match="supports exactly 1.5.3"):
        installer._require_supported_version()

    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing)
    with pytest.raises(RuntimeError, match="is not installed"):
        installer._require_supported_version()


def test_installer_atomically_installs_and_publishes_identity(tmp_path) -> None:
    """Launcher publication is regular, executable, and records only identity metadata."""
    installer = _load_installer()
    scripts_root = tmp_path / "scripts"
    scripts_root.mkdir()
    source = tmp_path / "launcher.py"
    source.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
    github_env = tmp_path / "github-env"

    installed = installer.install_launcher(source, scripts_root)
    installer._append_github_environment(github_env, installed, scripts_root)

    assert installed == (scripts_root / installer.LAUNCHER_NAME).resolve()
    assert installed.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert installed.stat().st_mode & 0o111
    environment = github_env.read_text(encoding="utf-8")
    assert f"STRIX_EXECUTABLE_PATH={installed}" in environment
    assert f"STRIX_EXECUTABLE_ROOT={scripts_root.resolve()}" in environment
    assert f"STRIX_EXECUTABLE_SHA256={installer._sha256(installed)}" in environment
    assert "CWL_STRIX_UNBOUNDED_INFERENCE=1" in environment

    destination_link = scripts_root / installer.LAUNCHER_NAME
    destination_link.unlink()
    destination_link.symlink_to(source)
    with pytest.raises(RuntimeError, match="destination must not be a symlink"):
        installer.install_launcher(source, scripts_root)


def test_installer_parser_requires_every_trusted_input() -> None:
    """The CLI cannot silently omit an identity-binding input."""
    installer = _load_installer()
    parser = installer.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_installer_main_composes_validation_install_and_publication(monkeypatch, tmp_path) -> None:
    """CLI main orders version, identity, install, and environment publication."""
    installer = _load_installer()
    source = tmp_path / "source"
    executable = tmp_path / "strix"
    scripts_root = tmp_path / "scripts"
    github_env = tmp_path / "env"
    source.write_text("launcher", encoding="utf-8")
    executable.write_text("strix", encoding="utf-8")
    scripts_root.mkdir()
    expected = "1" * 64
    calls: list[object] = []

    arguments = types.SimpleNamespace(
        launcher=source,
        strix_executable=executable,
        scripts_root=scripts_root,
        expected_sha256=expected,
        github_env=github_env,
    )
    monkeypatch.setattr(installer, "build_parser", lambda: types.SimpleNamespace(parse_args=lambda: arguments))
    monkeypatch.setattr(installer, "_require_supported_version", lambda: calls.append("version"))
    monkeypatch.setattr(
        installer,
        "_validate_installation",
        lambda *args: calls.append(("validate", args)),
    )
    installed = scripts_root / installer.LAUNCHER_NAME
    monkeypatch.setattr(installer, "install_launcher", lambda *args: calls.append(("install", args)) or installed)
    monkeypatch.setattr(
        installer,
        "_append_github_environment",
        lambda *args: calls.append(("publish", args)),
    )

    installer.main()

    assert calls[0] == "version"
    assert calls[1] == ("validate", (executable, scripts_root, expected))
    assert calls[2] == ("install", (source, scripts_root))
    assert calls[3] == ("publish", (github_env, installed, scripts_root))



def test_installer_rejects_absent_github_environment(tmp_path) -> None:
    """Publishing without the workflow environment file must fail closed."""
    installer = _load_installer()

    with pytest.raises(RuntimeError, match="GITHUB_ENV is required"):
        installer._append_github_environment(None, tmp_path / "launcher", tmp_path)


def test_installer_script_entrypoint_runs_bound_cli(monkeypatch, tmp_path) -> None:
    """The real installer entrypoint validates and publishes bound file identities."""
    installer = _load_installer()
    scripts_root = tmp_path / "scripts"
    scripts_root.mkdir()
    source = tmp_path / "launcher.py"
    source.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
    executable = scripts_root / "strix"
    executable.write_bytes(b"reviewed-strix")
    github_env = tmp_path / "github-env"
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.5.3")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(INSTALLER),
            "--launcher",
            str(source),
            "--strix-executable",
            str(executable),
            "--scripts-root",
            str(scripts_root),
            "--expected-sha256",
            installer._sha256(executable),
            "--github-env",
            str(github_env),
        ],
    )

    runpy.run_path(str(INSTALLER), run_name="__main__")

    installed = scripts_root / installer.LAUNCHER_NAME
    assert installed.is_file()
    assert f"STRIX_EXECUTABLE_PATH={installed.resolve()}" in github_env.read_text(
        encoding="utf-8"
    )


def test_launcher_script_entrypoint_enters_patched_strix(monkeypatch) -> None:
    """The real launcher entrypoint installs compatibility before entering Strix."""
    calls: list[str] = []
    strix_package = types.ModuleType("strix")
    core_package = types.ModuleType("strix.core")
    interface_package = types.ModuleType("strix.interface")
    inputs_module = types.ModuleType("strix.core.inputs")
    scan_setup_module = types.ModuleType("strix.interface.scan_setup")
    main_module = types.ModuleType("strix.interface.main")
    inputs_module.make_model_settings = lambda *args, **kwargs: kwargs
    scan_setup_module.asyncio = asyncio
    main_module.asyncio = asyncio
    main_module.main = lambda: calls.append("main")
    core_package.inputs = inputs_module
    interface_package.scan_setup = scan_setup_module
    interface_package.main = main_module
    strix_package.core = core_package
    strix_package.interface = interface_package
    monkeypatch.setitem(sys.modules, "strix", strix_package)
    monkeypatch.setitem(sys.modules, "strix.core", core_package)
    monkeypatch.setitem(sys.modules, "strix.core.inputs", inputs_module)
    monkeypatch.setitem(sys.modules, "strix.interface", interface_package)
    monkeypatch.setitem(
        sys.modules,
        "strix.interface.scan_setup",
        scan_setup_module,
    )
    monkeypatch.setitem(sys.modules, "strix.interface.main", main_module)
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.5.3")
    monkeypatch.setenv("LLM_TIMEOUT", "300")
    monkeypatch.setenv("LLM_STREAM_IDLE_TIMEOUT", "300")

    runpy.run_path(str(LAUNCHER), run_name="__main__")

    assert calls == ["main"]
