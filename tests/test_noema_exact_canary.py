"""Exact content exception must not disclose PR prose or sibling source."""
import unittest
from scripts.ci import noema_exact_canary as policy

class ExactCanaryTests(unittest.TestCase):
    def test_public_canary_helpers_have_docstrings(self):
        """The canary module remains eligible for the 100% docstring gate."""
        import ast
        from pathlib import Path
        tree = ast.parse(Path(policy.__file__).read_text())
        helpers = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in ('require_target', 'require_content', 'messages'):
            with self.subTest(helper=name):
                self.assertTrue(ast.get_docstring(helpers[name]), name)

    def test_actual_serialization_contains_only_approved_yaml(self):
        import json
        from unittest.mock import patch
        # Synthetic approved-content fixture; the real digest remains immutable.
        import hashlib
        content = 'name: synthetic\n'
        with patch.object(policy, 'DIGEST', hashlib.sha256(content.encode()).hexdigest()):
            from scripts.ci.noema_review_gate import _noema_verdict_response_format
            raw = policy.serialize_payload(content, _noema_verdict_response_format(2))
            decoded = json.loads(raw)
            self.assertEqual(decoded['messages'], policy.messages(content))
            self.assertNotIn('title', decoded)
            for extra in ('\nforeign source', '\nreview thread'):
                decoded['messages'][1]['content'] = policy.INSTRUCTION + content + extra
                with self.assertRaisesRegex(RuntimeError, 'scope'):
                    policy.validate_payload(decoded)

    def test_foreign_schema_is_not_an_input_channel(self):
        import hashlib
        from unittest.mock import patch
        content = 'name: synthetic\n'
        with patch.object(policy, 'DIGEST', hashlib.sha256(content.encode()).hexdigest()):
            with self.assertRaisesRegex(RuntimeError, 'scope'):
                policy.serialize_payload(content, {'description': 'foreign private source'})

    def test_call_llm_uses_only_exact_serialized_input(self):
        import os
        import json
        import hashlib
        from unittest.mock import patch
        from scripts.ci import noema_review_gate as gate
        content = 'name: synthetic\n'
        requests = []
        class StopProbe(BaseException):
            pass
        class Opener:
            def open(self, request):
                requests.append(json.loads(request.data))
                raise StopProbe()
        env = {'NOEMA_EXACT_CANARY_NON_ZDR': 'true',
               'NOEMA_LLM_API_URL': 'https://litellm.poinnetworks.net/v1/chat/completions',
               'NOEMA_LLM_API_KEY': 'synthetic', 'NOEMA_LLM_MODEL': 'auto'}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(policy, 'DIGEST', hashlib.sha256(content.encode()).hexdigest()), \
             patch.object(gate, 'reject_private_llm_url'), \
             patch.object(gate, 'fetch_changed_files', return_value=[(policy.PATH, 'added')]), \
             patch.object(gate, 'fetch_file_content_at_ref', return_value=content), \
             patch.object(gate.urllib.request, 'build_opener', return_value=Opener()):
            with self.assertRaises(StopProbe):
                gate.call_llm(policy.REPOSITORY, 4,
                    {'headRefOid': policy.HEAD, 'title': 'PRIVATE TITLE'},
                    'PRIVATE DIFF', False, policy.HEAD, 'PRIVATE THREAD', [policy.PATH])
        self.assertEqual(len(requests), 1)
        schema = requests[0]['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['adversarial_validation']['properties']['probes']['minItems'],
                         gate._required_probe_count('', [policy.PATH]))
        self.assertEqual(requests[0]['messages'], [
            {'role': 'system', 'content': policy.SYSTEM},
            {'role': 'user', 'content': policy.INSTRUCTION + content}])

    def test_workflow_uses_dedicated_default_closed_exception(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / '.github/workflows/noema-review.yml').read_text()
        self.assertIn("NOEMA_EXACT_CANARY_NON_ZDR: ${{ vars.NOEMA_EXACT_CANARY_NON_ZDR || 'false' }}", source)
        self.assertIn('secrets.NOEMA_EXACT_CANARY_API_KEY', source)
        self.assertIn('python3 -m scripts.ci.noema_exact_canary', source)

    def test_canary_credential_selection_rejects_pat_oidc_before_model(self):
        import os
        import subprocess
        import tempfile
        from pathlib import Path
        import yaml
        root = Path(__file__).resolve().parents[1]
        workflow = yaml.load((root / '.github/workflows/noema-review.yml').read_text(), Loader=yaml.BaseLoader)
        step = next(s for s in workflow['jobs']['noema-review']['steps'] if s['name'] == 'Select fail-closed Noema reviewer credential')
        for mode, pat, app, expected in [('true', True, True, None), ('true', False, False, None),
                                         ('true', False, True, 'github-app'), ('false', True, True, 'pat')]:
            with self.subTest(mode=mode, pat=pat, app=app), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'out'
                env = dict(PATH=os.environ['PATH'], TARGET_REPOSITORY=policy.REPOSITORY,
                           NOEMA_EXACT_CANARY_NON_ZDR=mode, GITHUB_OUTPUT=str(output),
                           NOEMA_REVIEW_TOKEN='synthetic-pat' if pat else '',
                           NOEMA_GITHUB_APP_CLIENT_ID='synthetic-id' if app else '',
                           NOEMA_GITHUB_APP_PRIVATE_KEY='synthetic-key' if app else '',
                           TOKEN_EXCHANGE_URL='https://inert.invalid', GH_TOKEN='ambient-must-not-borrow')
                result = subprocess.run(['bash', '-c', step['run']], env=env, capture_output=True, text=True)
                if expected is None:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Non-ZDR canary requires native GitHub App selection', result.stdout)
                    self.assertNotIn('source=', output.read_text())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('source=' + expected, output.read_text())

    def test_advertised_minimum_survives_actual_validator(self):
        import os
        import json
        import hashlib
        from unittest.mock import patch
        from scripts.ci import noema_review_gate as gate
        content = 'name: synthetic\non: workflow_dispatch\n'
        requests = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                schema = requests[-1]['response_format']['json_schema']['schema']
                count = schema['properties']['adversarial_validation']['properties']['probes']['minItems']
                verdict = {'decision': 'approve', 'summary': 'Synthetic review.', 'findings': [],
                           'reviewed_lines': [{'path': policy.PATH, 'line': 1, 'side': 'RIGHT', 'analysis': 'Examined exact added workflow.'}],
                           'adversarial_validation': {'status': 'passed', 'residual_risk': 'Offline fixture only.',
                               'probes': [{'path': policy.PATH, 'line': i + 1, 'side': 'RIGHT',
                                           'hypothesis': f'Regression {i}', 'attack_or_counterexample': f'Counterexample {i}',
                                           'evidence': f'Exact line {i + 1}', 'outcome': 'falsified'} for i in range(count)]}}
                return json.dumps({'choices': [{'message': {'content': json.dumps(verdict)}}]}).encode()
        class Opener:
            def open(self, request):
                requests.append(json.loads(request.data))
                return Response()
        env = {'NOEMA_EXACT_CANARY_NON_ZDR': 'true',
               'NOEMA_LLM_API_URL': 'https://litellm.poinnetworks.net/v1/chat/completions',
               'NOEMA_LLM_API_KEY': 'synthetic', 'NOEMA_LLM_MODEL': 'auto'}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(policy, 'DIGEST', hashlib.sha256(content.encode()).hexdigest()), \
             patch.object(gate, 'reject_private_llm_url'), \
             patch.object(gate, 'fetch_changed_files', return_value=[(policy.PATH, 'added')]), \
             patch.object(gate, 'fetch_file_content_at_ref', return_value=content), \
             patch.object(gate.urllib.request, 'build_opener', return_value=Opener()):
            verdict = gate.call_llm(policy.REPOSITORY, 4, {'headRefOid': policy.HEAD},
                                    'PRIVATE DIFF', False, policy.HEAD, 'PRIVATE THREAD', [policy.PATH])
        self.assertEqual(verdict['decision'], 'approve')
        self.assertEqual(len(verdict['adversarial_validation']['probes']), 2)
        self.assertEqual(len(requests), 1)

    def test_scope_is_exact(self):
        policy.require_target(policy.REPOSITORY, policy.NUMBER, policy.HEAD)
        for args in [('foreign/repo', 4, policy.HEAD),
                     (policy.REPOSITORY, True, policy.HEAD),
                     (policy.REPOSITORY, 5, policy.HEAD),
                     (policy.REPOSITORY, 4, 'a' * 40)]:
            with self.assertRaisesRegex(RuntimeError, 'scope'):
                policy.require_target(*args)

    def test_payload_refuses_unapproved_context(self):
        with self.assertRaisesRegex(RuntimeError, 'scope'):
            policy.validate_payload({'messages': [{'role': 'user', 'content': 'foreign private source'}]})

if __name__ == '__main__':
    unittest.main()


"""Public CLI privacy regression using real consumers and finite IO adapters."""
import hashlib, json, os, pathlib, subprocess, sys, uuid
import pytest

ROOT=pathlib.Path(__file__).resolve().parents[1]

MATRIX = [(entry, stage+':'+kind)
    for entry,stages in [('prepare',('pr','files','content','http','enter','read','close','envelope','fsync')),
                         ('policy',('pr','files','content')),
                         ('gate',('pr','files','content','http','enter','read','close','readback')),
                         ('publish',('pr','cleanup'))]
    for stage in stages for kind in ('nonzero','decode','runtime','os','value','interrupt','exit')
    if kind!='nonzero' or stage in {'pr','files','content','readback'}]
MATRIX += [('prepare',stage+':'+kind) for stage in ('error_read','error_close') for kind in ('runtime','os','value','interrupt','exit')]
MATRIX += [(entry,case) for entry in ('prepare','gate') for case in ('http:url','http:http','verdict:invalid','model_decode:invalid')]
MATRIX += [('prepare','telemetry:success'),('prepare','context:runtime'),('prepare','context:os'),('prepare','context:interrupt'),('prepare','context:exit'),('prepare','diff:nonzero'),('prepare','success:ok'),('policy','success:ok'),('publish','parse_envelope:decode')]
MATRIX += [(entry,stage+':'+kind) for entry,stages in (
    ('workflow_admit',('pr','files','content')),('workflow_prepare',('pr','files','content','read','close','fsync')))
    for stage in stages for kind in ('nonzero','os','interrupt','exit')
    if kind!='nonzero' or stage in {'pr','files','content'}]
MATRIX += [('workflow_admit','success:ok'),('workflow_prepare','success:ok')]
MATRIX += [('native_'+entry,case) for entry,case in (
    ('prepare','pr:nonzero'),('prepare','files:nonzero'),('prepare','content:nonzero'),
    ('prepare','success:ok'),('policy','content:nonzero'),('policy','success:ok'))]

@pytest.mark.parametrize('entry,case', MATRIX)
def test_public_cli_does_not_expose_private_context(entry,case,tmp_path):
    marker='PRIVATE_CANARY_'+uuid.uuid4().hex
    input_file=tmp_path/'input.json';state_file=tmp_path/'state.json'
    input_file.write_text(json.dumps({'entry':entry,'case':case,'marker':marker}))
    source=str(ROOT)
    workflow=entry.startswith('workflow_')
    native=entry.startswith('native_')
    actual_entry={'workflow_admit':'policy','workflow_prepare':'prepare'}.get(entry,entry.removeprefix('native_'))
    input_file.write_text(json.dumps({'entry':actual_entry,'case':case,'marker':marker,'native':native}))
    environment={'PATH':os.environ['PATH'],'HOME':str(tmp_path),'TMPDIR':str(tmp_path),
       'NOEMA_EXACT_CANARY_NON_ZDR':'true','NOEMA_LLM_API_URL':'https://litellm.poinnetworks.net/v1/chat/completions',
       'NOEMA_LLM_MODEL':'auto','NOEMA_LLM_API_KEY':'synthetic',
       'NOEMA_REVIEW_TOKEN_SOURCE':'noema-review-github-app','NOEMA_REVIEW_ACTOR':'cwl-noema-review[bot]',
       'NOEMA_REVIEW_INSTALLATION_ID':'1','FIXTURE_SOURCE':source,'FIXTURE_INPUT':str(input_file),'FIXTURE_STATE':str(state_file)}
    command=[sys.executable,'-I','-B',str(ROOT/'tests/fixtures/noema_canary_cli_fixture.py')]
    if native:
        import shlex
        launcher=tmp_path/'native-bin';launcher.mkdir()
        script=launcher/'gh'
        script.write_text('#!/bin/sh\nexec '+shlex.join([sys.executable,'-I','-B',str(ROOT/'tests/fixtures/noema_canary_github_fixture.py')])+' "$@"\n')
        script.chmod(0o700)
        environment['PATH']=str(launcher)+os.pathsep+environment['PATH']
    if workflow:
        import shlex
        import yaml
        launcher=tmp_path/'bin';launcher.mkdir()
        script=launcher/'python3'
        script.write_text('#!/bin/sh\nexec '+shlex.join(command)+' "$@"\n');script.chmod(0o700)
        environment.update(PATH=str(launcher)+os.pathsep+environment['PATH'],TARGET_REPOSITORY=policy.REPOSITORY,
          PR_NUMBER='4',EXPECTED_HEAD_SHA=policy.HEAD,NOEMA_EXACT_CANARY_API_KEY='synthetic',GH_TOKEN='synthetic',
          PERSONAL_ROUTE_SELECTED='true',GITHUB_WORKSPACE=str(ROOT),RUNNER_TEMP=str(tmp_path),GITHUB_OUTPUT=str(tmp_path/'out'))
        workflow_doc=yaml.load((ROOT/'.github/workflows/noema-review.yml').read_text(),Loader=yaml.BaseLoader)
        step_name='Admit existing personal LiteLLM auto route' if entry=='workflow_admit' else 'Prepare Noema model verdict'
        step=next(s for s in workflow_doc['jobs']['noema-review']['steps'] if s.get('name')==step_name)
        command=['bash','-c',step['run']]
    if sys.platform=='darwin':
        profile='(version 1)(allow default)(deny network*)(deny file-write*)(allow file-write* (subpath '+json.dumps(str(tmp_path))+'))'
        command=['/usr/bin/sandbox-exec','-p',profile,*command]
    result=subprocess.run(command,env=environment,cwd=source,capture_output=True,timeout=20)
    (tmp_path/'stdout.bin').write_bytes(result.stdout);(tmp_path/'stderr.bin').write_bytes(result.stderr)
    record={'entry':entry,'case':case,'exit':result.returncode,'stdout_sha256':hashlib.sha256(result.stdout).hexdigest(),
       'stderr_sha256':hashlib.sha256(result.stderr).hexdigest(),'marker_in_logs':marker.encode() in result.stdout+result.stderr}
    state=json.loads(state_file.read_text())
    record['external_calls']=state['external_calls'];record['requests']=len(state['http_requests']);record['publications']=state['publications']
    record['stage_faults']=state['stage_faults'];record['context_skipped']=state.get('context_skipped',False)
    record['marker_in_requests']=any(marker in r['data'] for r in state['http_requests'])
    if state['http_requests']:
        payload=json.loads(state['http_requests'][0]['data'])
        assert set(payload)=={'model','messages','response_format'}
        assert payload['model']=='auto'
        assert payload['messages']==[{'role':'system','content':'Return strict JSON only. Do not include markdown.'},
          {'role':'user','content':'Independently review this exact YAML for correctness and security. Return the declared response schema. Cite changed RIGHT-side lines. For approval falsify at least two distinct concrete regression hypotheses; for request_changes confirm a concrete finding. This is a complete new file; no other repository context is authorized.\nRepository: ContextualWisdomLab/traveling-agent\nPR: 4\nHead: bf85ddde01f871f0e713db54aae5a16883777d9f\nPath: .github/workflows/docker-ephemeral-canary.yml\nname: synthetic\non: workflow_dispatch\n'}]
    (tmp_path/'result.json').write_text(json.dumps(record,indent=2))
    if workflow:
        assert not any(stage in state['external_calls'] for stage in ('diff','context'))
        if case=='success:ok':
            assert result.returncode==0
            outputs=(tmp_path/'out').read_text()
            assert ('selected=true' if entry=='workflow_admit' else 'prepared=true') in outputs
        else:
            assert result.returncode!=0
    assert not record['marker_in_logs'], 'Private sentinel reached the actual public CLI output'
    assert not record['marker_in_requests'], 'Private sentinel reached the actual HTTP request payload'
    assert record['publications']==0
    stage,kind=case.split(':',1)
    skipped=entry=='prepare' and state.get('context_skipped',False) and stage in {'context','diff'}
    success=stage in {'success','telemetry'} or skipped or (stage=='context' and kind=='runtime')
    expected=0 if success else 130 if kind=='interrupt' else 1
    if not workflow:
        assert result.returncode==expected
    if not success and stage in {'pr','files','content','readback'}:
        assert stage in state['external_calls'], 'Failure boundary was not reached'
    if stage in {'envelope','fsync','cleanup'}:
        assert stage in state['stage_faults'], 'File lifecycle boundary was not reached'
    if stage in {'http','enter','read','close','error_read','error_close','verdict','model_decode','telemetry','envelope','fsync'}:
        assert record['requests']==1
    if stage in {'pr','files','content','parse_envelope','cleanup'}:
        assert record['requests']==0
