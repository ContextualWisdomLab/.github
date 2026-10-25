"""Exact content exception must not disclose PR prose or sibling source."""
import unittest
from scripts.ci import noema_exact_canary as policy

class ExactCanaryTests(unittest.TestCase):
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
