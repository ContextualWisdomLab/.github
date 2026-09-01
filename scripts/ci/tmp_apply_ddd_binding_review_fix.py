#!/usr/bin/env python3
"""Apply RED then GREEN review remediation for the hourly DDD entrypoint contract."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one exact fragment or fail closed on branch drift."""
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one fragment, found {count}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


def apply_red() -> None:
    """Add a regression that the raw-prose implementation must fail."""
    replace_once(
        "tests/test_organization_commercial_readiness_loop_policy.py",
        """    for changed in mutations:
        assert not is_manual_product_entrypoint(workflow(content=changed))


def test_repository_eligibility_is_owned_and_write_capable() -> None:
""",
        """    for changed in mutations:
        assert not is_manual_product_entrypoint(workflow(content=changed))


def test_ddd_contract_rejects_unbound_unused_yaml_prose() -> None:
    \"\"\"DDD words in an unused scalar are not an agent instruction contract.\"\"\"
    safe = manual_workflow()
    assert safe.content is not None
    unused = safe.content.replace("prompt: |\\n", "notes: |\\n", 1)
    assert not is_manual_product_entrypoint(workflow(content=unused))


def test_repository_eligibility_is_owned_and_write_capable() -> None:
""",
    )


def apply_green() -> None:
    """Install the scoped capability and invocation-binding contract."""
    replace_once(
        "scripts/ci/organization_commercial_readiness_loop.py",
        """import re
import subprocess
import sys
from pathlib import Path
""",
        """import re
import subprocess
import sys
import textwrap
from pathlib import Path
""",
    )
    replace_once(
        "scripts/ci/organization_commercial_readiness_loop.py",
        """ENTRYPOINT_MARKER = "# cwl-org-commercial-entrypoint: v1"
DDD_ENTRYPOINT_MARKER = "# cwl-ddd-architecture-audit: required"
DDD_CONTRACT_TERMS = (
    "Domain-Driven Design",
    "core, supporting, and generic subdomains",
    "Bounded Context",
    "Context Map",
    "Ubiquitous Language",
    "Aggregate",
    "Entity",
    "Value Object",
    "Domain Service",
    "Repository",
    "Domain Event",
    "Invariant",
    "Anti-Corruption Layer",
    "Shared Kernel",
    "directory paths",
    "docs/product-technical-gap-baseline.md",
)
CENTRAL_REPOSITORY = f"{DEFAULT_ORGANIZATION}/.github"
""",
        """ENTRYPOINT_MARKER = "# cwl-org-commercial-entrypoint: v1"
DDD_ENTRYPOINT_MARKER = "# cwl-ddd-architecture-audit: v1"
DDD_PROMPT_BINDING_MARKER = "# cwl-ddd-prompt-binding: v1"
DDD_PROMPT_ENVIRONMENT = "CWL_PRODUCT_AGENT_PROMPT"
DDD_CAPABILITY_ENVIRONMENT = "CWL_DDD_CONTRACT_CAPABILITIES"
DDD_PROMPT_BINDING = f"--prompt-env {DDD_PROMPT_ENVIRONMENT}"
DDD_CAPABILITY_BINDING = (
    f"--architecture-contract-env {DDD_CAPABILITY_ENVIRONMENT}"
)
DDD_CONTRACT_CAPABILITIES = frozenset(
    {
        "aggregate",
        "anti_corruption_layer",
        "bounded_context",
        "context_map",
        "directory_ownership",
        "domain_event",
        "domain_service",
        "entity",
        "invariant",
        "minimal_shared_kernel",
        "product_gap_baseline",
        "repository",
        "subdomain_classification",
        "ubiquitous_language",
        "value_object",
    }
)
DDD_CAPABILITY_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]*")
CENTRAL_REPOSITORY = f"{DEFAULT_ORGANIZATION}/.github"
""",
    )
    replace_once(
        "scripts/ci/organization_commercial_readiness_loop.py",
        """def has_domain_driven_development_contract(source: str) -> bool:
    \"\"\"Return whether one entrypoint accepts the complete DDD repair contract.\"\"\"
    return DDD_ENTRYPOINT_MARKER in source and all(
        term in source for term in DDD_CONTRACT_TERMS
    )


def is_manual_product_entrypoint(workflow: WorkflowRecord) -> bool:
""",
        """def _root_mapping_regions(source: str, key: str) -> tuple[str, ...]:
    \"\"\"Return top-level YAML mapping bodies for one exact key.\"\"\"
    lines = source.splitlines()
    regions: list[str] = []
    for index, line in enumerate(lines):
        if line != f"{key}:":
            continue
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.strip() and not candidate.startswith(" "):
                break
            body.append(candidate)
        regions.append("\\n".join(body))
    return tuple(regions)


def _yaml_block_scalars(source: str, key: str) -> tuple[str, ...]:
    \"\"\"Return dedented YAML literal or folded block scalars for one key.\"\"\"
    header = re.compile(
        rf"^(?P<indent> *){re.escape(key)}: *[>|][+-]? *$"
    )
    lines = source.splitlines()
    blocks: list[str] = []
    for index, line in enumerate(lines):
        match = header.fullmatch(line)
        if match is None:
            continue
        base_indent = len(match.group("indent"))
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.strip():
                candidate_indent = len(candidate) - len(candidate.lstrip(" "))
                if candidate_indent <= base_indent:
                    break
            body.append(candidate)
        blocks.append(textwrap.dedent("\\n".join(body)).strip("\\n"))
    return tuple(blocks)


def _shell_commands(block: str) -> tuple[str, ...]:
    \"\"\"Return non-comment shell commands with continuations joined.\"\"\"
    commands: list[str] = []
    fragments: list[str] = []
    for line in block.splitlines():
        fragment = line.strip()
        if not fragment or fragment.startswith("#"):
            continue
        continued = fragment.endswith("\\")
        fragments.append(fragment.removesuffix("\\").rstrip())
        if continued:
            continue
        commands.append(" ".join(fragments))
        fragments = []
    if fragments:
        commands.append(" ".join(fragments))
    return tuple(commands)


def _has_bound_ddd_agent_invocation(source: str) -> bool:
    \"\"\"Return whether one executable command receives both contract inputs.\"\"\"
    for run_block in _yaml_block_scalars(source, "run"):
        if DDD_PROMPT_BINDING_MARKER not in run_block:
            continue
        for command in _shell_commands(run_block):
            if DDD_PROMPT_BINDING in command and DDD_CAPABILITY_BINDING in command:
                return True
    return False


def has_domain_driven_development_contract(source: str) -> bool:
    \"\"\"Return whether one entrypoint binds a scoped versioned DDD contract.\"\"\"
    if DDD_ENTRYPOINT_MARKER not in source:
        return False
    root_environments = _root_mapping_regions(source, "env")
    if len(root_environments) != 1:
        return False
    environment = root_environments[0]
    capability_blocks = _yaml_block_scalars(
        environment, DDD_CAPABILITY_ENVIRONMENT
    )
    prompt_blocks = _yaml_block_scalars(environment, DDD_PROMPT_ENVIRONMENT)
    if len(capability_blocks) != 1 or len(prompt_blocks) != 1:
        return False
    if not prompt_blocks[0].strip():
        return False
    declared_capabilities = frozenset(
        DDD_CAPABILITY_TOKEN_RE.findall(capability_blocks[0])
    )
    if not DDD_CONTRACT_CAPABILITIES.issubset(declared_capabilities):
        return False
    return _has_bound_ddd_agent_invocation(source)


def is_manual_product_entrypoint(workflow: WorkflowRecord) -> bool:
""",
    )
    replace_once(
        "organization_commercial_readiness_fixtures.py",
        """        content=(
            "# cwl-org-commercial-entrypoint: v1\\n"
            "# cwl-ddd-architecture-audit: required\\n"
            "on:\\n  workflow_dispatch:\\n"
            "concurrency:\\n  group: product-development\\n"
            "permissions:\\n  contents: write\\n"
            "NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}\\n"
            "prompt: |\\n"
            "  Apply Domain-Driven Design before and during every increment.\\n"
            "  Classify core, supporting, and generic subdomains; define each Bounded Context, Context Map, and Ubiquitous Language.\\n"
            "  Keep Aggregate, Entity, Value Object, Domain Service, Repository, Domain Event, and Invariant names aligned across code, API, database, and tests.\\n"
            "  Isolate external systems behind an Anti-Corruption Layer and keep the Shared Kernel minimal.\\n"
            "  Audit and correct misleading directory paths with imports, packaging, callers, tests, and architecture documents in the same bounded change.\\n"
            "  Update docs/product-technical-gap-baseline.md with detected and repaired architecture drift.\\n"
        ),
""",
        """        content=(
            "# cwl-org-commercial-entrypoint: v1\\n"
            "# cwl-ddd-architecture-audit: v1\\n"
            "on:\\n  workflow_dispatch:\\n"
            "concurrency:\\n  group: product-development\\n"
            "permissions:\\n  contents: write\\n"
            "env:\\n"
            "  NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}\\n"
            "  CWL_DDD_CONTRACT_CAPABILITIES: >-\\n"
            "    aggregate anti_corruption_layer bounded_context context_map\\n"
            "    directory_ownership domain_event domain_service entity invariant\\n"
            "    minimal_shared_kernel product_gap_baseline repository\\n"
            "    subdomain_classification ubiquitous_language value_object\\n"
            "  CWL_PRODUCT_AGENT_PROMPT: |\\n"
            "    Deliver one buyer-visible increment through the repository-owned product agent.\\n"
            "\\n"
            "    Keep implementation, tests, documentation, and package boundaries coherent.\\n"
            "jobs:\\n"
            "  develop:\\n"
            "    runs-on: ubuntu-24.04\\n"
            "    steps:\\n"
            "      - name: Invoke the product agent\\n"
            "        run: |\\n"
            "          # cwl-ddd-prompt-binding: v1\\n"
            "          python scripts/automation/commercial_product_development.py \\\\\\n"
            "            --prompt-env CWL_PRODUCT_AGENT_PROMPT \\\\\\n"
            "            --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\\n"
        ),
""",
    )
    replace_once(
        "tests/test_organization_commercial_readiness_loop_policy.py",
        """    ActionKind,
    ActionResult,
    DDD_CONTRACT_TERMS,
    RunRecord,
""",
        """    ActionKind,
    ActionResult,
    DDD_CONTRACT_CAPABILITIES,
    RunRecord,
""",
    )
    replace_once(
        "tests/test_organization_commercial_readiness_loop_policy.py",
        """    is_dedicated_writer_workflow,
    is_live_writer_run,
    is_manual_product_entrypoint,
""",
        """    has_domain_driven_development_contract,
    is_dedicated_writer_workflow,
    is_live_writer_run,
    is_manual_product_entrypoint,
""",
    )
    replace_once(
        "tests/test_organization_commercial_readiness_loop_policy.py",
        """def test_product_entrypoint_requires_manual_nvidia_and_ddd_opt_in() -> None:
    \"\"\"Product dispatch requires a manual credential-isolated DDD contract.\"\"\"
    safe = manual_workflow()
    assert is_manual_product_entrypoint(safe)
    assert not is_manual_product_entrypoint(workflow(state="disabled_manually", content="x"))
    assert not is_manual_product_entrypoint(workflow(content=None))
    mutations = [
        (safe.content or "") + 'schedule:\\n  - cron: "1 * * * *"\\n',
        (safe.content or "") + "COPILOT_GITHUB_TOKEN: forbidden\\n",
        (safe.content or "").replace("# cwl-org-commercial-entrypoint: v1\\n", ""),
        (safe.content or "").replace(
            "# cwl-ddd-architecture-audit: required\\n", ""
        ),
        (safe.content or "").replace("concurrency:\\n", ""),
    ]
    mutations.extend(
        (safe.content or "").replace(term, f"missing-{index}", 1)
        for index, term in enumerate(DDD_CONTRACT_TERMS)
    )
    for changed in mutations:
        assert not is_manual_product_entrypoint(workflow(content=changed))


def test_ddd_contract_rejects_unbound_unused_yaml_prose() -> None:
    \"\"\"DDD words in an unused scalar are not an agent instruction contract.\"\"\"
    safe = manual_workflow()
    assert safe.content is not None
    unused = safe.content.replace("prompt: |\\n", "notes: |\\n", 1)
    assert not is_manual_product_entrypoint(workflow(content=unused))
""",
        """def test_product_entrypoint_requires_manual_nvidia_and_bound_ddd_opt_in() -> None:
    \"\"\"Product dispatch requires a scoped capability set bound to one command.\"\"\"
    safe = manual_workflow()
    assert safe.content is not None
    source = safe.content
    assert "Domain-Driven Design" not in source
    assert is_manual_product_entrypoint(safe)
    assert has_domain_driven_development_contract(source)

    ordinary_rejections = [
        source + 'schedule:\\n  - cron: "1 * * * *"\\n',
        source + "COPILOT_GITHUB_TOKEN: forbidden\\n",
        source.replace("# cwl-org-commercial-entrypoint: v1\\n", "", 1),
        source.replace("# cwl-ddd-architecture-audit: v1\\n", "", 1),
        source.replace("concurrency:\\n", "", 1),
    ]
    for changed in ordinary_rejections:
        assert not is_manual_product_entrypoint(workflow(content=changed))

    for index, capability in enumerate(sorted(DDD_CONTRACT_CAPABILITIES)):
        changed = source.replace(capability, f"omitted_{index}", 1)
        assert not has_domain_driven_development_contract(changed)


def test_ddd_contract_rejects_comments_unused_scopes_and_split_bindings() -> None:
    \"\"\"Comments, unscoped values, and separate commands cannot fake a binding.\"\"\"
    safe = manual_workflow()
    assert safe.content is not None
    source = safe.content
    comment_only = (
        "# cwl-ddd-architecture-audit: v1\\n"
        + "\\n".join(f"# {item}" for item in sorted(DDD_CONTRACT_CAPABILITIES))
        + "\\n# cwl-ddd-prompt-binding: v1\\n"
        + "# --prompt-env CWL_PRODUCT_AGENT_PROMPT\\n"
        + "# --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\\n"
    )
    assert not has_domain_driven_development_contract(comment_only)

    invalid_sources = [
        source.replace("env:\\n", "metadata:\\n", 1),
        source.replace("CWL_PRODUCT_AGENT_PROMPT: |", "UNUSED_PROMPT: |", 1),
        source.replace(
            "CWL_DDD_CONTRACT_CAPABILITIES: >-", "UNUSED_CAPABILITIES: >-", 1
        ),
        source.replace(
            "    Deliver one buyer-visible increment through the repository-owned product agent.\\n",
            "",
            1,
        ),
        source.replace("# cwl-ddd-prompt-binding: v1", "# unbound", 1),
        source.replace(
            "--prompt-env CWL_PRODUCT_AGENT_PROMPT", "--prompt-env UNUSED_PROMPT", 1
        ),
        source.replace(
            "--architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES",
            "--architecture-contract-env UNUSED_CAPABILITIES",
            1,
        ),
        source + "env:\\n  OTHER_VALUE: present\\n",
        source.replace(
            "  CWL_PRODUCT_AGENT_PROMPT: |",
            "  CWL_PRODUCT_AGENT_PROMPT: |\\n"
            "    duplicate\\n"
            "  CWL_PRODUCT_AGENT_PROMPT: |",
            1,
        ),
        source.replace(
            "  CWL_DDD_CONTRACT_CAPABILITIES: >-",
            "  CWL_DDD_CONTRACT_CAPABILITIES: >-\\n"
            "    bounded_context\\n"
            "  CWL_DDD_CONTRACT_CAPABILITIES: >-",
            1,
        ),
    ]
    for changed in invalid_sources:
        assert not has_domain_driven_development_contract(changed)

    bound_run = (
        "        run: |\\n"
        "          # cwl-ddd-prompt-binding: v1\\n"
        "          python scripts/automation/commercial_product_development.py \\\\n"
        "            --prompt-env CWL_PRODUCT_AGENT_PROMPT \\\\n"
        "            --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\\n"
    )
    split_run = (
        "        run: |\\n"
        "          # cwl-ddd-prompt-binding: v1\\n"
        "          product-agent --prompt-env CWL_PRODUCT_AGENT_PROMPT\\n"
        "          product-agent --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\\n"
    )
    assert not has_domain_driven_development_contract(
        source.replace(bound_run, split_run, 1)
    )

    dangling_run = (
        "        run: |\\n"
        "          # cwl-ddd-prompt-binding: v1\\n"
        "          product-agent \\\\n"
    )
    assert not has_domain_driven_development_contract(
        source.replace(bound_run, dangling_run, 1)
    )
""",
    )
    replace_once(
        "tests/test_organization_commercial_readiness_loop_policy.py",
        """    assert "# cwl-ddd-architecture-audit: required" in doctoring
""",
        """    assert "# cwl-ddd-architecture-audit: v1" in doctoring
    assert "--architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES" in doctoring
""",
    )

    doctoring_path = ROOT / "docs/doctoring/organization-commercial-readiness-loop.md"
    doctoring = doctoring_path.read_text(encoding="utf-8")
    start = doctoring.index("## Product-development boundary")
    end = doctoring.index("## Failure, evidence, and operations")
    product_section = """## Product-development boundary

Product development is dispatched only when a repository has zero open pull requests and exposes one active, manual-only, explicitly marked workflow. The DDD enrollment is versioned and its values must live in the root workflow `env` mapping so every job receives the same contract:

```yaml
# cwl-org-commercial-entrypoint: v1
# cwl-ddd-architecture-audit: v1
on:
  workflow_dispatch:

env:
  CWL_DDD_CONTRACT_CAPABILITIES: >-
    aggregate anti_corruption_layer bounded_context context_map
    directory_ownership domain_event domain_service entity invariant
    minimal_shared_kernel product_gap_baseline repository
    subdomain_classification ubiquitous_language value_object
  CWL_PRODUCT_AGENT_PROMPT: |
    Deliver one buyer-visible increment through the repository-owned product agent.

jobs:
  develop:
    steps:
      - run: |
          # cwl-ddd-prompt-binding: v1
          product-agent \
            --prompt-env CWL_PRODUCT_AGENT_PROMPT \
            --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES
```

The entrypoint must also contain an explicit `concurrency` contract, use `NVIDIA_NIM_API_KEY`, omit `COPILOT_GITHUB_TOKEN`, have no schedule of its own, and carry a commercial/product-development identity. Human-readable prompt wording is repository-owned and may use any language. Eligibility depends on stable capability identifiers rather than copied English prose. The prompt and capability environment names must be passed to the same non-comment shell command under the binding marker; comments, unrelated YAML, unscoped step values, separate commands, or unused block scalars do not satisfy the contract.

The capability contract covers strategic and tactical Domain-Driven Design: subdomain classification, Bounded Context, Context Map, Ubiquitous Language, Aggregate, Entity, Value Object, Domain Service, Repository, Domain Event, Invariant, Anti-Corruption Layer, minimal Shared Kernel, directory ownership, and product-gap baseline traceability.

Each hourly product increment must identify the owning product responsibility before selecting a repository, then compare the live directory tree, module/package names, API, database objects, tests, and documentation with that responsibility. Misleading directory paths, generic `utils`/`common` dumping grounds that own domain behavior, infrastructure imports inside the domain model, cross-context database access, obsolete product names, or customer-visible implementation boundaries are architecture defects, not cosmetic debt. When one can be corrected safely in the bounded increment, the agent moves the code and updates imports, package manifests, call sites, migrations, tests, ADRs, diagrams, and compatibility adapters in the same pull request.

The contract does not impose one universal folder template. A move is justified by domain ownership and dependency direction, not by directory aesthetics. Aggregate boundaries remain the smallest consistency boundary; external and legacy systems are isolated behind an Anti-Corruption Layer; the Shared Kernel remains minimal; and cross-context integration uses explicit versioned contracts. If a coherent move exceeds the current pull request's safe scope, the agent must record the exact owner, callers, target context, migration sequence, and acceptance evidence in `docs/product-technical-gap-baseline.md` and select it as the next bounded architecture increment rather than silently leaving the drift unresolved.

This opt-in prevents the central coordinator from guessing that an unrelated manual workflow can safely modify product source. Repositories with an existing hourly or more frequent dedicated writer keep their own lease and are never double-dispatched; those schedules may share the same DDD contract and should adopt it without adding another cron.

The repository-local entrypoint remains responsible for implementing the two environment-name flags in its product-agent adapter, bounded editable paths, tests, 100% production statement and branch coverage, public docstrings, package and security verification, exact-head publication, and pull-request creation. A missing compliant entrypoint is a deliberate no-op, not permission to inject a generic writer into that repository.

"""
    doctoring_path.write_text(
        doctoring[:start] + product_section + doctoring[end:], encoding="utf-8"
    )

    replace_once(
        "docs/product-technical-gap-baseline.md",
        """- **조치:** 수동 제품개발 진입점에 `# cwl-ddd-architecture-audit: required`와 전략·전술 DDD 용어, directory-path repair, `docs/product-technical-gap-baseline.md` 갱신을 요구한다. 기존 전용 예약은 writer lease를 유지해 중복 실행하지 않는다.
""",
        """- **조치:** 수동 제품개발 진입점에 `# cwl-ddd-architecture-audit: v1`, root `env`의 versioned capability ID 집합, 자유 형식 agent prompt, 동일 실행 명령의 `--prompt-env CWL_PRODUCT_AGENT_PROMPT`·`--architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES` binding을 요구한다. 주석·무관 YAML·분리 명령은 계약으로 인정하지 않으며, 기존 전용 예약은 writer lease를 유지해 중복 실행하지 않는다.
""",
    )
    replace_once(
        "docs/product-technical-gap-baseline.md",
        """- **완료 증거:** exact-head focused policy tests, statement/branch coverage 100%, Python docstring 100%, workflow security checks, independent review, protected merge. 병합 전 상태는 구현 중이며 운영 완료로 간주하지 않는다.
""",
        """- **리뷰 보강:** raw YAML 전체의 단어 존재 검사를 제거하고 root environment scope와 실제 product-agent command binding을 검증한다. 설명문은 특정 영어 문구에 종속되지 않는다.
- **완료 증거:** exact-head focused policy tests, statement/branch coverage 100%, Python docstring 100%, workflow security checks, independent review, protected merge. 병합 전 상태는 구현 중이며 운영 완료로 간주하지 않는다.
""",
    )
    replace_once(
        "CHANGELOG.md",
        """- Restore the hourly organization commercial-readiness coordinator when the dedicated maintainer secret is absent by exchanging the protected scheduled job's OIDC identity for a short-lived OpenCode App installation token; retain bounded network calls, token masking, and fail-closed parsing. Require every centrally dispatched product-development entrypoint to accept a machine-checked Domain-Driven Design contract, continuously repairing misleading directory ownership and recording larger bounded-context migrations in `docs/product-technical-gap-baseline.md` without duplicating repository-owned schedules.
""",
        """- Restore the hourly organization commercial-readiness coordinator when the dedicated maintainer secret is absent by exchanging the protected scheduled job's OIDC identity for a short-lived OpenCode App installation token; retain bounded network calls, token masking, and fail-closed parsing. Require every centrally dispatched product-development entrypoint to bind a versioned machine-readable Domain-Driven Design capability set and repository-owned prompt to the same product-agent command, rejecting comments or unused YAML while continuously repairing misleading directory ownership and recording larger bounded-context migrations in `docs/product-technical-gap-baseline.md` without duplicating repository-owned schedules.
""",
    )


def main() -> None:
    """Run the selected TDD phase."""
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("red", "green"))
    args = parser.parse_args()
    if args.phase == "red":
        apply_red()
    else:
        apply_green()


if __name__ == "__main__":
    main()
