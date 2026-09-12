"""Exercise launcher fail-closed boundaries without requiring a scanner installation."""

import stat
import sys
import types

import pytest

from scripts.ci import strix_review_skill_launcher as launcher


@pytest.fixture
def native_skills(tmp_path, monkeypatch):
    """Model only the supported registration/render interface for boundary cases."""
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    for mode in ("quick", "standard", "deep"):
        (builtin / (mode + ".md")).write_text("Original " + mode + "\n")
    registered = []

    def register(directory):
        """Record native skill-directory registration for boundary checks."""
        registered.append(directory)

    def load(names):
        """Return the original packaged scan-mode text."""
        mode = names[0].split("/")[1]
        return {mode: (builtin / (mode + ".md")).read_text()}

    def render(*, scan_mode, is_root):
        """Read the registered scan-mode text for prompt preflight."""
        return (registered[-1] / "scan_modes" / (scan_mode + ".md")).read_text()

    for name, attributes in {
        "strix.agents.prompt": {"render_system_prompt": render},
        "strix.skills": {"load_skills": load, "register_skill_dir": register,
                         "registered_skill_dirs": lambda: tuple(registered)},
        "strix.utils.resource_paths": {"get_strix_resource_path": lambda *parts: builtin / parts[-1]},
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(launcher, "version", lambda _: "1.5.3")
    monkeypatch.setattr(launcher, "review_skill_instructions", lambda: "MANDATORY_METHODS")
    return builtin, registered


def test_bundle_reader_uses_trusted_local_loader():
    """The bootstrap retrieves the same complete central bytes as other consumers."""
    from scripts.ci.review_skill_bundle import review_skill_instructions

    assert launcher.review_skill_instructions() == review_skill_instructions()


def test_registration_preserves_modes_readonly_until_cli_returns(native_skills, monkeypatch, capsys):
    """The existing CLI receives original argv while all mode files remain protected."""
    builtin, registered = native_skills
    argv = ["strix", "-n", "-t", "/target", "--scan-mode", "quick"]
    monkeypatch.setattr(sys, "argv", argv)
    called = []

    def cli():
        """Check unchanged CLI arguments and immutable skill files during execution."""
        assert sys.argv is argv
        root = registered[-1]
        assert stat.S_IMODE(root.stat().st_mode) == 0o500
        for source in builtin.iterdir():
            target = root / "scan_modes" / source.name
            assert target.read_bytes() == source.read_bytes() + b"\n\nMANDATORY_METHODS"
            assert stat.S_IMODE(target.stat().st_mode) == 0o400
        called.append(True)

    module = types.ModuleType("strix.interface.main")
    module.main = cli
    monkeypatch.setitem(sys.modules, "strix.interface.main", module)
    launcher.main()
    assert called == [True]
    assert not registered[-1].exists()
    assert capsys.readouterr().out == "MANDATORY_METHODS\n"


@pytest.mark.parametrize("failure", ["version", "registered", "empty_mode", "missing_mode", "missing_methods", "missing_original", "bundle"])
def test_registration_rejects_partial_or_untrusted_inputs(native_skills, monkeypatch, failure):
    """No scanner entrypoint runs when required content cannot be verified/rendered."""
    builtin, registered = native_skills
    if failure == "version":
        monkeypatch.setattr(launcher, "version", lambda _: "0.0.0")
    elif failure == "registered":
        registered.append(builtin)
    elif failure == "empty_mode":
        (builtin / "quick.md").write_text("")
    elif failure == "missing_mode":
        (builtin / "quick.md").unlink()
    elif failure in {"missing_methods", "missing_original"}:
        result = "Original quick\n" if failure == "missing_methods" else "MANDATORY_METHODS"
        monkeypatch.setattr(sys.modules["strix.agents.prompt"], "render_system_prompt", lambda **_: result)
    else:
        def missing_bundle():
            """Simulate a missing mandatory method before scanner startup."""
            raise FileNotFoundError("missing mandatory method")
        monkeypatch.setattr(launcher, "review_skill_instructions", missing_bundle)
    with pytest.raises((ValueError, FileNotFoundError)):
        with launcher.registered_review_skills():
            pytest.fail("scanner could start despite invalid skill inputs")
    if registered and failure != "registered":
        assert not registered[-1].exists()


def test_script_entrypoint_registers_before_cli(native_skills, monkeypatch):
    """Execute the script entrypoint with native API doubles and the real bundle."""
    import importlib.metadata
    import runpy

    monkeypatch.setattr(importlib.metadata, "version", lambda _: "1.5.3")
    called = []
    module = types.ModuleType("strix.interface.main")
    module.main = lambda: called.append(True)
    monkeypatch.setitem(sys.modules, "strix.interface.main", module)
    runpy.run_path(launcher.__file__, run_name="__main__")
    assert called == [True]
