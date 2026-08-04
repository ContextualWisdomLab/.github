"""Tests for the verified contextual-orchestrator policy integration."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci import contextual_fallback_policy as policy


def blob_sha(data: bytes) -> str:
    """Return a Git blob identity for fixture receipts."""
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def test_verified_policy_orders_all_free_models_before_paid(
    stub_policy: SimpleNamespace,
) -> None:
    """A paid priority of zero cannot jump ahead of free candidates."""
    models = policy.plan_models(
        "agent",
        repository_visibility="public",
        required_capabilities=("code_review",),
        environ={"FREE_KEY": "free", "PAID_KEY": "paid"},
    )
    assert models == ("free/a", "free/b", "paid/model")


def test_plan_filters_credentials_visibility_capabilities_and_configured_pool(
    stub_policy: SimpleNamespace,
) -> None:
    """Runtime eligibility and configured model intersection fail closed."""
    assert policy.plan_models(
        "agent",
        repository_visibility="private",
        configured_models=("paid/model",),
        required_capabilities=("code_review",),
        environ={"PAID_KEY": "present"},
    ) == ("paid/model",)
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="no valid"):
        policy.plan_models(
            "agent",
            repository_visibility="public",
            required_capabilities=("missing",),
            environ={"FREE_KEY": "present", "PAID_KEY": "present"},
        )
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="absent"):
        policy.plan_models(
            "agent",
            repository_visibility="public",
            configured_models=("unknown/model",),
            environ={},
        )


def test_configured_model_validation_rejects_unsafe_and_duplicate_values() -> None:
    """Configured pool tokens are whitespace-free, typed, unique, and non-empty."""
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="strings"):
        policy._validated_configured_models((object(),))  # type: ignore[arg-type]
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="whitespace-free"):
        policy._validated_configured_models(("bad model",))
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="must not be empty"):
        policy._validated_configured_models(())
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="duplicate"):
        policy._validated_configured_models(("one", "one"))
    assert policy._validated_configured_models(None) is None
    assert policy._validated_configured_models((" one ",)) == ("one",)


def test_json_reader_rejects_symlink_size_encoding_shape_and_duplicates(
    tmp_path: Path,
) -> None:
    """Policy control JSON accepts only bounded regular unambiguous objects."""
    missing = tmp_path / "missing.json"
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="regular"):
        policy._read_json_object(missing, label="test")
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="regular"):
        policy._read_json_object(link, label="test")
    oversized = tmp_path / "large.json"
    oversized.write_bytes(b"{" + b" " * policy.MAX_JSON_BYTES + b"}")
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="exceeds"):
        policy._read_json_object(oversized, label="test")
    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"\xff")
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="UTF-8 JSON"):
        policy._read_json_object(invalid, label="test")
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="JSON object"):
        policy._read_json_object(array, label="test")
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="duplicate JSON"):
        policy._read_json_object(duplicate, label="test")


def test_git_blob_sha_rejects_missing_and_symlink(tmp_path: Path) -> None:
    """Blob verification never follows symlinks or accepts missing paths."""
    missing = tmp_path / "missing"
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="regular"):
        policy.git_blob_sha(missing)
    target = tmp_path / "target"
    target.write_text("data", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="regular"):
        policy.git_blob_sha(link)
    assert policy.git_blob_sha(target) == blob_sha(b"data")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda receipt: receipt.update({"extra": True}), "keys"),
        (lambda receipt: receipt.update({"schema_version": 2}), "schema_version"),
        (lambda receipt: receipt.update({"source_repository": "wrong"}), "source_repository"),
        (lambda receipt: receipt.update({"source_commit": "b" * 40}), "source_commit"),
        (lambda receipt: receipt.update({"source_files": {}}), "source file map"),
        (lambda receipt: receipt.update({"integration_files": {}}), "integration file map"),
    ],
)
def test_vendor_receipt_schema_fails_closed(
    stub_policy: SimpleNamespace, mutation, message: str
) -> None:
    """Receipt identity and exact file maps are mandatory."""
    receipt = json.loads(stub_policy.receipt.read_text(encoding="utf-8"))
    mutation(receipt)
    stub_policy.receipt.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(policy.FallbackPolicyIntegrationError, match=message):
        policy.verify_vendored_module()


def test_vendor_blob_mismatch_and_existing_module_identity_fail_closed(
    stub_policy: SimpleNamespace,
) -> None:
    """Source tampering and an already-loaded outside package are rejected."""
    module_path = stub_policy.package / "model_fallback.py"
    original_module = module_path.read_text(encoding="utf-8")
    module_path.write_text(original_module + "\n# tampered\n", encoding="utf-8")
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="blob mismatch"):
        policy.verify_vendored_module()
    module_path.write_text(original_module, encoding="utf-8")
    sys.modules["contextual_orchestrator.model_fallback"] = SimpleNamespace(
        __file__="/tmp/outside/model_fallback.py"
    )
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="untrusted"):
        policy.load_policy_module()


def test_load_policy_module_reuses_verified_vendor_module(
    stub_policy: SimpleNamespace,
) -> None:
    """A verified already-loaded module is reused without path drift."""
    first = policy.load_policy_module()
    second = policy.load_policy_module()
    assert first is second
    assert stub_policy.root.resolve() in Path(first.__file__).resolve().parents


def test_manifest_parse_errors_are_normalized(
    stub_policy: SimpleNamespace,
) -> None:
    """Agent lookup or parser failures do not leak implementation details."""
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="invalid for agent"):
        policy.plan_models(
            "missing",
            repository_visibility="public",
            environ={},
        )


def test_cli_lines_json_environment_merge_and_error(
    stub_policy: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI produces machine-readable plans and secret-free bounded errors."""
    monkeypatch.setenv("POOL", "paid/model free/b free/a")
    monkeypatch.setenv("FREE_KEY", "secret-free")
    monkeypatch.setenv("PAID_KEY", "secret-paid")
    assert policy.main(
        [
            "--agent",
            "agent",
            "--repository-visibility",
            "public",
            "--configured-models-env",
            "POOL",
            "--required-capability",
            "code_review",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert output == "free/a\nfree/b\npaid/model\n"
    assert "secret" not in output

    assert policy.main(
        [
            "--agent",
            "agent",
            "--repository-visibility",
            "public",
            "--configured-model",
            "free/a",
            "--deny-paid",
            "--format",
            "json",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out) == {"models": ["free/a"]}

    assert policy.main(
        [
            "--agent",
            "agent",
            "--repository-visibility",
            "public",
            "--configured-model",
            "unknown/model",
        ]
    ) == 2
    error = capsys.readouterr().err
    assert "ERROR:" in error
    assert "secret" not in error


def test_configured_models_from_args_handles_empty_and_combined_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI configuration combines explicit tokens and a whitespace list."""
    assert policy._configured_models_from_args(
        SimpleNamespace(configured_model=[], configured_models_env=None)
    ) is None
    monkeypatch.setenv("POOL", "two three")
    assert policy._configured_models_from_args(
        SimpleNamespace(configured_model=["one"], configured_models_env="POOL")
    ) == ("one", "two", "three")


def test_json_and_blob_read_errors_are_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Filesystem read races are converted to stable integration errors."""
    path = tmp_path / "value.json"
    path.write_text("{}", encoding="utf-8")
    original = Path.read_bytes

    def fail_read(self: Path) -> bytes:
        if self == path:
            raise OSError("read failed")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="could not be read"):
        policy._read_json_object(path, label="test")
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="could not be read"):
        policy.git_blob_sha(path)


def test_import_failures_and_sys_path_cleanup_branches(
    stub_policy: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import errors and unusual sys.path mutations remain fail-closed."""
    root_text = str(stub_policy.root.resolve())

    def remove_then_fail(name: str):
        assert name == "contextual_orchestrator.model_fallback"
        sys.path.remove(root_text)
        raise ImportError("boom")

    monkeypatch.setattr(policy.importlib, "import_module", remove_then_fail)
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="could not be imported"):
        policy.load_policy_module()
    assert root_text not in sys.path


def test_import_cleanup_removes_nonleading_vendor_path_and_rejects_outside_module(
    stub_policy: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nonleading import paths are removed and imported module paths are verified."""
    root_text = str(stub_policy.root.resolve())

    def move_and_return(name: str):
        assert name == "contextual_orchestrator.model_fallback"
        assert sys.path.pop(0) == root_text
        sys.path.append(root_text)
        return SimpleNamespace(__file__="/tmp/outside/model_fallback.py")

    monkeypatch.setattr(policy.importlib, "import_module", move_and_return)
    with pytest.raises(policy.FallbackPolicyIntegrationError, match="outside"):
        policy.load_policy_module()
    assert root_text not in sys.path
