from pathlib import Path
import re

content = Path("tests/test_sandboxed_web_e2e.py").read_text()
new_content = content.replace('assert "shell" not in popen_calls[0][1]', 'assert popen_calls[0][1].get("shell") is False')
new_content = new_content.replace('assert "shell" not in run_calls[0][1]', 'assert run_calls[0][1].get("shell") is False')
Path("tests/test_sandboxed_web_e2e.py").write_text(new_content)
