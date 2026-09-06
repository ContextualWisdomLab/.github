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
from enum import Enum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit


class ProbeErrorCategory(str, Enum):
    """Closed failure vocabulary accepted from a future released adapter."""

    AUTHENTICATION_FAILED = "authentication_failed"
    TRANSPORT_FAILED = "transport_failed"
    INVALID_RESPONSE = "invalid_response"
    POLICY_UNAVAILABLE = "policy_unavailable"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"


PROBE_NAMES = ("discovery", "json_object", "json_schema", "tool_call")


class GatewayAdmissionError(RuntimeError):
    """Carry only validated, bounded admission evidence, never exception text."""

    def __init__(
        self,
        error_category: str,
        probe_name: str = "bootstrap",
        http_status: int | None = None,
    ):
        """Project error details onto the closed, secret-free evidence fields."""
        allowed_categories = {item.value for item in ProbeErrorCategory} | {
            "invalid_gateway_configuration",
            "invalid_output_location",
            "external_gateway_admission_failed",
        }
        safe_category = (
            error_category
            if type(error_category) is str and error_category in allowed_categories
            else "invalid_response"
        )
        safe_probe = (
            probe_name
            if type(probe_name) is str and probe_name in (*PROBE_NAMES, "bootstrap")
            else "bootstrap"
        )
        safe_status = (
            http_status
            if type(http_status) is int and 100 <= http_status <= 599
            else None
        )
        self.evidence = {
            "probe_name": safe_probe,
            "http_status": safe_status,
            "result": "failed",
            "error_category": safe_category,
        }
        super().__init__(safe_category)


@dataclass(frozen=True)
class ProbeReceipt:
    """Semantic result; discovery success includes the exact free-model alias."""

    probe_name: str
    http_status: int | None
    error_category: ProbeErrorCategory | None = None

    def safe_evidence(self, expected_probe: str) -> dict:
        """Reject malformed adapter evidence before it reaches logs or gates."""
        if (
            type(self.probe_name) is not str
            or self.probe_name != expected_probe
            or (
                self.http_status is not None
                and (
                    type(self.http_status) is not int
                    or not 100 <= self.http_status <= 599
                )
            )
            or (
                self.error_category is not None
                and type(self.error_category) is not ProbeErrorCategory
            )
            or (self.error_category is None and self.http_status != 200)
        ):
            raise GatewayAdmissionError("invalid_response", expected_probe)
        error_category = (
            self.error_category.value if self.error_category is not None else None
        )
        if error_category is not None:
            raise GatewayAdmissionError(
                error_category, expected_probe, self.http_status
            )
        return {
            "probe_name": expected_probe,
            "http_status": self.http_status,
            "result": "passed",
            "error_category": None,
        }


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

    def list_models(self) -> ProbeReceipt:
        """Validate authenticated discovery and exact orchestrator/free presence.

        Return discovery policy_unavailable when the free pool is absent.
        Never return upstream model identifiers or raw response data.
        """
        ...

    def probe_capability(
        self, capability_name: str, *, model_name: str, require_zdr: bool
    ) -> ProbeReceipt:
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
    probe_evidence = []
    for probe_name in PROBE_NAMES:
        try:
            probe_receipt = (
                probe_port.list_models()
                if probe_name == "discovery"
                else probe_port.probe_capability(
                    probe_name,
                    model_name="orchestrator/free",
                    require_zdr=gateway_config.require_zdr,
                )
            )
        except Exception:  # noqa: BLE001 - typed failures must use receipts
            raise GatewayAdmissionError("invalid_response", probe_name) from None
        if type(probe_receipt) is not ProbeReceipt:
            raise GatewayAdmissionError("invalid_response", probe_name)
        probe_evidence.append(probe_receipt.safe_evidence(probe_name))
    return {
        "requested_model": "orchestrator/free",
        "capabilities": {name: "passed" for name in PROBE_NAMES[1:]},
        "probes": probe_evidence,
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
    except GatewayAdmissionError as admission_error:
        source_evidence = (
            admission_error.evidence if type(admission_error.evidence) is dict else {}
        )
        safe_error = GatewayAdmissionError(
            source_evidence.get("error_category", "invalid_response"),
            source_evidence.get("probe_name", "bootstrap"),
            source_evidence.get("http_status"),
        )
        print("::error::" + json.dumps(safe_error.evidence))
        return 1
    except Exception:  # noqa: BLE001 - bootstrap failures never reveal raw input
        print(
            "::error::"
            + json.dumps(
                GatewayAdmissionError("external_gateway_admission_failed").evidence
            )
        )
        return 1
    print(
        "External gateway inference preflight passed; private requests must retain ZDR policy."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
