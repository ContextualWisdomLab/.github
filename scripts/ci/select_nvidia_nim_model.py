#!/usr/bin/env python3
"""Resolve the first live NVIDIA NIM model from an ordered candidate pool.

Why this exists
---------------
The scheduled autofix worker used to hard-code one NVIDIA NIM model id. NVIDIA
retires hosted models on published end-of-life dates, and the endpoint then
answers every request with HTTP 410 ``Gone``, e.g.

    The model 'mistralai/mistral-small-4-119b-2603' has reached its end of life
    on 2026-07-27T00:00:00Z and is no longer available.

A single hard-coded id therefore turns a normal provider lifecycle event into a
total outage of the repair loop. This helper asks the provider which models are
actually served right now (``GET /v1/models``, the OpenAI-compatible catalog
route NVIDIA NIM implements) and returns the first entry of an ordered,
operator-controlled preference list that the provider still serves.

The helper is deliberately fail-closed: an unreachable catalog, an unparsable
catalog, or a pool with no served candidate is an error, never a silent
fallback to an arbitrary model.

References:
    NVIDIA. (2025). *NVIDIA NIM for large language models: OpenAI-compatible
    API reference*. https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html
    OpenAI. (2025). *API reference: List models*.
    https://platform.openai.com/docs/api-reference/models/list
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import sys
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
ALLOWED_CATALOG_HOSTS = frozenset({"integrate.api.nvidia.com"})
DEFAULT_TIMEOUT_SECONDS = 30.0
EX_TEMPFAIL = 75


class ModelResolutionUnavailable(RuntimeError):
    """The reviewed model pool cannot be resolved due to provider availability."""


def parse_candidates(raw_candidates: str) -> list[str]:
    """Split a whitespace-separated candidate pool into ordered model ids.

    Duplicate ids are removed while the operator's preference order is kept, so
    a pool may be assembled from several sources without changing behavior.
    """
    ordered: list[str] = []
    for candidate in raw_candidates.split():
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


def validate_catalog_base_url(base_url: str) -> str:
    """Return the catalog base URL after refusing untrusted endpoints.

    Only HTTPS URLs on the known NVIDIA NIM integration host are accepted, so a
    tampered variable cannot redirect the API key to another host.
    """
    parts = urlsplit(base_url)
    if parts.scheme != "https":
        raise ValueError(f"NVIDIA NIM base URL must use https; got {parts.scheme or '<none>'}")
    if parts.hostname not in ALLOWED_CATALOG_HOSTS:
        raise ValueError(f"NVIDIA NIM base URL host is not allowed: {parts.hostname or '<none>'}")
    if parts.port not in (None, 443):
        raise ValueError(f"NVIDIA NIM base URL must use the default HTTPS port; got {parts.port}")
    if parts.username or parts.password:
        raise ValueError("NVIDIA NIM base URL must not embed credentials")
    if parts.query or parts.fragment:
        raise ValueError("NVIDIA NIM base URL must not include a query or fragment")
    return base_url.rstrip("/")


def fetch_served_model_ids(
    base_url: str,
    api_key: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> set[str]:
    """Return the model ids the provider currently serves.

    Any transport or payload problem raises, because guessing a model id would
    hide a provider outage behind a confusing downstream model error.
    """
    normalized_base_url = validate_catalog_base_url(base_url)
    parts = urlsplit(normalized_base_url)
    request_path = f"{parts.path.rstrip('/')}/models"
    try:
        connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
            parts.hostname,
            parts.port or 443,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        )
        try:
            connection.request(
                "GET",
                request_path,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            if response.status >= 400:
                error = RuntimeError(
                    f"NVIDIA NIM model catalog request failed with HTTP {response.status}"
                )
                if response.status == 429 or response.status >= 500:
                    raise ModelResolutionUnavailable(str(error))
                raise error
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
    except RuntimeError:
        raise
    except (OSError, http.client.HTTPException) as error:
        raise ModelResolutionUnavailable("NVIDIA NIM model catalog is unreachable") from error
    except UnicodeDecodeError as error:
        raise ModelResolutionUnavailable(
            "NVIDIA NIM model catalog returned a non-UTF-8 body"
        ) from error
    except json.JSONDecodeError as error:
        raise ModelResolutionUnavailable("NVIDIA NIM model catalog returned a non-JSON body") from error
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ModelResolutionUnavailable("NVIDIA NIM model catalog payload has no model list")
    served = {
        str(entry["id"])
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]
    }
    if not served:
        raise ModelResolutionUnavailable("NVIDIA NIM model catalog listed no usable model id")
    return served


def select_model(candidates: list[str], served_model_ids: set[str], *, role: str) -> str:
    """Return the first candidate the provider still serves for this role."""
    if not candidates:
        raise ValueError(f"no {role} NVIDIA NIM model candidates were configured")
    for candidate in candidates:
        if candidate in served_model_ids:
            return candidate
    raise ModelResolutionUnavailable(
        f"no configured {role} NVIDIA NIM model candidate is currently served: {' '.join(candidates)}. "
        "Add a live model id to the candidate pool variable so the repair worker can run."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line for the model resolver."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, help="whitespace-separated ordered model ids")
    parser.add_argument(
        "--exclude",
        default="",
        help="whitespace-separated model ids that cannot be selected",
    )
    parser.add_argument("--role", default="primary", help="candidate pool role used in error messages")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="NVIDIA NIM OpenAI-compatible base URL")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="model catalog request timeout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Print the resolved model id, or report an actionable failure."""
    args = parse_args(argv)
    api_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVIDIA_NIM_API_KEY") or ""
    if not api_key:
        print(
            "::error::NVIDIA_API_KEY is required to resolve a live NVIDIA NIM model.",
            file=sys.stderr,
        )
        return 1
    try:
        served = fetch_served_model_ids(args.base_url, api_key, timeout_seconds=args.timeout_seconds)
        excluded = set(parse_candidates(args.exclude))
        candidates = [candidate for candidate in parse_candidates(args.candidates) if candidate not in excluded]
        print(select_model(candidates, served, role=args.role))
    except ValueError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    except ModelResolutionUnavailable as error:
        print(f"::error::{error}", file=sys.stderr)
        return EX_TEMPFAIL
    except RuntimeError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
