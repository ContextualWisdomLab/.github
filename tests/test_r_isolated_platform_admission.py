"""Source and executable matrix-admission contract; no native R execution."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Admission(unittest.TestCase):
    def test_matrix_admission(self):
        script = ROOT / 'scripts/ci/r_isolated_matrix.py'
        self.assertTrue(script.is_file(), 'Missing supported-platform admission')
        rows = [{'os': 'ubuntu-latest', 'r': 'release'},
                {'os': 'macos-latest', 'r': 'release'},
                {'os': 'windows-latest', 'r': 'release'},
                {'os': 'ubuntu-24.04-arm', 'r': 'release'}]
        result = subprocess.run([sys.executable, str(script), json.dumps(rows)],
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('STOP', result.stderr)
        for invalid in ([], rows[1:], [{'os': 'ubuntu-evil', 'r': 'release'}],
                        [{'os': 'ubuntu-latest', 'r': ''}], {}):
            denied = subprocess.run([sys.executable, str(script), json.dumps(invalid)],
                                    capture_output=True, text=True, check=False)
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual(denied.stdout, '')

    def test_r_selector_is_static_and_matrix_is_admitted(self):
        text = (ROOT / '.github/workflows/r-package-check.yml').read_text()
        self.assertIn('needs: admit-platforms', text)
        self.assertIn('config: ${{ fromJSON(needs.admit-platforms.outputs.matrix) }}', text)
        self.assertIn('labels: [self-hosted, Linux, X64, cwlab-ci-isolated]', text)
        self.assertNotIn('toJSON(matrix.config.os)', text)
        inline = text.split("<<'PY'\n", 1)[1].split('\n          PY', 1)[0]
        emitted = '\n'.join(line[10:] for line in inline.splitlines()) + '\n'
        self.assertEqual(emitted, (ROOT / 'scripts/ci/r_isolated_matrix.py').read_text())


def test_supported_matrix_and_cli_branches_are_exercised_in_process(monkeypatch, capsys):
    """Cover actual admission and CLI errors without executing native R jobs."""
    import pytest
    import runpy
    from scripts.ci.r_isolated_matrix import admit

    rows = [{'os': 'ubuntu-latest', 'r': 'release'},
            {'os': 'ubuntu-24.04', 'r': '4.4'}]
    assert admit(json.dumps(rows)) == rows
    for value in ({}, [], [None], [{'os': 1, 'r': 'release'}],
                  [{'os': 'ubuntu-latest', 'r': ''}],
                  [{'os': 'ubuntu-latest', 'r': 1}],
                  [{'os': 'windows-latest', 'r': 'release'}]):
        with pytest.raises(ValueError):
            admit(json.dumps(value))
    script = str(ROOT / 'scripts/ci/r_isolated_matrix.py')
    monkeypatch.setattr(sys, 'argv', [script, json.dumps(rows)])
    runpy.run_path(script, run_name='__main__')
    assert json.loads(capsys.readouterr().out) == rows
    for argv in ([script], [script, 'not-json']):
        monkeypatch.setattr(sys, 'argv', argv)
        with pytest.raises(SystemExit) as error:
            runpy.run_path(script, run_name='__main__')
        assert error.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == '' and captured.err


if __name__ == '__main__':
    unittest.main()
