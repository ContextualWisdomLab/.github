"""Shared fixtures for contextual-orchestrator policy integration tests."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci import contextual_fallback_policy as policy


STUB_MODULE = '''
from dataclasses import dataclass

@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    provider: str
    model: str
    cost_tier: str
    priority: int
    required_credentials: tuple[str, ...]
    repository_visibilities: frozenset[str]
    capabilities: frozenset[str]

@dataclass(frozen=True)
class FallbackContext:
    repository_visibility: str
    available_credentials: frozenset[str]
    required_capabilities: frozenset[str]
    allow_paid: bool

def load_fallback_manifest(document, agent):
    raw = document["agents"][agent]["candidates"]
    return tuple(Candidate(
        candidate_id=item["candidate_id"],
        provider=item["provider"],
        model=item["model"],
        cost_tier=item["cost_tier"],
        priority=item.get("priority", 100),
        required_credentials=tuple(item.get("required_credentials", [])),
        repository_visibilities=frozenset(item.get("repository_visibilities", ["public", "private", "internal"])),
        capabilities=frozenset(item.get("capabilities", ["text"])),
    ) for item in raw)

def build_fallback_plan(candidates, context):
    eligible = []
    for index, candidate in enumerate(candidates):
        if context.repository_visibility not in candidate.repository_visibilities:
            continue
        if set(candidate.required_credentials) - set(context.available_credentials):
            continue
        if set(context.required_capabilities) - set(candidate.capabilities):
            continue
        if candidate.cost_tier == "paid" and not context.allow_paid:
            continue
        eligible.append((index, candidate))
    if not eligible:
        raise RuntimeError("no eligible candidates")
    eligible.sort(key=lambda pair: (0 if pair[1].cost_tier == "free" else 1, pair[1].priority, pair[0]))
    return type("Plan", (), {"candidates": tuple(candidate for _, candidate in eligible)})()
'''


def blob_sha(data: bytes) -> str:
    """Return a Git blob identity for fixture receipts."""
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


@pytest.fixture()
def stub_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Install a verified minimal policy package and manifest in a temp root."""
    root = tmp_path / "vendor"
    package = root / "contextual_orchestrator"
    package.mkdir(parents=True)
    init_path = package / "__init__.py"
    module_path = package / "model_fallback.py"
    license_path = root / "LICENSE"
    init_path.write_text('"""stub package"""\n', encoding="utf-8")
    module_path.write_text(STUB_MODULE, encoding="utf-8")
    license_path.write_text("stub license\n", encoding="utf-8")
    source_files = {
        "contextual_orchestrator/model_fallback.py": blob_sha(module_path.read_bytes()),
        "LICENSE": blob_sha(license_path.read_bytes()),
    }
    integration_files = {
        "contextual_orchestrator/__init__.py": blob_sha(init_path.read_bytes())
    }
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_repository": "stub/repo",
                "source_commit": "a" * 40,
                "source_files": source_files,
                "integration_files": integration_files,
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agents": {
                    "agent": {
                        "candidates": [
                            {
                                "candidate_id": "paid",
                                "provider": "paid",
                                "model": "paid/model",
                                "cost_tier": "paid",
                                "priority": 0,
                                "required_credentials": ["PAID_KEY"],
                                "repository_visibilities": ["public", "private"],
                                "capabilities": ["text", "code_review"],
                            },
                            {
                                "candidate_id": "free-b",
                                "provider": "free",
                                "model": "free/b",
                                "cost_tier": "free",
                                "priority": 20,
                                "required_credentials": ["FREE_KEY"],
                                "repository_visibilities": ["public"],
                                "capabilities": ["text", "code_review"],
                            },
                            {
                                "candidate_id": "free-a",
                                "provider": "free",
                                "model": "free/a",
                                "cost_tier": "free",
                                "priority": 10,
                                "required_credentials": ["FREE_KEY"],
                                "repository_visibilities": ["public"],
                                "capabilities": ["text", "code_review"],
                            },
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "VENDOR_ROOT", root)
    monkeypatch.setattr(policy, "VENDOR_PACKAGE_ROOT", package)
    monkeypatch.setattr(policy, "VENDOR_RECEIPT_PATH", receipt)
    monkeypatch.setattr(policy, "POLICY_MANIFEST_PATH", manifest)
    monkeypatch.setattr(policy, "SOURCE_REPOSITORY", "stub/repo")
    monkeypatch.setattr(policy, "SOURCE_COMMIT", "a" * 40)
    monkeypatch.setattr(policy, "EXPECTED_SOURCE_BLOBS", source_files)
    monkeypatch.setattr(policy, "EXPECTED_INTEGRATION_BLOBS", integration_files)
    for name in list(sys.modules):
        if name == "contextual_orchestrator" or name.startswith(
            "contextual_orchestrator."
        ):
            sys.modules.pop(name)
    yield SimpleNamespace(
        root=root,
        package=package,
        receipt=receipt,
        manifest=manifest,
        source_files=source_files,
        integration_files=integration_files,
    )
    for name in list(sys.modules):
        if name == "contextual_orchestrator" or name.startswith(
            "contextual_orchestrator."
        ):
            sys.modules.pop(name)
