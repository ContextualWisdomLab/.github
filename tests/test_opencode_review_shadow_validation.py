"""Strict validation and CLI tests for shadow routing and verification."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from opencode_review_shadow_test_support import (
    SHADOW_PATH,
    VERIFY_PATH,
    candidate,
    request,
    shadow,
    verification_input,
    verifier_decision,
    verify,
    write_json,
)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "unknown fields"),
        (
            lambda value: value["policy"].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["changed_files"][0].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["policy"]["model_pool"][0].update(
                {"unexpected": True}
            ),
            "unknown fields",
        ),
        (lambda value: value.update({"schema_version": "2.0"}), "schema_version"),
        (lambda value: value.update({"pull_request_number": True}), "integer"),
        (
            lambda value: value["policy"].update({"shadow_mode": False}),
            "shadow_mode",
        ),
        (
            lambda value: value["policy"].update({"publication_enabled": True}),
            "publication_enabled",
        ),
        (
            lambda value: value["changed_files"][0].update({"path": "../secret"}),
            "relative source path",
        ),
        (
            lambda value: value["changed_files"][0].update({"additions": True}),
            "integer",
        ),
        (
            lambda value: value["policy"]["model_pool"][0].update(
                {"prompt_sha256": "sha256:bad"}
            ),
            "sha256",
        ),
        (
            lambda value: value["policy"].update({"attempt_timeout_seconds": 0}),
            "timeout",
        ),
    ],
)
def test_routing_request_rejects_malformed_or_extensible_evidence(
    mutate: Any, message: str
) -> None:
    """Every request, policy, file, and model layer must fail closed."""
    value = request()
    mutate(value)
    with pytest.raises(shadow.ShadowValidationError, match=message):
        shadow.build_plan(value)


def test_routing_rejects_empty_files_duplicate_models_and_invalid_roles() -> None:
    """The planner requires material evidence and unique supported model descriptors."""
    empty = request(files=[])
    with pytest.raises(shadow.ShadowValidationError, match="changed_files"):
        shadow.build_plan(empty)

    duplicate = request()
    duplicate["policy"]["model_pool"].append(
        dict(duplicate["policy"]["model_pool"][0])
    )
    with pytest.raises(shadow.ShadowValidationError, match="descriptor_id"):
        shadow.build_plan(duplicate)

    invalid_role = request()
    invalid_role["policy"]["model_pool"][0]["role_codes"] = ["administrator"]
    with pytest.raises(shadow.ShadowValidationError, match="role_codes"):
        shadow.build_plan(invalid_role)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.pop("repository"), "missing fields"),
        (lambda value: value.update({"repository": ""}), "non-empty string"),
        (
            lambda value: value["policy"]["model_pool"][0].update(
                {"role_codes": []}
            ),
            "non-empty list",
        ),
        (
            lambda value: value["policy"]["model_pool"][0].update(
                {"role_codes": ["general_detector", "general_detector"]}
            ),
            "duplicates",
        ),
        (
            lambda value: value["changed_files"][0].update({"risk_tags": [""]}),
            "risk_tags",
        ),
        (lambda value: value["policy"].update({"model_pool": []}), "model_pool"),
    ],
)
def test_routing_rejects_empty_duplicate_or_incomplete_contract_fields(
    mutate: Any, message: str
) -> None:
    """Strict routing validation covers missing and structurally empty evidence."""
    value = request()
    mutate(value)
    with pytest.raises(shadow.ShadowValidationError, match=message):
        shadow.build_plan(value)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "unknown fields"),
        (
            lambda value: value["verification_policy"].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["source_index"][0].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["detector_attempts"][0].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["candidates"][0].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["verifier_decisions"][0].update(
                {"unexpected": True}
            ),
            "unknown fields",
        ),
        (lambda value: value.update({"head_sha": "main"}), "commit SHA"),
        (
            lambda value: value["verification_policy"].update(
                {"shadow_mode": False}
            ),
            "shadow_mode",
        ),
        (
            lambda value: value["verification_policy"].update(
                {"publication_enabled": True}
            ),
            "publication_enabled",
        ),
        (
            lambda value: value["verification_policy"].update(
                {"minimum_independent_verifiers": True}
            ),
            "integer",
        ),
        (
            lambda value: value["detector_attempts"][0].update(
                {"reviewed_head_sha": "c" * 40}
            ),
            "reviewed_head_sha",
        ),
        (
            lambda value: value["candidates"][0].update(
                {"reviewed_head_sha": "c" * 40}
            ),
            "reviewed_head_sha",
        ),
        (
            lambda value: value["verifier_decisions"][0].update(
                {"outcome": "uncertain"}
            ),
            "outcome",
        ),
    ],
)
def test_verification_bundle_rejects_malformed_or_stale_evidence(
    mutate: Any, message: str
) -> None:
    """Every verification layer must remain strict and exact-head bound."""
    value = verification_input()
    mutate(value)
    with pytest.raises(verify.VerificationValidationError, match=message):
        verify.verify_bundle(value)


def test_verification_rejects_duplicate_or_unknown_identity_references() -> None:
    """Source, attempt, candidate, and decision identities cannot be duplicated or forged."""
    duplicate_source = verification_input()
    duplicate_source["source_index"].append(dict(duplicate_source["source_index"][0]))
    with pytest.raises(verify.VerificationValidationError, match="source identity"):
        verify.verify_bundle(duplicate_source)

    duplicate_attempt = verification_input()
    duplicate_attempt["detector_attempts"].append(
        dict(duplicate_attempt["detector_attempts"][0])
    )
    with pytest.raises(verify.VerificationValidationError, match="attempt_id"):
        verify.verify_bundle(duplicate_attempt)

    duplicate_candidate = verification_input()
    duplicate_candidate["candidates"].append(dict(duplicate_candidate["candidates"][0]))
    with pytest.raises(verify.VerificationValidationError, match="candidate_id"):
        verify.verify_bundle(duplicate_candidate)

    unknown_candidate = verification_input(
        decisions=[verifier_decision("unknown_candidate")]
    )
    with pytest.raises(verify.VerificationValidationError, match="unknown candidate"):
        verify.verify_bundle(unknown_candidate)

    unknown_attempt = verification_input(
        candidates=[candidate(detector_attempt_id="unknown_detector")]
    )
    with pytest.raises(verify.VerificationValidationError, match="unknown detector"):
        verify.verify_bundle(unknown_attempt)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"source_index": {}}), "must be a list"),
        (lambda value: value.update({"schema_version": "2.0"}), "schema_version"),
        (lambda value: value.update({"risk_tier": "unknown"}), "risk_tier"),
        (
            lambda value: value["verification_policy"].update(
                {"require_model_diversity": 1}
            ),
            "require_model_diversity",
        ),
        (
            lambda value: value["source_index"][0].update(
                {"relationship": "untrusted"}
            ),
            "relationship",
        ),
        (
            lambda value: value["detector_attempts"][0].update(
                {"phase": "verifier"}
            ),
            "phase",
        ),
        (
            lambda value: value["detector_attempts"][0].update(
                {"status": "queued"}
            ),
            "status",
        ),
        (
            lambda value: value["candidates"][0].update({"blocking": 1}),
            "booleans",
        ),
        (
            lambda value: value["verifier_decisions"][0].update(
                {"verifier_attempt_id": "unknown_verifier"}
            ),
            "unknown verifier",
        ),
        (
            lambda value: value["verifier_decisions"].append(
                dict(value["verifier_decisions"][0])
            ),
            "decision identity",
        ),
    ],
)
def test_verification_rejects_additional_closed_contract_failures(
    mutate: Any, message: str
) -> None:
    """Strict verification validation covers every closed-schema authority boundary."""
    value = verification_input()
    mutate(value)
    with pytest.raises(verify.VerificationValidationError, match=message):
        verify.verify_bundle(value)


def test_strict_json_loaders_reject_duplicate_keys_and_nonfinite_numbers(
    tmp_path: Path,
) -> None:
    """Both tools reject ambiguous JSON objects and Python numeric extensions."""
    for module in (shadow, verify):
        duplicate = tmp_path / f"duplicate-{module.__name__}.json"
        duplicate.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
        with pytest.raises(module.validation_error_type(), match="duplicate JSON key"):
            module.load_json(duplicate)

        nonfinite = tmp_path / f"nonfinite-{module.__name__}.json"
        nonfinite.write_text('{"line": Infinity}')
        with pytest.raises(module.validation_error_type(), match="non-finite JSON number"):
            module.load_json(nonfinite)


def test_plan_and_verification_clis_write_atomic_outputs_with_stable_statuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Offline CLIs distinguish success from malformed evidence and leave no temp files."""
    request_path = tmp_path / "request.json"
    plan_path = tmp_path / "nested" / "plan.json"
    write_json(request_path, request())
    assert (
        shadow.main(
            ["plan", "--input", str(request_path), "--output", str(plan_path)]
        )
        == 0
    )
    assert json.loads(plan_path.read_text(encoding="utf-8"))["shadow_mode"] is True
    assert not plan_path.with_name(f".{plan_path.name}.tmp").exists()

    request_path.write_text("[]", encoding="utf-8")
    assert (
        shadow.main(
            ["plan", "--input", str(request_path), "--output", str(plan_path)]
        )
        == 2
    )
    assert "shadow review request rejected" in capsys.readouterr().err

    bundle_path = tmp_path / "bundle.json"
    report_path = tmp_path / "nested" / "verification.json"
    write_json(bundle_path, verification_input())
    assert (
        verify.main(
            ["--input", str(bundle_path), "--output", str(report_path)]
        )
        == 0
    )
    assert json.loads(report_path.read_text(encoding="utf-8"))[
        "publication_enabled"
    ] is False
    assert not report_path.with_name(f".{report_path.name}.tmp").exists()

    bundle_path.write_text("[]", encoding="utf-8")
    assert (
        verify.main(
            ["--input", str(bundle_path), "--output", str(report_path)]
        )
        == 2
    )
    assert "shadow verification rejected" in capsys.readouterr().err


def test_module_entrypoints_and_public_docstrings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct execution routes through tested CLIs and every public callable is documented."""
    request_path = tmp_path / "request.json"
    plan_path = tmp_path / "plan.json"
    write_json(request_path, request())
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SHADOW_PATH),
            "plan",
            "--input",
            str(request_path),
            "--output",
            str(plan_path),
        ],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(SHADOW_PATH), run_name="__main__")

    bundle_path = tmp_path / "bundle.json"
    report_path = tmp_path / "report.json"
    write_json(bundle_path, verification_input())
    monkeypatch.setattr(
        "sys.argv",
        [str(VERIFY_PATH), "--input", str(bundle_path), "--output", str(report_path)],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(VERIFY_PATH), run_name="__main__")

    for module in (shadow, verify):
        missing = [
            name
            for name, value in vars(module).items()
            if not name.startswith("_")
            and (isinstance(value, type) or callable(value))
            and getattr(value, "__module__", None) == module.__name__
            and not getattr(value, "__doc__", None)
        ]
        assert missing == []


def test_shadow_primitives_register_fail_closed_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path-based primitives load must import the exclusive writer."""
    import importlib.util

    primitives_path = SHADOW_PATH.with_name("opencode_review_shadow_primitives.py")
    module_dir = str(primitives_path.parent)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != module_dir])
    spec = importlib.util.spec_from_file_location(
        "opencode_review_shadow_primitives_direct", primitives_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert sys.path[0] == module_dir


def test_shadow_atomic_write_refuses_symlink_parent(tmp_path: Path) -> None:
    """Shadow JSON publication must not follow a swapped parent directory."""
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    link_parent = tmp_path / "link"
    link_parent.symlink_to(real_parent)
    with pytest.raises(ValueError, match="parent directory must not be a symbolic link"):
        shadow.atomic_write_json(link_parent / "plan.json", {"ok": True})
    assert not (real_parent / "plan.json").exists()
