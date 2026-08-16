"""Plan and execute a bounded, non-publishing OpenCode shadow review pool."""

from __future__ import annotations

import argparse
import os
import runpy
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

_PRIMITIVES = runpy.run_path(
    str(Path(__file__).with_name("opencode_review_shadow_primitives.py"))
)
atomic_write_json = _PRIMITIVES["atomic_write_json"]
digest_bytes = _PRIMITIVES["digest_bytes"]
digest_json = _PRIMITIVES["digest_json"]
require_commit = _PRIMITIVES["require_commit"]
require_fields = _PRIMITIVES["require_fields"]
require_integer = _PRIMITIVES["require_integer"]
require_object = _PRIMITIVES["require_object"]
require_relative_path = _PRIMITIVES["require_relative_path"]
require_sha256 = _PRIMITIVES["require_sha256"]
require_string = _PRIMITIVES["require_string"]
strict_load_json = _PRIMITIVES["strict_load_json"]

ROOT_FIELDS = {
    "schema_version", "review_request_id", "repository", "pull_request_number",
    "base_sha", "head_sha", "diff_sha256", "evidence_sha256", "changed_files", "policy",
}
POLICY_FIELDS = {
    "shadow_mode", "publication_enabled", "maximum_detector_attempts",
    "maximum_recursive_verification_depth", "attempt_timeout_seconds", "model_pool",
}
FILE_FIELDS = {"path", "primary_language", "additions", "deletions", "risk_tags"}
MODEL_FIELDS = {
    "descriptor_id", "provider_id", "model_id", "agent_name", "role_codes",
    "reasoning_efforts", "prompt_sha256",
}
ROLES = {
    "general_detector", "correctness_detector", "security_detector", "workflow_detector",
    "data_model_detector", "numerical_detector", "experience_detector",
    "documentation_detector", "verifier", "recursive_verifier",
}
EFFORTS = {"low", "medium", "high"}


class ShadowValidationError(ValueError):
    """Raised when an untrusted routing request violates its strict contract."""


class InsufficientPoolError(ShadowValidationError):
    """Raised when policy cannot allocate every required independent role."""


class ShadowExecutionError(RuntimeError):
    """Raised before execution when a credential or filesystem boundary is untrusted."""


def validation_error_type() -> type[ShadowValidationError]:
    """Return the public validation error used by strict JSON loading."""
    return ShadowValidationError


def load_json(path: Path) -> Any:
    """Load one strict JSON input file."""
    return strict_load_json(path, ShadowValidationError)


def _string_list(value: Any, label: str, *, allowed: set[str] | None = None) -> list[str]:
    """Validate one non-empty, unique string-list field."""
    if not isinstance(value, list) or not value:
        raise ShadowValidationError(f"{label} must be a non-empty list")
    result = [require_string(item, label, ShadowValidationError) for item in value]
    if len(set(result)) != len(result):
        raise ShadowValidationError(f"{label} contains duplicates")
    if allowed is not None and not set(result) <= allowed:
        raise ShadowValidationError(f"{label} contains unsupported values")
    return result


def _validate_request(raw: Any) -> dict[str, Any]:
    """Validate every layer of an untrusted shadow-review request."""
    value = require_object(raw, "shadow review request", ShadowValidationError)
    require_fields(value, ROOT_FIELDS, "shadow review request", ShadowValidationError)
    if value["schema_version"] != "1.0":
        raise ShadowValidationError("unsupported schema_version")
    require_string(value["review_request_id"], "review_request_id", ShadowValidationError)
    require_string(value["repository"], "repository", ShadowValidationError)
    require_integer(value["pull_request_number"], "pull_request_number", ShadowValidationError, minimum=1)
    require_commit(value["base_sha"], "base_sha", ShadowValidationError)
    require_commit(value["head_sha"], "head_sha", ShadowValidationError)
    require_sha256(value["diff_sha256"], "diff_sha256", ShadowValidationError)
    require_sha256(value["evidence_sha256"], "evidence_sha256", ShadowValidationError)
    files = value["changed_files"]
    if not isinstance(files, list) or not files:
        raise ShadowValidationError("changed_files must be a non-empty list")
    for index, raw_file in enumerate(files):
        item = require_object(raw_file, f"changed_files[{index}]", ShadowValidationError)
        require_fields(item, FILE_FIELDS, f"changed_files[{index}]", ShadowValidationError)
        require_relative_path(item["path"], "relative source path", ShadowValidationError)
        require_string(item["primary_language"], "primary_language", ShadowValidationError)
        require_integer(item["additions"], "additions integer", ShadowValidationError)
        require_integer(item["deletions"], "deletions integer", ShadowValidationError)
        tags = item["risk_tags"]
        if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
            raise ShadowValidationError("risk_tags must be a string list")
    policy = require_object(value["policy"], "policy", ShadowValidationError)
    require_fields(policy, POLICY_FIELDS, "policy", ShadowValidationError)
    if policy["shadow_mode"] is not True:
        raise ShadowValidationError("shadow_mode must be true")
    if policy["publication_enabled"] is not False:
        raise ShadowValidationError("publication_enabled must be false")
    require_integer(policy["maximum_detector_attempts"], "maximum_detector_attempts", ShadowValidationError, minimum=1)
    require_integer(policy["maximum_recursive_verification_depth"], "maximum_recursive_verification_depth", ShadowValidationError)
    require_integer(policy["attempt_timeout_seconds"], "attempt timeout", ShadowValidationError, minimum=1)
    models = policy["model_pool"]
    if not isinstance(models, list) or not models:
        raise ShadowValidationError("model_pool must be a non-empty list")
    descriptor_ids: set[str] = set()
    for index, raw_model in enumerate(models):
        model = require_object(raw_model, f"model_pool[{index}]", ShadowValidationError)
        require_fields(model, MODEL_FIELDS, f"model_pool[{index}]", ShadowValidationError)
        descriptor = require_string(model["descriptor_id"], "descriptor_id", ShadowValidationError)
        if descriptor in descriptor_ids:
            raise ShadowValidationError("descriptor_id must be unique")
        descriptor_ids.add(descriptor)
        for field in ("provider_id", "model_id", "agent_name"):
            require_string(model[field], field, ShadowValidationError)
        _string_list(model["role_codes"], "role_codes", allowed=ROLES)
        _string_list(model["reasoning_efforts"], "reasoning_efforts", allowed=EFFORTS)
        require_sha256(model["prompt_sha256"], "prompt_sha256", ShadowValidationError)
    return value


def _risk_profile(value: dict[str, Any]) -> tuple[str, str, list[str], list[str], str, int]:
    """Derive deterministic risk, size, role, effort, and recursion policy."""
    tags = sorted({tag for item in value["changed_files"] for tag in item["risk_tags"]})
    total = sum(item["additions"] + item["deletions"] for item in value["changed_files"])
    bucket = "small" if total <= 50 else "medium" if total <= 250 else "large"
    specialist_roles: list[str] = []
    mapping = (
        ("security", "security_detector"), ("workflow", "workflow_detector"),
        ("data_model", "data_model_detector"), ("numerical", "numerical_detector"),
        ("experience", "experience_detector"),
    )
    for tag, role in mapping:
        if tag in tags:
            specialist_roles.append(role)
    documentation_only = bool(tags) and set(tags) <= {"documentation"}
    critical = ({"security", "workflow", "release"} <= set(tags)) or (
        "migration" in tags and bool({"security", "workflow"} & set(tags))
    )
    tier = "low" if documentation_only else "critical" if critical else "high" if specialist_roles else "standard"
    effort = "low" if tier == "low" else "medium" if tier == "standard" else "high"
    depth = min(value["policy"]["maximum_recursive_verification_depth"], 1) if tier == "critical" else 0
    return tier, bucket, tags, specialist_roles, effort, depth


def _choose_model(
    models: list[dict[str, Any]], role: str, effort: str, excluded: set[str]
) -> dict[str, Any]:
    """Select the first eligible model outside a prohibited identity set."""
    for model in models:
        if role in model["role_codes"] and effort in model["reasoning_efforts"] and model["model_id"] not in excluded:
            return model
    message = "independent verifier" if role in {"verifier", "recursive_verifier"} else role
    raise InsufficientPoolError(f"model pool cannot supply {message}")


def build_plan(raw: Any) -> dict[str, Any]:
    """Validate a request and build a deterministic, content-addressed shadow plan."""
    value = _validate_request(raw)
    tier, bucket, reasons, specialists, effort, depth = _risk_profile(value)
    detector_roles = ["general_detector", *specialists]
    if len(detector_roles) > value["policy"]["maximum_detector_attempts"]:
        raise InsufficientPoolError("detector attempt budget is below required roles")
    attempts: list[dict[str, Any]] = []
    detector_models: set[str] = set()
    for index, role in enumerate(detector_roles, start=1):
        model = _choose_model(value["policy"]["model_pool"], role, effort, set())
        detector_models.add(model["model_id"])
        attempts.append(_attempt(model, role, "detector", effort, f"detector_{index:03d}"))
    verifier_effort = "medium" if tier == "low" else effort
    verifier = _choose_model(value["policy"]["model_pool"], "verifier", verifier_effort, detector_models)
    attempts.append(_attempt(verifier, "verifier", "verifier", verifier_effort, "verifier_001"))
    if depth:
        recursive = _choose_model(
            value["policy"]["model_pool"], "recursive_verifier", effort,
            detector_models | {verifier["model_id"]},
        )
        attempts.append(_attempt(recursive, "recursive_verifier", "verifier", effort, "verifier_002"))
    plan: dict[str, Any] = {
        "schema_version": "1.0", "review_request_id": value["review_request_id"],
        "repository": value["repository"], "pull_request_number": value["pull_request_number"],
        "base_sha": value["base_sha"], "head_sha": value["head_sha"],
        "evidence_sha256": value["evidence_sha256"], "input_sha256": digest_json(value),
        "risk_tier": tier, "risk_reasons": reasons, "diff_size_bucket": bucket,
        "shadow_mode": True, "publication_enabled": False,
        "maximum_recursive_verification_depth": depth,
        "attempt_timeout_seconds": value["policy"]["attempt_timeout_seconds"],
        "attempts": attempts,
    }
    plan["plan_sha256"] = digest_json(plan)
    return plan


def _attempt(model: dict[str, Any], role: str, phase: str, effort: str, attempt_id: str) -> dict[str, Any]:
    """Build a credential-free normalized attempt descriptor."""
    return {
        "attempt_id": attempt_id, "phase": phase, "role_code": role,
        "provider_id": model["provider_id"], "model_id": model["model_id"],
        "agent_name": model["agent_name"], "reasoning_effort": effort,
        "prompt_sha256": model["prompt_sha256"],
    }


def _validate_execution_boundary(plan: dict[str, Any], evidence: Path, binary: Path, worktree: Path) -> str:
    """Validate secret, evidence, executable, and worktree boundaries."""
    secret = os.environ.get("NVIDIA_NIM_API_KEY")
    if not secret:
        raise ShadowExecutionError("NVIDIA_NIM_API_KEY is required")
    if digest_bytes(evidence.read_bytes()) != plan["evidence_sha256"]:
        raise ShadowExecutionError("evidence_sha256 does not match evidence")
    if binary.is_symlink():
        raise ShadowExecutionError("OpenCode binary must not be a symlink")
    mode = binary.stat().st_mode
    if not stat.S_ISREG(mode) or not os.access(binary, os.X_OK):
        raise ShadowExecutionError("OpenCode binary must be an executable file")
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ShadowExecutionError("OpenCode binary must not be group/world writable")
    if not worktree.is_dir() or worktree.is_symlink():
        raise ShadowExecutionError("working directory must be a trusted directory")
    return secret


def _run_attempt(
    attempt: dict[str, Any], plan: dict[str, Any], evidence: Path, output: Path,
    binary: Path, worktree: Path, detector_files: list[Path], secret: str,
) -> dict[str, Any]:
    """Run one fixed-argument OpenCode attempt and normalize its evidence."""
    stdout_path = output / f"{attempt['attempt_id']}.stdout.json"
    stderr_path = output / f"{attempt['attempt_id']}.stderr.txt"
    command = [
        str(binary), "run", "--agent", attempt["agent_name"], "--model", attempt["model_id"],
        "--variant", attempt["reasoning_effort"], "--format", "json", "--dir", str(worktree),
        "--file", str(evidence),
    ]
    for detector_file in detector_files:
        command.extend(("--file", str(detector_file)))
    command.append(f"role={attempt['role_code']} head={plan['head_sha']} shadow=true")
    environment = {"PATH": os.environ.get("PATH", ""), "NVIDIA_API_KEY": secret}
    try:
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True,
            timeout=plan["attempt_timeout_seconds"], env=environment,
        )
        stdout, stderr = completed.stdout, completed.stderr
        status_value = "complete" if completed.returncode == 0 else "failed"
        exit_code: int | None = completed.returncode
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or "")
        status_value, exit_code = "timed_out", None
    stdout = stdout.replace(secret, "[REDACTED_NVIDIA_API_KEY]")
    stderr = stderr.replace(secret, "[REDACTED_NVIDIA_API_KEY]")
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "attempt_id": attempt["attempt_id"], "phase": attempt["phase"],
        "role_code": attempt["role_code"], "provider_id": attempt["provider_id"],
        "model_id": attempt["model_id"], "reviewed_head_sha": plan["head_sha"],
        "status": status_value, "exit_code": exit_code,
        "stdout_file": stdout_path.relative_to(output).as_posix(),
        "stderr_file": stderr_path.relative_to(output).as_posix(),
        "stdout_sha256": digest_bytes(stdout.encode("utf-8")),
        "stderr_sha256": digest_bytes(stderr.encode("utf-8")),
    }


def _prepare_output_directory(output: Path) -> None:
    """Create a private empty output directory or reject unsafe reuse."""
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ShadowExecutionError("output directory must be a real directory")
    if output.exists():
        if output.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ShadowExecutionError("output directory must not be group/world writable")
        if any(output.iterdir()):
            raise ShadowExecutionError("output directory must be empty")
    else:
        output.mkdir(parents=True, mode=0o700)


def execute_plan(
    plan: dict[str, Any], *, evidence_path: Path, output_directory: Path,
    opencode_binary: Path, working_directory: Path,
) -> dict[str, Any]:
    """Execute detectors before verifiers with bounded isolation and no publication path."""
    secret = _validate_execution_boundary(plan, evidence_path, opencode_binary, working_directory)
    _prepare_output_directory(output_directory)
    records: list[dict[str, Any]] = []
    detector_files: list[Path] = []
    for attempt in plan["attempts"]:
        if attempt["phase"] == "verifier" and not detector_files:
            records.append({
                "attempt_id": attempt["attempt_id"], "phase": attempt["phase"],
                "role_code": attempt["role_code"], "provider_id": attempt["provider_id"],
                "model_id": attempt["model_id"], "reviewed_head_sha": plan["head_sha"],
                "status": "dependency_failed",
            })
            continue
        record = _run_attempt(
            attempt, plan, evidence_path, output_directory, opencode_binary,
            working_directory, detector_files if attempt["phase"] == "verifier" else [], secret,
        )
        records.append(record)
        if attempt["phase"] == "detector" and record["status"] == "complete":
            detector_files.append(output_directory / record["stdout_file"])
    manifest: dict[str, Any] = {
        "schema_version": "1.0", "shadow_mode": True, "publication_enabled": False,
        "plan_sha256": plan["plan_sha256"], "head_sha": plan["head_sha"], "attempts": records,
        "completed_attempt_count": sum(item["status"] == "complete" for item in records),
        "failed_attempt_count": sum(item["status"] != "complete" for item in records),
    }
    manifest["execution_sha256"] = digest_json(manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline plan CLI and return a stable process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--input", required=True, type=Path)
    plan_parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        atomic_write_json(arguments.output, build_plan(load_json(arguments.input)))
    except (ShadowValidationError, OSError) as error:
        print(f"shadow review request rejected: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
