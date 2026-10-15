"""Exercise the retained fallback checker with valid and reversed routing."""
import json
import pytest
import yaml
from tests.test_all_self_hosted_runner_contract import test_isolated_fallback_never_selects_privileged_group as check_fallback
from tests.test_all_self_hosted_runner_contract import test_nonprivileged_runners_require_isolated_label as check_static

ISOLATED = {'group':'CWL CI isolated','labels':['self-hosted','linux','x64','cwlab-ci-isolated']}
CONTROL = {'group':'CWL central control','labels':['self-hosted','linux','x64']}


def install_fixture(tmp_path, monkeypatch, typed, suffix, unsafe):
    first, fallback = (ISOLATED, CONTROL) if unsafe else (CONTROL, ISOLATED)
    expression = "github.workflow_ref == 'ContextualWisdomLab/.github/.github/workflows/example.yml@refs/heads/main' && fromJSON('" + json.dumps(first,separators=(',',':')) + "') || fromJSON('" + json.dumps(fallback,separators=(',',':')) + "')"
    selector = {'group':'${{ ('+expression+').group }}','labels':'${{ ('+expression+').labels }}'} if typed else '${{ '+expression+' }}'
    workflows = tmp_path/'.github/workflows'
    workflows.mkdir(parents=True)
    (workflows/f'example.{suffix}').write_text(yaml.safe_dump({'jobs':{f'job{n}':{'runs-on':selector} for n in range(29)}}, width=10000))
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize('typed',[False,True])
@pytest.mark.parametrize('suffix',['yml','yaml'])
def test_checker_rejects_privileged_fallback(tmp_path,monkeypatch,typed,suffix):
    install_fixture(tmp_path,monkeypatch,typed,suffix,True)
    with pytest.raises(AssertionError):
        check_fallback()


@pytest.mark.parametrize('typed',[False,True])
@pytest.mark.parametrize('suffix',['yml','yaml'])
def test_checker_accepts_same_shape_isolated_fallback(tmp_path,monkeypatch,typed,suffix):
    install_fixture(tmp_path,monkeypatch,typed,suffix,False)
    check_fallback()


def test_checker_refuses_empty_conditional_inventory(tmp_path, monkeypatch):
    workflows = tmp_path/'.github/workflows'
    workflows.mkdir(parents=True)
    (workflows/'example.yaml').write_text(yaml.safe_dump({'jobs':{'job':{'runs-on':ISOLATED}}}))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError, match='coverage'):
        check_fallback()


def test_checker_rejects_privileged_group_even_with_isolation_label(tmp_path, monkeypatch):
    install_fixture(tmp_path,monkeypatch,True,'yaml',False)
    path = tmp_path/'.github/workflows/example.yaml'
    text = path.read_text()
    path.write_text(text.replace('CWL CI isolated', 'CWL central control'))
    with pytest.raises(AssertionError, match='unsafe fallback'):
        check_fallback()


def test_checker_exceptions_are_not_counted_as_rejection(tmp_path, monkeypatch):
    install_fixture(tmp_path,monkeypatch,True,'yaml',True)
    def broken_parser(*args):
        raise RuntimeError('fixture parser failure')
    monkeypatch.setattr(yaml, 'safe_load', broken_parser)
    with pytest.raises(RuntimeError, match='fixture parser failure'):
        check_fallback()


def install_static_fixture(tmp_path, monkeypatch, suffix, labels, group='CWL CI isolated', block=False):
    """Write an ordinary selector as actual YAML with a nonstandard valid indent."""
    workflows = tmp_path / '.github/workflows'
    workflows.mkdir(parents=True)
    selector = {'group': group, 'labels': labels}
    document = {'jobs': {'ordinary': {'runs-on': selector}}}
    (workflows / f'ordinary.{suffix}').write_text(
        yaml.safe_dump(document, default_flow_style=not block, indent=4),
    )
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize('suffix', ['yml', 'yaml'])
@pytest.mark.parametrize('block', [False, True])
@pytest.mark.parametrize('missing', ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated'])
def test_static_checker_rejects_each_missing_required_label(tmp_path, monkeypatch, suffix, block, missing):
    """The same isolated group must not hide any missing required label."""
    labels = [label for label in ISOLATED['labels'] if label != missing]
    install_static_fixture(tmp_path, monkeypatch, suffix, labels, block=block)
    with pytest.raises(AssertionError):
        check_static()


@pytest.mark.parametrize('suffix', ['yml', 'yaml'])
@pytest.mark.parametrize('block', [False, True])
def test_static_checker_accepts_intact_isolated_mapping(tmp_path, monkeypatch, suffix, block):
    """Accept the exact positive through the same parser and ordinary-job gate."""
    install_static_fixture(tmp_path, monkeypatch, suffix, list(ISOLATED['labels']), block=block)
    check_static()


@pytest.mark.parametrize('suffix', ['yml', 'yaml'])
@pytest.mark.parametrize('group', ['CWL central control', 'CWL central CodeQL', 'CWL central OpenCode'])
def test_static_checker_preserves_existing_dedicated_groups(tmp_path, monkeypatch, suffix, group):
    """Retain the existing dedicated static exceptions without an isolation label."""
    install_static_fixture(tmp_path, monkeypatch, suffix, list(CONTROL['labels']), group=group)
    check_static()


@pytest.mark.parametrize('suffix', ['yml', 'yaml'])
@pytest.mark.parametrize('labels', [None, 'self-hosted linux x64 cwlab-ci-isolated', ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated', None]])
def test_static_checker_rejects_malformed_label_shapes(tmp_path, monkeypatch, suffix, labels):
    """A substring or malformed list must not substitute for typed label data."""
    install_static_fixture(tmp_path, monkeypatch, suffix, labels)
    with pytest.raises(AssertionError, match='static labels'):
        check_static()


@pytest.mark.parametrize('suffix', ['yml', 'yaml'])
def test_static_checker_requires_exact_group_name(tmp_path, monkeypatch, suffix):
    """Reject a group that only contains the required group name as a substring."""
    install_static_fixture(tmp_path, monkeypatch, suffix, list(ISOLATED['labels']), group='CWL CI isolated extra')
    with pytest.raises(AssertionError, match='unsupported static group'):
        check_static()


K_CSAP_LABELS = ['self-hosted', 'Linux', 'X64', 'k-csap-isolated']


def install_repository_scoped_fixture(tmp_path, monkeypatch, suffix, block, labels,
                                      name='k-csap-skills-quality', job_id='quality'):
    """Exercise the actual aggregate checker with the existing repo-scoped shape."""
    workflows = tmp_path / '.github/workflows'
    workflows.mkdir(parents=True)
    document = {'jobs': {job_id: {'runs-on': labels}}}
    (workflows / f'{name}.{suffix}').write_text(
        yaml.safe_dump(document, default_flow_style=not block),
    )
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize('suffix', ['yml', 'yaml'])
@pytest.mark.parametrize('block', [False, True])
def test_static_checker_accepts_repository_scoped_isolated_list(tmp_path, monkeypatch, suffix, block):
    """Case-insensitive GitHub labels retain all four existing requirements."""
    install_repository_scoped_fixture(tmp_path, monkeypatch, suffix, block, K_CSAP_LABELS)
    check_static()


@pytest.mark.parametrize('suffix', ['yml', 'yaml'])
@pytest.mark.parametrize('missing', K_CSAP_LABELS)
def test_static_checker_rejects_repository_scoped_missing_label(tmp_path, monkeypatch, suffix, missing):
    """Neither repository scoping nor list syntax excuses a missing label."""
    labels = [label for label in K_CSAP_LABELS if label != missing]
    install_repository_scoped_fixture(tmp_path, monkeypatch, suffix, False, labels)
    with pytest.raises(AssertionError):
        check_static()


@pytest.mark.parametrize('labels', [
    ['self-hosted', 'Linux', 'X64', 'k-csap-isolated-extra'],
    ['self-hosted', 'Linux', 'X64', 'cwlab-ci-isolated'],
    ['self-hosted', 'Linux', 'X64', None],
    K_CSAP_LABELS + ['privileged'],
])
def test_static_checker_rejects_repository_scoped_label_drift(tmp_path, monkeypatch, labels):
    """A lookalike, foreign label, malformed element or extra routing cannot pass."""
    install_repository_scoped_fixture(tmp_path, monkeypatch, 'yml', False, labels)
    with pytest.raises(AssertionError):
        check_static()


@pytest.mark.parametrize(('name', 'job_id'), [('ordinary', 'quality'), ('k-csap-skills-quality', 'ordinary')])
def test_static_checker_rejects_repository_scoped_list_in_other_jobs(tmp_path, monkeypatch, name, job_id):
    """The existing caller-repo selector is not a new global label-only exemption."""
    install_repository_scoped_fixture(tmp_path, monkeypatch, 'yaml', True, K_CSAP_LABELS, name, job_id)
    with pytest.raises(AssertionError):
        check_static()


def test_static_checker_requires_nonempty_inventory(tmp_path, monkeypatch):
    """An empty workflow population is not proof of ordinary runner admission."""
    (tmp_path / '.github/workflows').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError, match='coverage is empty'):
        check_static()
