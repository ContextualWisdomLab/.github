"""New sensitivity controls for the two failed final-quality contracts."""
from pathlib import Path
import pytest
from tests import test_noema_issuer_producer_connection as contract


@pytest.mark.parametrize('mutation', ['bypass', 'early_write', 'action_write', 'wide_issuer'])
def test_revised_contracts_reject_security_regressions(tmp_path, monkeypatch, mutation):
    """Actual revised consumers must reject each narrowly changed owned input."""
    root=Path(contract.ROOT)
    workflow=(root/'.github/workflows/noema-review.yml').read_text()
    issuer=(root/'scripts/ci/noema_existing_app_issuer.cjs').read_text()
    if mutation=='bypass':
        workflow=workflow.replace('node "$GITHUB_WORKSPACE/scripts/ci/noema_existing_app_issuer.cjs"','node bypass.cjs',1)
    elif mutation=='early_write':
        issuer=issuer.replace('await fence(read.token,phase);','/* fence removed */',1)
    elif mutation=='action_write':
        marker='      - name: Refresh repository-scoped Noema GitHub App token for publication\n'
        prefix,rest=workflow.split(marker,1)
        workflow=prefix+marker+rest.replace('permission-pull-requests: read','permission-pull-requests: write',1)
    else:
        issuer=issuer.replace("contents:'read',metadata:'read',pull_requests:grant", "contents:'write',metadata:'read',pull_requests:grant",1)
    wf=tmp_path/'.github/workflows/noema-review.yml';wf.parent.mkdir(parents=True);wf.write_text(workflow)
    helper=tmp_path/'scripts/ci/noema_existing_app_issuer.cjs';helper.parent.mkdir(parents=True);helper.write_text(issuer)
    monkeypatch.setattr(contract,'ROOT',tmp_path)
    target=contract.test_workflow_invokes_real_bootstrap_and_phase_producer_before_controller if mutation in ('bypass','early_write') else contract.test_actual_publish_request_has_only_controller_write_permissions
    with pytest.raises(AssertionError):
        target()
