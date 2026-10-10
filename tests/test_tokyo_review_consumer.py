"""Tokyo admission reuses central dispatch, never a leaf worker or unknown App."""
import json
from pathlib import Path

from scripts.ci import noema_review_handoff as handoff

ROOT = Path(__file__).resolve().parents[1]
TOKYO = 'ContextualWisdomLab/tokyo-travel-2026'


def test_tokyo_source_target_is_explicit_and_unique():
    targets = json.loads((ROOT / 'scripts/ci/opencode_repository_dispatch_targets.json').read_text())['targets']
    assert targets.count(TOKYO) == 1


def test_leaf_handoff_dispatches_central_handler_with_exact_target_head():
    calls = []
    handoff.dispatch_noema(TOKYO, 3, 'a' * 40,
                          runner=lambda args, stdin: calls.append((args, json.loads(stdin))))
    assert calls[0][0] == ['api', '-X', 'POST', 'repos/ContextualWisdomLab/.github/dispatches', '--input', '-']
    assert calls[0][1] == {'event_type': 'noema-review', 'client_payload': {
        'target_repository': TOKYO, 'pr_number': 3, 'pr_head_sha': 'a' * 40}}


def test_tokyo_noema_selects_only_existing_self_hosted_groups():
    source = (ROOT / '.github/workflows/noema-review.yml').read_text()
    selectors = [line for line in source.splitlines() if line.strip().startswith(('group: ${{', 'labels: ${{'))]
    assert selectors
    for line in selectors:
        assert "github.repository == '" + TOKYO + "'" in line
        assert 'CWL CI isolated' in line
        assert 'ubuntu-24.04' not in line
