"""Require typed group/label fields instead of object-valued runs-on expressions."""
from pathlib import Path
import re
import yaml


def test_dynamic_group_routing_uses_explicit_yaml_mapping() -> None:
    observed = 0
    paths = sorted(set(Path('.github/workflows').glob('*.yml')) | set(Path('.github/workflows').glob('*.yaml')))
    for path in paths:
        jobs = yaml.safe_load(path.read_text())['jobs']
        for job_id, job in jobs.items():
            runner = job.get('runs-on')
            if isinstance(runner, str) and '"group":' in runner:
                raise AssertionError(f'{path}:{job_id}: object-valued expression is not a typed runner mapping')
            if isinstance(runner, dict) and str(runner.get('group', '')).startswith('${{ ('):
                observed += 1
                group = runner['group']
                labels = runner['labels']
                assert group.endswith(').group }}'), (path, job_id, group)
                assert labels.endswith(').labels }}'), (path, job_id, labels)
                assert group.removesuffix(').group }}') == labels.removesuffix(').labels }}'), (path, job_id)
                assert 'CWL CI isolated' in group and 'cwlab-ci-isolated' in labels, (path, job_id)
    assert observed == 22, observed
