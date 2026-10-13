"""New sensitivity controls for the two failed final-quality contracts."""
from pathlib import Path
import pytest
from tests import test_noema_issuer_producer_connection as contract


@pytest.mark.parametrize('mutation', ['bypass', 'missing_write', 'wide_permission'])
def test_revised_contracts_reject_security_regressions(tmp_path, monkeypatch, mutation):
    """Actual revised consumers must reject each narrowly changed owned input."""
    root=Path(contract.ROOT)
    workflow=(root/'.github/workflows/noema-review.yml').read_text()
    if mutation=='bypass':
        workflow=workflow.replace('.github/actions/noema-review/two_phase.py"','bypass.py"',1)
    elif mutation=='missing_write':
        marker='      - name: Refresh repository-scoped Noema GitHub App token for publication\n'
        prefix,rest=workflow.split(marker,1)
        workflow=prefix+marker+rest.replace('permission-pull-requests: write','permission-pull-requests: read',1)
    else:
        marker='      - name: Refresh repository-scoped Noema GitHub App token for publication\n'
        prefix,rest=workflow.split(marker,1)
        workflow=prefix+marker+rest.replace('permission-contents: read','permission-contents: write',1)
    wf=tmp_path/'.github/workflows/noema-review.yml';wf.parent.mkdir(parents=True);wf.write_text(workflow)
    monkeypatch.setattr(contract,'ROOT',tmp_path)
    target=contract.test_normal_workflow_does_not_require_unprovided_bootstrap_inputs if mutation == 'bypass' else contract.test_actual_publish_request_has_only_scoped_app_write_permissions
    with pytest.raises(AssertionError):
        target()
