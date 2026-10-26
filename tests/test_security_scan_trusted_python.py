"""Security scanner postprocessing must not execute checkout-owned Python."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

class TrustedPythonTests(unittest.TestCase):
    def test_all_python_steps_ignore_checkout_imports(self):
        jobs = yaml.safe_load((ROOT / '.github/workflows/security-scan.yml').read_text())['jobs']
        count = 0
        for job in jobs.values():
            for step in job['steps']:
                if step.get('shell', '').startswith('python3'):
                    self.assertEqual(step['shell'], 'python3 -I {0}')
                    count += 1
                self.assertNotIn('python3 scripts/', step.get('run', ''))
                self.assertNotIn("python3 <<", step.get('run', ''))
        self.assertEqual(count, 5)

    def test_filter_runs_without_checkout_code(self):
        jobs = yaml.safe_load((ROOT / '.github/workflows/security-scan.yml').read_text())['jobs']
        step = next(s for s in jobs['gitleaks']['steps'] if s['name'] == 'Filter test-classified Gitleaks SARIF results')
        self.assertEqual(step.get('shell'), 'python3 -I {0}')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'json.py').write_text("raise RuntimeError('checkout code executed')")
            (root / 'pathlib.py').write_text("raise RuntimeError('checkout code executed')")
            (root / 'gitleaks-results.sarif').write_text(json.dumps({'runs': [{'results': [
                {'ruleId': 'test', 'properties': {'classifications': ['TEST']}},
                {'ruleId': 'real', 'properties': {}}]}]}))
            script = root / 'trusted-step.py'
            script.write_text(step['run'])
            p = subprocess.run(['python3', '-I', str(script)], cwd=root, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            output = json.loads((root / 'gitleaks-results.upload.sarif').read_text())
            self.assertEqual([r['ruleId'] for r in output['runs'][0]['results']], ['real'])
            (root / 'gitleaks-results.sarif').write_text('invalid')
            p = subprocess.run(['python3', '-I', str(script)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)

if __name__ == '__main__':
    unittest.main()
