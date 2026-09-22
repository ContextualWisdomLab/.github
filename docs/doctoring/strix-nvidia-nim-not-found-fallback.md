# Strix NVIDIA NIM model-catalog fallback: evidence and design record

## Decision

Strix treats an authenticated NVIDIA NIM model-catalog `404 Not Found` as
provider availability evidence, not as a target-application vulnerability. The
gate does not retry the same unavailable model. It proceeds to a distinct
reviewed NVIDIA hosted model and only then to the existing GitHub Models
candidates.

Public-repository scans now default to
`nvidia/nemotron-3-super-120b-a12b`. The first fallback is
`nvidia/llama-3.3-nemotron-super-49b-v1.5`. Private repositories retain the
contracted provider because NVIDIA hosted trial inputs are restricted to public
repositories by the central workflow.

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

The outer workflow may classify exhausted provider infrastructure as neutral only
when the run log contains no vulnerability signal. Any reported severity or
non-zero vulnerability count remains blocking. Scanner reports and attempt logs
remain available as artifacts.

## Verification contract

Regression evidence proves that:

1. the exact LiteLLM `Nvidia_nimException` 404 observed in required CI is
   recognized;
2. an ordinary application 404 is not recognized;
3. provider context and 404 evidence on different lines are not recognized;
4. a provider-like source literal on one line without LiteLLM `NotFoundError`
   context is not recognized;
5. model-catalog 404s enter cross-model fallback but never same-model retry;
6. the primary and first fallback are current NVIDIA hosted models;
7. GitHub Models remain later cross-provider fallbacks;
8. vulnerability signals prevent neutral infrastructure classification; and
9. the required-workflow smoke contract pins these properties.

## Limitations

Hosted model catalogs may change independently of this repository. A model-card
page or supported self-hosted NIM container does not guarantee indefinite hosted
trial availability. The ordered model plan must therefore be reviewed against
current NVIDIA documentation whenever a provider returns a catalog 404. This
change does not treat arbitrary provider errors as success and does not weaken
Strix severity, changed-file attribution, or independent approval requirements.

## References

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC
9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110

NVIDIA Corporation. (2025). *Llama-3.3-Nemotron-Super-49B-v1.5* [Model card].
NVIDIA NIM. https://build.nvidia.com/nvidia/llama-3_3-nemotron-super-49b-v1_5/modelcard

NVIDIA Corporation. (2026a). *NVIDIA-Nemotron-3-Super-120B-A12B* [Model
card]. NVIDIA NIM.
https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard

NVIDIA Corporation. (2026b). *Configuration reference*. NVIDIA AI-Q Blueprint.
https://docs.nvidia.com/aiq-blueprint/2.2.0-rc1/customization/configuration-reference.html
