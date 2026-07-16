import re
from pathlib import Path


def test_opencode_docker_root_context_retry_exits_on_success() -> None:
    """Docker evidence must not fail after a successful repository-root retry."""
    workflow = Path(".github/workflows/opencode-review.yml").read_text(encoding="utf-8")

    assert re.search(
        r'docker build --pull=false -f "\$dockerfile" -t "\$image_tag" \.\n'
        r"\s+exit 0\n"
        r"\s+fi\n"
        r'\s+echo "Docker build failed with repository root context; no fallback context remains\."',
        workflow,
    )
