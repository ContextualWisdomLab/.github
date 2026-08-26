# Strix NVIDIA NIM model-catalog fallback: evidence and design record

## Decision

Strix treats an authenticated NVIDIA NIM model-catalog `404 Not Found` as
provider availability evidence, not as a target-application vulnerability. The
gate does not retry the same unavailable model. It proceeds to a distinct
reviewed NVIDIA hosted model and only then to the direct OpenAI fallback.

For public-repository scans, the trusted workflow queries NVIDIA's authenticated
`/v1/models` catalog and selects the first served entry from reviewed primary
and fallback pools. The default pool prefers
`nvidia/nemotron-3-super-120b-a12b`; the distinct fallback is
`nvidia/llama-3.1-nemotron-ultra-253b-v1`. The retired
`nvidia/llama-3.3-nemotron-super-49b-v1.5` is no longer executable workflow
configuration. Private repositories retain the contracted provider because
NVIDIA hosted trial inputs are restricted to public repositories.

OpenRouter remains a supported transport and API-base capability. It is not a
static fallback-model registry: executable fallback expressions must not add a
hard-coded OpenRouter model identifier. OpenRouter model selection belongs to
the authenticated live-catalog resolver at the provider owner boundary. This
keeps transport recovery separate from model discovery and prevents central
workflow configuration from duplicating a provider catalog that can change.

## Trust boundary

The NVIDIA classifier accepts only a single bounded log line that contains all
three signals: a LiteLLM `NotFoundError`, NVIDIA NIM provider context, and
model-catalog not-found evidence. It does not assemble provider and `404`
signals from different lines. A bare application `404`, route miss, database
lookup miss, provider-like source literal, or other target-controlled output is
not enough to enter model fallback.

This same-line rule matters because scanner stdout can include text derived from
the repository under review. Requiring the trusted LiteLLM exception marker and
all provider-availability evidence on one line prevents repository content from
combining with an unrelated application `404` to spoof infrastructure fallback.
Provider-side failure also remains a fail-closed incomplete scan until a distinct
fallback produces complete evidence.

Exhausted provider infrastructure remains fail-closed even when the trusted
gate has classified every observed threshold finding as outside the pull
request's changed files. That classification scopes authoritative findings; it
cannot prove that an incomplete provider-exhausted scan observed every finding.
Changed, unmapped, and changed-manifest findings also remain blocking. Scanner
reports and attempt logs remain available as artifacts.

## Verification contract

Regression evidence proves that:

1. the exact LiteLLM `Nvidia_nimException` 404 observed in required CI is
   recognized;
2. an ordinary application 404 is not recognized;
3. provider context and 404 evidence on different lines are not recognized;
4. a provider-like source literal on one line without LiteLLM `NotFoundError`
   context is not recognized;
5. model-catalog 404s enter cross-model fallback but never same-model retry;
6. the primary and first fallback are present in the live NVIDIA catalog;
7. OpenRouter's authenticated dynamic free router and direct OpenAI remain the
   later cross-provider fallbacks;
8. provider exhaustion remains non-passing after unchanged baseline findings;
9. changed, unmapped, and changed-manifest findings also block after provider
   exhaustion; and
10. executable fallback expressions use OpenRouter's dynamic router rather than
    hard-coding one of its underlying provider model ids; and
11. the required-workflow smoke contract pins these properties.

## Limitations

Hosted model catalogs and capacity may change independently of this repository.
Catalog membership prevents deterministic retired-model selection but does not
prove capacity, so HTTP 429 exhaustion remains fail-closed if every fallback is
unavailable. This change does not treat provider errors as success and does not
weaken Strix severity, changed-file attribution, or approval requirements.

Operationally, at least one configured provider must have usable request
capacity or credit before a required scan can produce authoritative evidence.
The live catalog resolver verifies model availability, not quota, rate-limit
headroom, or account balance. Restoring those provider resources is a runtime
prerequisite; adding another fixed model identifier is not a substitute.

## Current fallback contract (2026-08-25)

The direct-OpenAI fallback is `gpt-5.4`. The retired `gpt-5.6-luna` identifier
must not appear in the executable workflow, required smoke contract, or model
pool. A central workflow update without its smoke and model-pool assertions is
invalid because every consumer repository would fail before its own scan. The
contract is verified by `scripts/ci/strix_required_workflow_smoke.sh` and the
focused `test_strix_quick_gate.sh` case; provider failures remain non-passing.

## References

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC
9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110

NVIDIA Corporation. (2026a). *Models*. NVIDIA NIM.
https://build.nvidia.com/models

NVIDIA Corporation. (2026b). *NVIDIA-Nemotron-3-Super-120B-A12B* [Model
card]. NVIDIA NIM.
https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard

NVIDIA Corporation. (2026c). *Configuration reference*. NVIDIA AI-Q Blueprint.
https://docs.nvidia.com/aiq-blueprint/2.2.0-rc1/customization/configuration-reference.html
