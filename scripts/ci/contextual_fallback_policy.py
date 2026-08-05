#!/usr/bin/env python3
"""Load and apply the vendored contextual-orchestrator fallback policy.

The integration verifies every vendored source blob before importing it, then
uses contextual-orchestrator's strict manifest parser and deterministic planner.
Only credential names are inspected. Secret values are never serialized.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VENDOR_ROOT = REPOSITORY_ROOT / "vendor" / "contextual-orchestrator"
VENDOR_PACKAGE_ROOT = VENDOR_ROOT / "contextual_orchestrator"
VENDOR_RECEIPT_PATH = VENDOR_ROOT / "VENDOR_RECEIPT.json"
POLICY_MANIFEST_PATH = REPOSITORY_ROOT / "config" / "llm-fallback-policy.json"
SOURCE_REPOSITORY = "ContextualWisdomLab/contextual-orchestrator"
SOURCE_COMMIT = "40c6a4b419cdf8fa90c422acb5443a0e1cca5d16"
MAX_JSON_BYTES = 262_144
EXPECTED_SOURCE_BLOBS = {
    "contextual_orchestrator/_fallback_manifest.py": "60458fbdffb180e089cf6da378c560a476635557",
    "contextual_orchestrator/_fallback_plan.py": "8f6e0c0e328a035e613456cf7a1d14062e1c4382",
    "contextual_orchestrator/_fallback_types.py": "8f1cafdf26ba0e2371e310d377db5c0528a88557",
    "LICENSE": "591bbf197b355e60604618c8a8a50bc5a839b204",
}
EXPECTED_INTEGRATION_BLOBS = {
    "contextual_orchestrator/__init__.py": "ec227439ce0c395682d086c24e7f0246a1dc612a",
    "contextual_orchestrator/model_fallback.py": "2d7b183184c1d13a0465d01ea93042a1426ec38c",
}
_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "source_repository",
        "source_commit",
        "source_files",
        "integration_files",
    }
)


class FallbackPolicyIntegrationError(RuntimeError):
    """Report a fail-closed central fallback-policy integration error."""


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting duplicate security-control keys."""
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise FallbackPolicyIntegrationError(f"duplicate JSON key: {key}")
        parsed[key] = value
    return parsed


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    """Read a bounded regular UTF-8 JSON object without following symlinks."""
    if not path.is_file() or path.is_symlink():
        raise FallbackPolicyIntegrationError(
            f"{label} must be a regular non-symlink file"
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FallbackPolicyIntegrationError(f"{label} could not be read") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise FallbackPolicyIntegrationError(f"{label} exceeds {MAX_JSON_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
        parsed = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FallbackPolicyIntegrationError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise FallbackPolicyIntegrationError(f"{label} must be a JSON object")
    return parsed


def git_blob_sha(path: Path) -> str:
    """Return the Git SHA-1 blob identity of one regular non-symlink file."""
    if not path.is_file() or path.is_symlink():
        raise FallbackPolicyIntegrationError(
            f"vendored path is not a regular non-symlink file: {path.name}"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FallbackPolicyIntegrationError(
            f"vendored path could not be read: {path.name}"
        ) from exc
    header = f"blob {len(data)}\0".encode("ascii")
    # Git's object format requires SHA-1 here; this is an identity comparison,
    # not a cryptographic signature or password/security primitive.
    return hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1  # nosec B324
        header + data,
        usedforsecurity=False,
    ).hexdigest()


def verify_vendored_module() -> None:
    """Verify the exact contextual-orchestrator commit and source blob receipt."""
    receipt = _read_json_object(VENDOR_RECEIPT_PATH, label="vendor receipt")
    unknown_keys = set(receipt) - _RECEIPT_KEYS
    missing_keys = _RECEIPT_KEYS - set(receipt)
    if unknown_keys or missing_keys:
        raise FallbackPolicyIntegrationError(
            "vendor receipt keys do not match the required schema"
        )
    if receipt.get("schema_version") != 1:
        raise FallbackPolicyIntegrationError("vendor receipt schema_version must be 1")
    if receipt.get("source_repository") != SOURCE_REPOSITORY:
        raise FallbackPolicyIntegrationError("vendor receipt source_repository mismatch")
    if receipt.get("source_commit") != SOURCE_COMMIT:
        raise FallbackPolicyIntegrationError("vendor receipt source_commit mismatch")
    source_files = receipt.get("source_files")
    integration_files = receipt.get("integration_files")
    if not isinstance(source_files, dict) or source_files != EXPECTED_SOURCE_BLOBS:
        raise FallbackPolicyIntegrationError("vendor receipt source file map mismatch")
    if (
        not isinstance(integration_files, dict)
        or integration_files != EXPECTED_INTEGRATION_BLOBS
    ):
        raise FallbackPolicyIntegrationError(
            "vendor receipt integration file map mismatch"
        )
    expected_files = EXPECTED_SOURCE_BLOBS | EXPECTED_INTEGRATION_BLOBS
    for relative_path, expected_sha in expected_files.items():
        candidate = VENDOR_ROOT / relative_path
        actual_sha = git_blob_sha(candidate)
        if actual_sha != expected_sha:
            raise FallbackPolicyIntegrationError(
                f"vendored contextual-orchestrator blob mismatch: {relative_path}"
            )


def load_policy_module() -> ModuleType:
    """Import the verified vendored contextual-orchestrator policy module."""
    verify_vendored_module()
    root = VENDOR_ROOT.resolve()
    existing = sys.modules.get("contextual_orchestrator.model_fallback")
    if existing is not None:
        existing_path = Path(str(getattr(existing, "__file__", ""))).resolve()
        if root not in existing_path.parents:
            raise FallbackPolicyIntegrationError(
                "an untrusted contextual_orchestrator module is already imported"
            )
        return existing
    root_text = str(root)
    sys.path.insert(0, root_text)
    try:
        module = importlib.import_module("contextual_orchestrator.model_fallback")
    except Exception as exc:
        raise FallbackPolicyIntegrationError(
            "vendored contextual-orchestrator policy could not be imported"
        ) from exc
    finally:
        if sys.path and sys.path[0] == root_text:
            sys.path.pop(0)
        else:
            try:
                sys.path.remove(root_text)
            except ValueError:
                pass
    module_path = Path(str(getattr(module, "__file__", ""))).resolve()
    if root not in module_path.parents:
        raise FallbackPolicyIntegrationError(
            "contextual-orchestrator resolved outside the verified vendor root"
        )
    return module


def _validated_configured_models(
    configured_models: Sequence[str] | None,
) -> tuple[str, ...] | None:
    """Validate an optional caller-owned candidate availability list."""
    if configured_models is None:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_model in configured_models:
        if not isinstance(raw_model, str):
            raise FallbackPolicyIntegrationError(
                "configured model identifiers must be strings"
            )
        model = raw_model.strip()
        if not model or any(character.isspace() for character in model):
            raise FallbackPolicyIntegrationError(
                "configured model identifiers must be non-empty whitespace-free tokens"
            )
        if model in seen:
            raise FallbackPolicyIntegrationError(
                f"duplicate configured model: {model}"
            )
        seen.add(model)
        normalized.append(model)
    if not normalized:
        raise FallbackPolicyIntegrationError("configured model list must not be empty")
    return tuple(normalized)


def plan_models(
    agent: str,
    *,
    repository_visibility: str,
    configured_models: Sequence[str] | None = None,
    required_capabilities: Sequence[str] = ("text",),
    allow_paid: bool = True,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return eligible model identifiers in verified free-before-paid order."""
    module = load_policy_module()
    document = _read_json_object(POLICY_MANIFEST_PATH, label="fallback manifest")
    try:
        candidates = module.load_fallback_manifest(document, agent)
    except Exception as exc:
        raise FallbackPolicyIntegrationError(
            f"fallback manifest is invalid for agent {agent!r}"
        ) from exc
    configured = _validated_configured_models(configured_models)
    if configured is not None:
        by_model = {candidate.model: candidate for candidate in candidates}
        unknown = [model for model in configured if model not in by_model]
        if unknown:
            raise FallbackPolicyIntegrationError(
                "configured models are absent from the shared policy: "
                + ",".join(unknown)
            )
        configured_set = set(configured)
        candidates = tuple(
            candidate for candidate in candidates if candidate.model in configured_set
        )
    environment = os.environ if environ is None else environ
    credential_names = {
        name for candidate in candidates for name in candidate.required_credentials
    }
    available_credentials = frozenset(
        name for name in credential_names if str(environment.get(name, "")).strip()
    )
    try:
        context = module.FallbackContext(
            repository_visibility=repository_visibility,
            available_credentials=available_credentials,
            required_capabilities=frozenset(required_capabilities),
            allow_paid=allow_paid,
        )
        plan = module.build_fallback_plan(candidates, context=context)
    except Exception as exc:
        raise FallbackPolicyIntegrationError(
            f"no valid fallback plan is available for agent {agent!r}"
        ) from exc
    return tuple(candidate.model for candidate in plan.candidates)


def _configured_models_from_args(args: argparse.Namespace) -> tuple[str, ...] | None:
    """Combine repeated configured models with one optional environment list."""
    values = list(args.configured_model)
    if args.configured_models_env:
        values.extend(os.environ.get(args.configured_models_env, "").split())
    return tuple(values) if values else None


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser used by the three central workflow adapters."""
    parser = argparse.ArgumentParser(prog="contextual-fallback-policy")
    parser.add_argument("--agent", required=True)
    parser.add_argument(
        "--repository-visibility",
        choices=("public", "private", "internal"),
        required=True,
    )
    parser.add_argument("--configured-model", action="append", default=[])
    parser.add_argument("--configured-models-env")
    parser.add_argument("--required-capability", action="append", default=[])
    parser.add_argument("--deny-paid", action="store_true")
    parser.add_argument("--format", choices=("lines", "json"), default="lines")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate and print one shared fallback plan without exposing secrets."""
    args = _build_parser().parse_args(argv)
    capabilities = tuple(args.required_capability) or ("text",)
    try:
        models = plan_models(
            args.agent,
            repository_visibility=args.repository_visibility,
            configured_models=_configured_models_from_args(args),
            required_capabilities=capabilities,
            allow_paid=not args.deny_paid,
        )
    except FallbackPolicyIntegrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps({"models": list(models)}, sort_keys=True, separators=(",", ":")))
    else:
        print("\n".join(models))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
