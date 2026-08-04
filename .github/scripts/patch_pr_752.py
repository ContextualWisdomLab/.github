"""Apply the bounded NVIDIA NIM migration for the central PR autofix workflow."""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/pr-review-autofix.yml")
DOCTORING_PATH = Path("docs/doctoring/hourly-nvidia-nim-autofix.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact reviewed block and fail closed on source drift."""

    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact block, found {count}")
    return text.replace(old, new, 1)


def apply() -> None:
    """Migrate only model authentication/configuration and write its design record."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    old_provider = '''            "model": "github-models/openai/gpt-5",
            "small_model": "github-models/deepseek/deepseek-v3-0324",
            "enabled_providers": ["github-models"],
            "permission": {
              "edit": "allow",
              "bash": "deny",
              "read": "allow",
              "grep": "allow",
              "glob": "allow",
              "list": "allow",
              "task": "deny",
              "webfetch": "deny",
              "websearch": "deny",
              "lsp": "deny",
              "external_directory": "deny"
            },
            "agent": {
              "ci-autofix": {
                "description": "Conservative CI pull request review autofix agent",
                "mode": "primary",
                "prompt": "{file:./autofix-prompt.md}",
                "steps": 12,
                "permission": {
                  "edit": "allow",
                  "bash": "deny",
                  "read": "allow",
                  "grep": "allow",
                  "glob": "allow",
                  "list": "allow",
                  "task": "deny",
                  "webfetch": "deny",
                  "websearch": "deny",
                  "lsp": "deny",
                  "external_directory": "deny"
                }
              }
            },
            "provider": {
              "github-models": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "GitHub Models",
                "options": {
                  "baseURL": "https://models.github.ai/inference",
                  "apiKey": "{env:STRIX_GITHUB_MODELS_TOKEN}"
                },
                "models": {
                  "openai/gpt-5": {
                    "name": "OpenAI GPT-5",
                    "tool_call": true,
                    "reasoning": true,
                    "options": {
                      "reasoningEffort": "high"
                    },
                    "variants": {
                      "high": {
                        "reasoningEffort": "high"
                      }
                    },
                    "limit": {
                      "context": 200000,
                      "output": 100000
                    }
                  },
                  "deepseek/deepseek-v3-0324": {
                    "name": "DeepSeek V3 0324",
                    "tool_call": true,
                    "limit": {
                      "context": 128000,
                      "output": 4096
                    }
                  }
                }
              }
            }'''
    new_provider = '''            "model": "nvidia-nim/mistralai/mistral-nemotron",
            "small_model": "nvidia-nim/nvidia/nemotron-3-nano-30b-a3b",
            "enabled_providers": ["nvidia-nim"],
            "permission": {
              "edit": "allow",
              "bash": "deny",
              "read": "allow",
              "grep": "allow",
              "glob": "allow",
              "list": "allow",
              "task": "deny",
              "webfetch": "deny",
              "websearch": "deny",
              "lsp": "deny",
              "external_directory": "deny"
            },
            "agent": {
              "ci-autofix": {
                "description": "Conservative CI pull request review autofix agent",
                "mode": "primary",
                "prompt": "{file:./autofix-prompt.md}",
                "steps": 12,
                "permission": {
                  "edit": "allow",
                  "bash": "deny",
                  "read": "allow",
                  "grep": "allow",
                  "glob": "allow",
                  "list": "allow",
                  "task": "deny",
                  "webfetch": "deny",
                  "websearch": "deny",
                  "lsp": "deny",
                  "external_directory": "deny"
                }
              }
            },
            "provider": {
              "nvidia-nim": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "NVIDIA NIM",
                "options": {
                  "baseURL": "https://integrate.api.nvidia.com/v1",
                  "apiKey": "{env:NVIDIA_API_KEY}"
                },
                "models": {
                  "mistralai/mistral-nemotron": {
                    "name": "Mistral Nemotron",
                    "tool_call": true,
                    "limit": {
                      "context": 131072,
                      "output": 4096
                    }
                  },
                  "nvidia/nemotron-3-nano-30b-a3b": {
                    "name": "Nemotron 3 Nano 30B A3B",
                    "tool_call": true,
                    "limit": {
                      "context": 262144,
                      "output": 16384
                    }
                  }
                }
              }
            }'''
    workflow = replace_once(
        workflow, old_provider, new_provider, "OpenCode provider configuration"
    )

    old_ordinary_env = '''        env:
          STRIX_GITHUB_MODELS_TOKEN: ${{ secrets.STRIX_GITHUB_MODELS_TOKEN || github.token }}
          GITHUB_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || steps.target_app_token.outputs.token || github.token }}
          MODEL: github-models/openai/gpt-5
          USE_GITHUB_TOKEN: "true"
          SHARE: "false"'''
    new_ordinary_env = '''        env:
          NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || steps.target_app_token.outputs.token || github.token }}
          MODEL: nvidia-nim/mistralai/mistral-nemotron
          SHARE: "false"'''
    workflow = replace_once(
        workflow,
        old_ordinary_env,
        new_ordinary_env,
        "ordinary OpenCode execution environment",
    )

    old_conflict_env = '''        env:
          STRIX_GITHUB_MODELS_TOKEN: ${{ secrets.STRIX_GITHUB_MODELS_TOKEN || github.token }}
          GITHUB_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || steps.target_app_token.outputs.token || github.token }}
          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || steps.target_app_token.outputs.token || github.token }}
          MODEL: github-models/openai/gpt-5
          USE_GITHUB_TOKEN: "true"
          SHARE: "false"'''
    new_conflict_env = '''        env:
          NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || steps.target_app_token.outputs.token || github.token }}
          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || steps.target_app_token.outputs.token || github.token }}
          MODEL: nvidia-nim/mistralai/mistral-nemotron
          SHARE: "false"'''
    workflow = replace_once(
        workflow,
        old_conflict_env,
        new_conflict_env,
        "conflict-resolution OpenCode execution environment",
    )
    WORKFLOW_PATH.write_text(workflow, encoding="utf-8")

    doctoring = '''# Hourly NVIDIA NIM review-autofix boundary

## Decision

The central `PR Review Fix Scheduler` dispatches at minute 23 of every hour and retains its one-hour same-head retry boundary. The dispatched write-capable OpenCode autofix workflow uses only the NVIDIA NIM OpenAI-compatible provider. Its primary model is `mistralai/mistral-nemotron`; its small model is `nvidia/nemotron-3-nano-30b-a3b`.

This change is deliberately isolated from `opencode-review-dispatch.yml`. The existing read-only review agent keeps its own model pool, secret scoping, approval credentials, and repository policy. The autofix agent receives `secrets.NVIDIA_NIM_API_KEY` as `NVIDIA_API_KEY` only in the two steps that execute OpenCode: ordinary review repair and merge-conflict resolution. GitHub mutation credentials remain separate and continue to authorize only repository reads or writes.

## Product and MSA boundary

The scheduler, feedback collector, model execution, validation, and GitHub mutation stages remain independently replaceable central services. Target repositories consume the automation through repository-dispatch metadata and do not need to embed provider credentials or model configuration. The agent retains its conservative file allowlist, denied shell/tool permissions, exact-head checks, and fail-closed push guard.

## Verification contract

Static tests require the hourly cron inherited from the central baseline, the single `nvidia-nim` provider, the official NVIDIA API base URL, environment-only credential resolution, exact model IDs, and secret visibility limited to the two OpenCode execution steps. They reject GitHub Models provider configuration, GitHub Models model authentication, and `USE_GITHUB_TOKEN` fallback in the write-capable autofix workflow.

The selected primary model is documented by NVIDIA as suitable for agentic workflows, coding, instruction following, and function calling. The small model is documented as supporting coding, reasoning, instruction following, and tool calling. These catalog claims inform provider selection; they are not treated as evidence that any individual repair is correct. Repository tests, security checks, independent review, and branch protection remain authoritative.

## Standards alignment

The design supports NIST SSDF practices for protecting development environments and verifying software artifacts by narrowing credential exposure, separating model authentication from mutation authorization, and retaining independent verification before merge. It also follows the SLSA 1.2 source-track direction by preserving review and source-management controls. No formal NIST or SLSA conformance claim is made.

## References

Anomaly Co. (n.d.). *Providers*. OpenCode. Retrieved August 4, 2026, from https://opencode.ai/docs/providers/

Booth, H., Ogata, M., Kent, K., Souppaya, M., & Dodson, D. (2025). *Secure software development framework (SSDF) version 1.2: Recommendations for mitigating the risk of software vulnerabilities* (Initial Public Draft NIST SP 800-218 Rev. 1). National Institute of Standards and Technology. https://csrc.nist.gov/pubs/sp/800/218/r1/ipd

NVIDIA Corporation. (n.d.). *API reference for NVIDIA NIM for large language models*. Retrieved August 4, 2026, from https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html

NVIDIA Corporation. (2025). *Mistral-Nemotron* [Model card]. https://build.nvidia.com/mistralai/mistral-nemotron

NVIDIA Corporation. (2026). *Nemotron-3-Nano-30B-A3B* [Model catalog]. https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b

SLSA Community. (2025, November 24). *Announcing SLSA v1.2*. https://slsa.dev/blog/2025/11/announce-slsa-v1.2

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
'''
    DOCTORING_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DOCTORING_PATH.exists() and DOCTORING_PATH.read_text(encoding="utf-8") != doctoring:
        raise SystemExit(f"{DOCTORING_PATH}: existing content does not match")
    DOCTORING_PATH.write_text(doctoring, encoding="utf-8")


if __name__ == "__main__":
    apply()
