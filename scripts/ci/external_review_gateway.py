"""Fail-closed external review admission awaiting a released CO adapter.

This owner port does not implement or copy the proposed CO request contract.
Only a protected source change may register a reviewed immutable adapter.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit


class GatewayAdmissionError(RuntimeError):
    """Carry only an owner-defined, secret-free admission category."""


@dataclass
class ExternalGatewayConfig:
    """Bootstrap inputs from the trusted workflow, never PR-controlled values."""

    base_url: str
    token_file: Path
    require_zdr: bool

    def validate(self) -> None:
        """Require an HTTPS origin and private, owned, regular token file."""
        try:
            parsed_url = urlsplit(self.base_url)
            port_number = parsed_url.port
            if (
                any(
                    ord(character) <= 32 or ord(character) == 127
                    for character in self.base_url
                )
                or parsed_url.scheme != "https"
                or not parsed_url.hostname
                or parsed_url.username is not None
                or parsed_url.password is not None
                or parsed_url.path not in {"", "/"}
                or parsed_url.query
                or parsed_url.fragment
                or (port_number is not None and not 1 <= port_number <= 65535)
                or type(self.require_zdr) is not bool
            ):
                raise ValueError
            if not self.token_file.is_absolute() or any(
                ord(character) < 32 for character in str(self.token_file)
            ):
                raise ValueError
            token_stat = self.token_file.lstat()
            if (
                not stat.S_ISREG(token_stat.st_mode)
                or stat.S_IMODE(token_stat.st_mode) != 0o600
                or token_stat.st_uid != os.geteuid()
                or not 1 <= token_stat.st_size <= 8192
            ):
                raise ValueError
        except (OSError, ValueError):
            raise GatewayAdmissionError("invalid_gateway_configuration") from None


class InferenceProbePort(Protocol):
    """Released-adapter boundary; no provider credentials or admin readiness."""

    def list_models(self) -> list[str]:
        """Validate authenticated GET /v1/models and return exact model ids."""
        ...

    def probe_capability(
        self, capability_name: str, *, model_name: str, require_zdr: bool
    ) -> bool:
        """Validate a released capability contract using POST /v1/chat/completions.

        The adapter must verify TLS, reject redirects, reopen the private token
        without following symlinks, and validate response semantics. It must
        not call /readyz or accept an HTTP 200 alone as capability evidence.
        """
        ...


# CO #1084 is proposed, not a released adapter. Never populate this mapping
# from environment, a PR checkout, downloaded source, or an unverified SHA.
RELEASED_GATEWAY_ADAPTERS: dict[
    str, Callable[[ExternalGatewayConfig], InferenceProbePort]
] = {}


def verify_external_gateway(
    gateway_config: ExternalGatewayConfig, probe_port: InferenceProbePort
) -> dict:
    """Require every inference capability without partial readiness or fallback."""
    gateway_config.validate()
    try:
        model_inventory = probe_port.list_models()
        if (
            not isinstance(model_inventory, list)
            or not all(isinstance(model_name, str) for model_name in model_inventory)
            or "orchestrator/free" not in model_inventory
        ):
            raise GatewayAdmissionError("free_pool_unavailable")
        capability_results = {}
        for capability_name in ("json_object", "json_schema", "tool_call"):
            if (
                probe_port.probe_capability(
                    capability_name,
                    model_name="orchestrator/free",
                    require_zdr=gateway_config.require_zdr,
                )
                is not True
            ):
                raise GatewayAdmissionError("capability_unavailable")
            capability_results[capability_name] = "passed"
    except GatewayAdmissionError:
        raise
    except Exception:  # noqa: BLE001 - never expose transport, token or body details
        raise GatewayAdmissionError("inference_probe_failed") from None
    return {
        "model": "orchestrator/free",
        "capabilities": capability_results,
        "private_requests_require_zdr": gateway_config.require_zdr,
        "policy_evidence": "configured_gateway_policy_only",
    }


def main() -> int:
    """Admit only a source-registered released adapter and publish safe outputs."""
    adapter_revision = os.environ.get(
        "CONTEXTUAL_ORCHESTRATOR_GATEWAY_CONTRACT_REVISION", ""
    )
    adapter_factory = RELEASED_GATEWAY_ADAPTERS.get(adapter_revision)
    if adapter_factory is None:
        print("::error::released_contract_unavailable")
        return 1
    try:
        zdr_value = os.environ.get("CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR", "false")
        if zdr_value not in {"true", "false"}:
            raise GatewayAdmissionError("invalid_gateway_configuration")
        gateway_config = ExternalGatewayConfig(
            os.environ.get("CONTEXTUAL_ORCHESTRATOR_BASE_URL", ""),
            Path(os.environ.get("CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE", "")),
            zdr_value == "true",
        )
        gateway_config.validate()
        evidence = verify_external_gateway(
            gateway_config, adapter_factory(gateway_config)
        )
        runner_temp = os.environ["RUNNER_TEMP"]
        if not Path(runner_temp).is_absolute() or any(
            ord(character) < 32 for character in runner_temp
        ):
            raise GatewayAdmissionError("invalid_output_location")
        evidence_directory = Path(
            tempfile.mkdtemp(prefix="external-review-", dir=runner_temp)
        )
        evidence_path = evidence_directory / "preflight-evidence.json"
        evidence_path.write_text(
            json.dumps({**evidence, "contract_revision": adapter_revision}) + "\n"
        )
        evidence_path.chmod(0o600)
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as environment_file:
            environment_file.write(
                f"CONTEXTUAL_ORCHESTRATOR_BASE_URL={gateway_config.base_url.rstrip('/')}\n"
                f"CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE={gateway_config.token_file}\n"
                f"CONTEXTUAL_ORCHESTRATOR_PREFLIGHT_EVIDENCE={evidence_path}\n"
                f"CONTEXTUAL_ORCHESTRATOR_PRIVATE_REQUESTS_REQUIRE_ZDR={zdr_value}\n"
            )
    except Exception:  # noqa: BLE001 - bootstrap failures never reveal raw input
        print("::error::external_gateway_admission_failed")
        return 1
    print(
        "External gateway inference preflight passed; private requests must retain ZDR policy."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
