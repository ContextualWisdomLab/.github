"""Security contracts for governance-facing SBOM Markdown rendering."""

from scripts.ci import sbom_inventory_aggregator as agg


def test_render_inventory_markdown_neutralizes_untrusted_structure() -> None:
    """SBOM text must not create rows, headings, links, or raw HTML."""
    inventory = agg.build_inventory(
        [
            agg.RepoInventory(
                repo="acme/app\n## Forged repository",
                components=[
                    agg.Component(
                        name="library |\n| forged | 9 | MIT | no |",
                        version="[download](https://attacker.invalid)",
                        license="MIT</td><script>alert(1)</script>",
                    )
                ],
            ),
            agg.RepoInventory(
                repo="acme/broken",
                error="not found\n## Policy approved",
            ),
        ]
    )

    markdown = agg.render_inventory_markdown(
        inventory,
        generated_at="now\n## Forged timestamp",
    )

    assert "\n## Forged repository" not in markdown
    assert "\n| forged | 9 | MIT | no |" not in markdown
    assert "\n## Policy approved" not in markdown
    assert "\n## Forged timestamp" not in markdown
    assert "&#124;" in markdown
    assert "&lt;script&gt;" in markdown
    assert "&#91;download&#93;" in markdown


def test_inventory_summary_discloses_missing_sbom_evidence() -> None:
    """Unavailable repository evidence must not look like a clean inventory."""
    inventory = agg.build_inventory(
        [
            agg.RepoInventory(
                repo="acme/clean",
                components=[agg.Component(name="lib", version="1", license="MIT")],
            ),
            agg.RepoInventory(repo="acme/unavailable", error="forbidden"),
        ]
    )

    assert inventory["summary"]["error_count"] == 1
    assert inventory["summary"]["complete"] is False

    markdown = agg.render_inventory_markdown(inventory, generated_at="now")
    assert "SBOMs unavailable: 1" in markdown
    assert "Evidence completeness: incomplete" in markdown


def test_render_inventory_markdown_neutralizes_autolinks_and_github_references() -> None:
    """Untrusted metadata must not create links, mentions, or issue references."""
    inventory = agg.build_inventory(
        [
            agg.RepoInventory(
                repo="acme/security",
                components=[
                    agg.Component(
                        name="notify @security-team about #123",
                        version="https://attacker.invalid/payload",
                        license="mailto:attacker@example.invalid",
                    )
                ],
            )
        ]
    )

    markdown = agg.render_inventory_markdown(inventory, generated_at="now")

    assert "https://attacker.invalid" not in markdown
    assert "mailto:attacker@example.invalid" not in markdown
    assert "@security-team" not in markdown
    assert "#123" not in markdown
    assert "&#58;" in markdown
    assert "&#64;security-team" in markdown
    assert "&#35;123" in markdown


def test_render_inventory_markdown_neutralizes_emphasis_and_strikethrough() -> None:
    """Untrusted metadata must not create bold, italic, or deleted presentation."""
    inventory = agg.build_inventory(
        [
            agg.RepoInventory(
                repo="**approved** _trusted_ ~~no errors~~",
                components=[],
            )
        ]
    )

    markdown = agg.render_inventory_markdown(inventory, generated_at="now")

    assert "**approved**" not in markdown
    assert "_trusted_" not in markdown
    assert "~~no errors~~" not in markdown
    assert "&#42;&#42;approved&#42;&#42;" in markdown
    assert "&#95;trusted&#95;" in markdown
    assert "&#126;&#126;no errors&#126;&#126;" in markdown

    korean = agg.build_inventory(
        [
            agg.RepoInventory(
                repo="**승인됨** _정상_ ~~오류 없음~~",
                components=[],
            )
        ]
    )
    korean_markdown = agg.render_inventory_markdown(korean, generated_at="now")
    assert "**승인됨**" not in korean_markdown
    assert "_정상_" not in korean_markdown
    assert "~~오류 없음~~" not in korean_markdown
    assert "&#42;&#42;승인됨&#42;&#42;" in korean_markdown
    assert "&#95;정상&#95;" in korean_markdown
    assert "&#126;&#126;오류 없음&#126;&#126;" in korean_markdown


def test_empty_error_remains_unavailable_in_summary_and_report() -> None:
    """Empty error evidence must not disagree across JSON and Markdown channels."""
    inventory = agg.build_inventory([agg.RepoInventory(repo="acme/empty-error", error="")])

    markdown = agg.render_inventory_markdown(inventory, generated_at="now")

    assert inventory["summary"]["error_count"] == 1
    assert inventory["summary"]["complete"] is False
    assert "SBOM unavailable:" in markdown
    assert "No components reported." not in markdown


def test_render_inventory_markdown_neutralizes_dollar_math_delimiters() -> None:
    """Untrusted SBOM values cannot become GitHub inline-math expressions."""
    inventory = agg.build_inventory(
        [
            agg.RepoInventory(
                repo="acme/$x$",
                components=[
                    agg.Component(name="$x$", version="$x$", license="$x$")
                ],
            ),
            agg.RepoInventory(repo="acme/broken", error="$x$"),
        ]
    )

    markdown = agg.render_inventory_markdown(inventory, generated_at="$x$")

    assert "$x$" not in markdown
    assert markdown.count("&#36;") >= 12
