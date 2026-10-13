"""Explicit invalid receipts must stay invalid after test-harness migration."""
import pytest
from tests.test_opencode_required_verdict_regression import HEAD, runtime_verdict


@pytest.mark.parametrize('overrides', [
    {'body': '## OpenCode Review Overview\n- Gate result: COMMENT'},
    {'body': '@opencode-agent please review'},
    {'body': '## Pull request overview\n- Head SHA: `' + 'b' * 40 + '`'},
    {'id': None},
])
def test_invalid_receipt_is_not_improved_by_fixture_constructor(overrides):
    row = {'id': 1, 'state': 'APPROVED', 'commit_id': HEAD,
           'user': {'login': 'opencode-agent[bot]'},
           'body': '## Pull request overview\n- Head SHA: `' + HEAD + '`'}
    row.update(overrides)
    assert runtime_verdict([row]) == ''
