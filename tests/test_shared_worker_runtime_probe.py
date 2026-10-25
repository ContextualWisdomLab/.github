"""Trust boundary contracts for the manual, metadata-only runtime probe."""
from pathlib import Path
import unittest
import yaml

PATH = Path(__file__).resolve().parents[1] / '.github/workflows/shared-worker-runtime-probe.yml'

class ProbeContract(unittest.TestCase):
    def test_trusted_manual_probe(self):
        self.assertTrue(PATH.exists(), 'central trusted runtime probe is absent')
        workflow = yaml.safe_load(PATH.read_text())
        self.assertEqual(workflow.get('on', workflow.get(True)), {'workflow_dispatch': {}})
        self.assertEqual(workflow['permissions'], {})
        job = workflow['jobs']['probe']
        self.assertEqual(job['runs-on'], {'group': 'CWL central control', 'labels': ['self-hosted', 'Linux', 'X64', 'cwlab-control']})
        self.assertIn("github.ref == 'refs/heads/main'", job['if'])
        self.assertIn("github.repository == 'ContextualWisdomLab/.github'", job['if'])
        self.assertEqual(job['timeout-minutes'], 5)
        self.assertTrue(all('uses' not in s for s in job['steps']))
        script = job['steps'][0]['run']
        self.assertIn('docker version --format', script)
        self.assertIn('docker info --format', script)
        for forbidden in ['checkout', 'github.event.inputs', 'docker run', 'docker exec', 'docker pull', 'sudo', 'secrets.']:
            self.assertNotIn(forbidden, PATH.read_text())

if __name__ == '__main__':
    unittest.main()
