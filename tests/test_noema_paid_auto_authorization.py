"""Noema cost authorization is independent of private retention admission."""
import pathlib
import unittest
import subprocess
import sys
import os
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

class PaidAutoWorkflowTests(unittest.TestCase):
    def test_noema_passes_explicit_default_closed_paid_authorization(self):
        source = (ROOT / '.github/workflows/noema-review.yml').read_text()
        self.assertIn("NOEMA_REVIEW_PAID_AUTO_AUTHORIZED: ${{ vars.NOEMA_REVIEW_PAID_AUTO_AUTHORIZED || 'false' }}", source)
        self.assertIn('--paid-auto-authorized "$NOEMA_REVIEW_PAID_AUTO_AUTHORIZED"', source)
        self.assertIn('--zero-retention "$PERSONAL_REVIEW_ZDR_ATTESTED"', source)
        self.assertIn('--private-target "$PRIVATE_TARGET"', source)

    def test_paid_authorized_private_route_with_retention_is_admitted(self):
        result = subprocess.run([sys.executable, '-m', 'scripts.ci.personal_review_route',
            '--paid-auto-authorized', 'true', '--zero-cost', 'false',
            '--zero-retention', 'true', '--private-target', 'true'],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_paid_authority_never_substitutes_private_retention(self):
        result = subprocess.run([sys.executable, '-m', 'scripts.ci.personal_review_route',
            '--paid-auto-authorized', 'true', '--zero-cost', 'false',
            '--zero-retention', 'false', '--private-target', 'true'],
            cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('zero-retention supplier is not attested', result.stderr)

    def test_paid_authority_defaults_closed(self):
        result = subprocess.run([sys.executable, '-m', 'scripts.ci.personal_review_route',
            '--zero-cost', 'false', '--zero-retention', 'true', '--private-target', 'true'],
            cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('zero-cost supplier is not attested', result.stderr)

    def test_real_workflow_shell_preserves_privacy_boundary(self):
        source = (ROOT / '.github/workflows/noema-review.yml').read_text()
        section = source.split('      - name: Admit existing personal LiteLLM auto route\n', 1)[1]
        block = section.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0]
        shell = '\n'.join(line[10:] for line in block.splitlines())
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / 'output'
            env = dict(os.environ, LLM_GATEWAY_API_KEY='synthetic-not-a-key',
                NOEMA_REVIEW_PAID_AUTO_AUTHORIZED='true',
                PERSONAL_REVIEW_ZERO_COST_ATTESTED='false',
                PERSONAL_REVIEW_PUBLIC_AUTO_AUTHORIZED='false',
                PERSONAL_REVIEW_ZDR_ATTESTED='false', PRIVATE_TARGET='true',
                GITHUB_OUTPUT=str(output))
            denied = subprocess.run(['bash', '-c', shell], cwd=ROOT, env=env,
                capture_output=True, text=True)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('zero-retention supplier is not attested', denied.stderr)
            self.assertFalse(output.exists())
            env['PERSONAL_REVIEW_ZDR_ATTESTED'] = 'true'  # synthetic positive only
            admitted = subprocess.run(['bash', '-c', shell], cwd=ROOT, env=env,
                capture_output=True, text=True)
            self.assertEqual(admitted.returncode, 0, admitted.stderr)
            self.assertEqual(output.read_text(), 'selected=true\n')

if __name__ == '__main__':
    unittest.main()
