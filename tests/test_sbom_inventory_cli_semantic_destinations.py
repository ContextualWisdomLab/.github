"""Regression coverage for semantic SBOM aggregator CLI destinations."""

from scripts.ci import sbom_inventory_aggregator as agg


def test_cli_flags_translate_to_semantic_internal_destinations():
    """Stable CLI flags must not leak generic names into owned parser state."""
    argument_parser = agg.build_arg_parser()
    cli_arguments = argument_parser.parse_args(
        [
            "--org",
            "ContextualWisdomLab",
            "--output-dir",
            "docs/sbom",
            "--repo",
            "ContextualWisdomLab/.github",
            "--generated-at",
            "2026-09-02T05:15:45Z",
            "--self-test",
        ]
    )

    assert vars(cli_arguments) == {
        "organization_name": "ContextualWisdomLab",
        "output_directory": "docs/sbom",
        "repository_names": ["ContextualWisdomLab/.github"],
        "generated_timestamp": "2026-09-02T05:15:45Z",
        "self_test_requested": True,
    }
