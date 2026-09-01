"""Regression tests for executable DDD product-entrypoint binding."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from organization_commercial_readiness_fixtures import manual_workflow, workflow
from scripts.ci import organization_commercial_readiness_ddd_contract as contract
from scripts.ci import organization_commercial_readiness_loop as coordinator


def _source() -> str:
    """Return the canonical machine-bound multilingual workflow fixture."""
    source = manual_workflow().content
    assert source is not None
    return source


def _replace_command(source: str, replacement: str) -> str:
    """Replace the canonical multiline product-agent command once."""
    original = (
        "python scripts/automation/commercial_product_development.py \\\n"
        "            --prompt-env CWL_PRODUCT_AGENT_PROMPT \\\n"
        "            --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES"
    )
    assert original in source
    return source.replace(original, replacement, 1)


def test_accepts_multilingual_prompt_option_forms_and_environment_prefix() -> None:
    """Eligibility depends on bound capabilities, not copied English prose."""
    source = _source()
    assert "Domain-Driven Design" not in source
    assert coordinator.has_domain_driven_development_contract(source)
    assert coordinator.is_manual_product_entrypoint(manual_workflow())

    equals_options = source.replace(
        "--prompt-env CWL_PRODUCT_AGENT_PROMPT",
        "--prompt-env=CWL_PRODUCT_AGENT_PROMPT",
    ).replace(
        "--architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES",
        "--architecture-contract-env=CWL_DDD_CONTRACT_CAPABILITIES",
    )
    assert coordinator.has_domain_driven_development_contract(equals_options)

    prefixed = source.replace(
        "python scripts/automation/commercial_product_development.py",
        "env MODE=bounded python scripts/automation/commercial_product_development.py",
        1,
    )
    assert coordinator.has_domain_driven_development_contract(prefixed)

    single_quoted = source.replace(
        'CWL_DDD_CONTRACT_VERSION: "1"', "CWL_DDD_CONTRACT_VERSION: '1'"
    )
    plain = source.replace(
        'CWL_DDD_CONTRACT_VERSION: "1"', "CWL_DDD_CONTRACT_VERSION: 1"
    )
    assert coordinator.has_domain_driven_development_contract(single_quoted)
    assert coordinator.has_domain_driven_development_contract(plain)


def test_rejects_missing_extra_or_version_drift() -> None:
    """Version one accepts exactly the approved strategic and tactical set."""
    source = _source()
    for index, capability in enumerate(sorted(contract.DDD_CONTRACT_CAPABILITIES)):
        assert not coordinator.has_domain_driven_development_contract(
            source.replace(capability, f"omitted_{index}", 1)
        )
    assert not coordinator.has_domain_driven_development_contract(
        source.replace(
            " value_object\n", " value_object unexpected_capability\n", 1
        )
    )
    for replacement in ('2', '"2"', "'2'", "invalid", '"1\''):
        assert not coordinator.has_domain_driven_development_contract(
            source.replace(
                'CWL_DDD_CONTRACT_VERSION: "1"',
                f"CWL_DDD_CONTRACT_VERSION: {replacement}",
                1,
            )
        )
    assert not coordinator.has_domain_driven_development_contract(
        source.replace('  CWL_DDD_CONTRACT_VERSION: "1"\n', "", 1)
    )
    assert not coordinator.has_domain_driven_development_contract(
        source.replace(
            '  CWL_DDD_CONTRACT_VERSION: "1"\n',
            '  CWL_DDD_CONTRACT_VERSION: "1"\n'
            "  CWL_DDD_CONTRACT_VERSION: 1\n",
            1,
        )
    )
    assert not coordinator.has_domain_driven_development_contract(
        source.replace("# cwl-ddd-architecture-audit: required\n", "", 1)
    )


def test_rejects_unscoped_duplicate_or_empty_environment_values() -> None:
    """Only one root environment may own one prompt and capability block."""
    source = _source()
    invalid = [
        source.replace("env:\n", "metadata:\n", 1),
        source + "\nenv:\n  OTHER_VALUE: present\n",
        source.replace(
            "CWL_PRODUCT_AGENT_PROMPT: |", "UNUSED_PROMPT: |", 1
        ),
        source.replace(
            "  CWL_PRODUCT_AGENT_PROMPT: |\n",
            "  CWL_PRODUCT_AGENT_PROMPT: |\n"
            "    duplicate\n"
            "  CWL_PRODUCT_AGENT_PROMPT: |\n",
            1,
        ),
        source.replace(
            "CWL_DDD_CONTRACT_CAPABILITIES: >-", "UNUSED_CAPABILITIES: >-", 1
        ),
        source.replace(
            "  CWL_DDD_CONTRACT_CAPABILITIES: >-\n",
            "  CWL_DDD_CONTRACT_CAPABILITIES: >-\n"
            "    bounded_context\n"
            "  CWL_DDD_CONTRACT_CAPABILITIES: >-\n",
            1,
        ),
        source.replace(
            "    제품 책임과 재사용 경계를 먼저 확인하고 구매자가 체감할 한 단위를 개발한다.\n",
            "",
            1,
        ).replace(
            "    디렉터리, 패키지, API, 데이터베이스, 테스트와 문서의 소유권을 함께 맞춘다.\n",
            "",
            1,
        ),
    ]
    for candidate in invalid:
        assert not coordinator.has_domain_driven_development_contract(candidate)


def test_rejects_comments_unused_prose_wrong_bindings_and_non_agents() -> None:
    """Comments and inert YAML cannot impersonate an executable agent contract."""
    source = _source()
    comments_only = (
        "# cwl-ddd-architecture-audit: required\n"
        + "\n".join(
            f"# {item}" for item in sorted(contract.DDD_CONTRACT_CAPABILITIES)
        )
        + "\n# cwl-ddd-prompt-binding: v1\n"
        + "# --prompt-env CWL_PRODUCT_AGENT_PROMPT\n"
        + "# --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\n"
    )
    assert not coordinator.has_domain_driven_development_contract(comments_only)
    assert not coordinator.has_domain_driven_development_contract(
        source.replace("  CWL_PRODUCT_AGENT_PROMPT: |", "  NOTES: |", 1)
    )
    for old, new in (
        ("# cwl-ddd-prompt-binding: v1", "# unbound"),
        ("--prompt-env CWL_PRODUCT_AGENT_PROMPT", "--prompt-env OTHER_PROMPT"),
        (
            "--architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES",
            "--architecture-contract-env OTHER_CAPABILITIES",
        ),
        (
            "--prompt-env CWL_PRODUCT_AGENT_PROMPT",
            "--prompt-env CWL_PRODUCT_AGENT_PROMPT "
            "--prompt-env CWL_PRODUCT_AGENT_PROMPT",
        ),
    ):
        assert not coordinator.has_domain_driven_development_contract(
            source.replace(old, new, 1)
        )
    for executable in (":", "[", "echo", "export", "false", "printf", "test", "true"):
        assert not coordinator.has_domain_driven_development_contract(
            source.replace(
                "python scripts/automation/commercial_product_development.py",
                executable,
                1,
            )
        )
    assert not coordinator.has_domain_driven_development_contract(
        _replace_command(
            source,
            "--prompt-env CWL_PRODUCT_AGENT_PROMPT "
            "--architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES",
        )
    )


def test_rejects_split_malformed_and_dangling_commands() -> None:
    """Both environment names must reach one well-formed command segment."""
    source = _source()
    for operator in (";", "&&", "||", "|", "&"):
        assert not coordinator.has_domain_driven_development_contract(
            _replace_command(
                source,
                "product-agent --prompt-env CWL_PRODUCT_AGENT_PROMPT "
                f"{operator} product-agent "
                "--architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES",
            )
        )
    assert not coordinator.has_domain_driven_development_contract(
        _replace_command(source, "; product-agent --prompt-env CWL_PRODUCT_AGENT_PROMPT")
    )
    assert not coordinator.has_domain_driven_development_contract(
        source.replace(
            "python scripts/automation/commercial_product_development.py",
            'product-agent "unterminated',
            1,
        )
    )
    assert not coordinator.has_domain_driven_development_contract(
        source.replace(
            "            --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\n",
            "",
            1,
        )
    )
    assert not coordinator.has_domain_driven_development_contract(
        source.replace(
            "            --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\n",
            "            --architecture-contract-env\n",
            1,
        )
    )


def test_rejects_marker_and_flags_distributed_across_run_blocks() -> None:
    """A marker in one step cannot authorize flags executed by another step."""
    source = _source()
    bound = (
        "        run: |\n"
        "          # cwl-ddd-prompt-binding: v1\n"
        "          python scripts/automation/commercial_product_development.py \\\n"
        "            --prompt-env CWL_PRODUCT_AGENT_PROMPT \\\n"
        "            --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\n"
    )
    split = (
        "        run: |\n"
        "          # cwl-ddd-prompt-binding: v1\n"
        "          product-agent --prompt-env CWL_PRODUCT_AGENT_PROMPT\n"
        "      - run: |\n"
        "          product-agent --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\n"
    )
    assert bound in source
    assert not coordinator.has_domain_driven_development_contract(
        source.replace(bound, split, 1)
    )


def test_rejects_non_step_and_unreachable_agent_bindings() -> None:
    """Only directly reachable job-step commands may bind the contract."""
    source = _source()
    run_block = next(iter(contract._step_run_blocks(source)))
    for prefix in ("env:\n", "metadata:\n"):
        inert = source.replace("jobs:\n", f"{prefix}  run: |\n" + "\n".join(
            f"    {line}" for line in run_block.splitlines()
        ) + "\njobs:\n", 1)
        inert = inert.replace("        run: |", "        notes: |", 1)
        assert not coordinator.has_domain_driven_development_contract(inert)

    heredoc = _replace_command(
        source,
        "cat <<'INERT'\n"
        "          product-agent --prompt-env CWL_PRODUCT_AGENT_PROMPT "
        "--architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\n"
        "          INERT",
    )
    assert not coordinator.has_domain_driven_development_contract(heredoc)

    skipped = _replace_command(
        source,
        "if false; then\n"
        "          product-agent --prompt-env CWL_PRODUCT_AGENT_PROMPT "
        "--architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES\n"
        "          fi",
    )
    assert not coordinator.has_domain_driven_development_contract(skipped)


def test_private_command_edges_and_compatibility_script_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover assignment-only, trailing-operator, and direct-script boundaries."""
    assert contract._executable(("env", "MODE=bounded")) is None
    assert list(contract._shell_segments("product-agent ;")) == [("product-agent",)]
    assert contract._step_run_blocks("run: |\n  product-agent") == ()
    assert contract._step_run_blocks("jobs:\n\n  run: |\n    product-agent") == ()

    path = Path(coordinator.__file__)
    monkeypatch.setattr(sys, "argv", [str(path), "--organization", "invalid/name"])
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(path), run_name="__main__")
    assert raised.value.code == 2


def test_manual_entrypoint_still_rejects_non_contract_workflows() -> None:
    """The compatibility facade keeps the original fail-closed API surface."""
    assert not coordinator.is_manual_product_entrypoint(
        workflow(content="# cwl-org-commercial-entrypoint: v1\n")
    )
