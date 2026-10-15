"""Native toolchain provisioning and isolated backend cache contracts."""

import ast
import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_backend_does_not_restore_an_unused_shared_pip_cache():
    workflow = yaml.load((ROOT / '.github/workflows/naruon-backend-ci.yml').read_text(), Loader=yaml.BaseLoader)
    setup = next(s for s in workflow['jobs']['backend']['steps'] if s.get('name') == 'Set up Python')
    assert setup['with'] == {'python-version': '3.14'}
    assert 'PIP_NO_CACHE_DIR=1' in (ROOT / '.github/workflows/naruon-backend-ci.yml').read_text()


def test_native_contracts_have_a_triggered_pinned_toolchain_gate():
    path = ROOT / '.github/workflows/naruon-supplier-quality-ci.yml'
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    for event in ('push', 'pull_request'):
        assert '.github/workflows/naruon-*-ci.yml' in workflow['on'][event]['paths']
        assert 'integration/naruon/**' in workflow['on'][event]['paths']
        assert 'tests/test_naruon*.py' in workflow['on'][event]['paths']
    assert workflow['permissions'] == {'contents': 'read'}
    job = workflow['jobs']['supplier-contracts']
    assert job['runs-on'] == {'group': 'CWL CI isolated', 'labels': ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated']}
    steps = job['steps']
    names = [s['name'] for s in steps]
    assert names.index('Set up Node') < names.index('Install locked pnpm without lifecycle hooks') < names.index('Run complete supplier contracts and native integration')
    node = next(s for s in steps if s['name'] == 'Set up Node')
    assert node['with'] == {'node-version': '24', 'package-manager-cache': 'false'}
    install = next(s for s in steps if s['name'] == 'Install locked pnpm without lifecycle hooks')['run']
    assert 'npm ci --ignore-scripts' in install
    command = next(s for s in steps if s['name'] == 'Run complete supplier contracts and native integration')['run']
    assert 'tests/test_naruon_reusable_ci_contract.py' in command
    assert 'integration/naruon/test_native_toolchain.py' in command
    assert 'tests/test_naruon_supplier_quality_workflow.py' in command
    assert not any('continue-on-error' in s for s in steps)


def test_native_toolchain_keeps_all_original_integration_cases():
    native = (ROOT / 'integration/naruon/test_native_toolchain.py').read_text()
    for name in ('frontend_emitted_profile_reaches_exact_consumer_private_mkdtemp', 'exact_consumer_artifact_profile_controls', 'pnpm11_native_store_env_prefix_controls', 'corepack_shell_checks_native_pnpm_store_before_setup_node', 'frontend_cache_store_survives_home_cleanup_for_setup_node_post'):
        assert 'def test_' + name in native
    assert 'pytest.skip' not in native
    assert 'db24b8f44a6438e100eab2e690464b971d35ee3c9af4638dcab3af7ee90c8cdd' in native


def test_native_functions_and_parametrizations_match_predecessor_bytes():
    source = (ROOT / 'integration/naruon/test_native_toolchain.py').read_text()
    lines = source.splitlines(keepends=True)
    expected = {'artifact_directory': '49c57e87a528effaffaf1c2db129c959403a70233a124219974ec52ca93e397e', 'test_frontend_emitted_profile_reaches_exact_consumer_private_mkdtemp': '2e478ff8285cb39cfb2f62d2cdb9fb53009f944edeba6049f44c445f130bb75c', 'test_exact_consumer_artifact_profile_controls': '44c72077017bbcf0e688cba16f6bf8974c1a876c8e7121b1e519c6c1e73fb380', 'pinned_pnpm_store': '2318e0489995c1fafe22bbefd3576322150e33bd9225be63d5a036ae1004f884', 'test_pnpm11_native_store_env_prefix_controls': '4f6c9afe608b7b9cd7ae0359194936705e5c50d049c8d93d67c6c2d0990d1096', 'test_corepack_shell_checks_native_pnpm_store_before_setup_node': 'dbb4c9b00d5928b015c7d09f35de4eb7568a81f2e84be4f8465c3fdf1ef75d7b', 'test_frontend_cache_store_survives_home_cleanup_for_setup_node_post': '6fd85074f0d5e272d5a704afc41b63a23f3172e0252ad901b614b193e900083f'}
    actual = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            original = ''.join(lines[start:node.end_lineno])
            actual[node.name] = hashlib.sha256(original.encode()).hexdigest()
    assert actual == expected
