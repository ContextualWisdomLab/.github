"""Known second-review App evidence, not arbitrary bot or human prerequisites."""
from copy import deepcopy
import json

import pytest

from scripts.ci import noema_review_gate as noema
from scripts.ci import pr_review_merge_scheduler as scheduler

HEAD = 'a' * 40


def app_review(monkeypatch):
    """Capture the actual publisher body without contacting GitHub or a model."""
    payloads = []
    monkeypatch.setenv('NOEMA_REVIEW_TOKEN_SOURCE', 'noema-review-github-app')
    monkeypatch.setattr(noema, 'run', lambda args, stdin=None: payloads.append(json.loads(stdin)))
    verdict = {
        'decision': 'approve', 'summary': 'Inspected the changed authorization boundary.',
        'findings': [],
        'reviewed_lines': [{'path': 'scripts/ci/example.py', 'line': 2, 'side': 'RIGHT',
                            'analysis': 'The exact-head guard rejects a stale commit before publication.'}],
        'adversarial_validation': {'residual_risk': 'App installation permissions are externally enforced.',
            'probes': [{'path': 'scripts/ci/example.py', 'line': 2, 'side': 'RIGHT',
                        'outcome': 'falsified', 'hypothesis': 'A stale head could bypass admission.',
                        'evidence': 'Changed-line inspection found the stale-head rejection before mutation.'}]},
    }
    noema.submit_review('ContextualWisdomLab/example', 1, {'headRefOid': HEAD},
                        'cwl-noema-review[bot]', verdict)
    return {'author': {'login': 'cwl-noema-review', '__typename': 'Bot'},
            'state': 'APPROVED', 'commit': {'oid': HEAD}, 'body': payloads[0]['body']}


def pull_request(review):
    """Keep GitHub's independent policy decision separate from review identity."""
    return {'author': {'login': 'source-writer'}, 'headRefOid': HEAD,
            'reviewDecision': 'APPROVED', 'reviews': {'nodes': [review]}}


def test_known_noema_app_real_publisher_body_counts_as_independent(monkeypatch):
    pr = pull_request(app_review(monkeypatch))
    assert scheduler.has_independent_current_head_approval(pr)
    assert scheduler.merge_approval_block_reason(pr) is None
    pr['reviewDecision'] = 'REVIEW_REQUIRED'
    assert scheduler.merge_approval_block_reason(pr) is not None


@pytest.mark.parametrize('mutation', ['author', 'unknown', 'primary', 'stale', 'no_commit',
    'empty', 'no_analysis', 'no_probe', 'no_credential', 'no_actor', 'marker_mismatch'])
def test_known_app_admission_preserves_negative_boundaries(monkeypatch, mutation):
    review = app_review(monkeypatch)
    pr = pull_request(review)
    if mutation == 'author':
        pr['author']['login'] = 'cwl-noema-review[bot]'
    elif mutation == 'unknown':
        review['author']['login'] = 'arbitrary-reviewer'
    elif mutation == 'primary':
        review['author']['login'] = 'opencode-agent'
    elif mutation == 'stale':
        review['commit']['oid'] = 'b' * 40
    elif mutation == 'no_commit':
        review['commit'] = None
    elif mutation == 'empty':
        review['body'] = ''
    elif mutation == 'no_analysis':
        review['body'] = review['body'].replace('### Reviewed changed lines', '### Missing')
    elif mutation == 'no_probe':
        review['body'] = review['body'].replace('### Adversarial validation', '### Missing')
    elif mutation == 'no_credential':
        review['body'] = review['body'].replace('noema-review-github-app', 'untrusted-token')
    elif mutation == 'no_actor':
        review['body'] = review['body'].replace('- Actor: `cwl-noema-review[bot]`', '')
    else:
        review['body'] = review['body'].replace('decision=approve', 'decision=request_changes')
    assert not scheduler.has_independent_current_head_approval(pr)


@pytest.mark.parametrize('state', ['CHANGES_REQUESTED', 'DISMISSED', 'APPROVED'])
def test_latest_same_app_policy_state_revokes_old_approval(monkeypatch, state):
    review = app_review(monkeypatch)
    later = deepcopy(review)
    later['author']['login'] = 'cwl-noema-review[bot]'
    later.update(state=state, body='not a substantive model review')
    pr = pull_request(review)
    pr['reviews']['nodes'].append(later)
    assert not scheduler.has_independent_current_head_approval(pr)
