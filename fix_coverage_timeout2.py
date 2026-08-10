from pathlib import Path
import sys

content = Path("scripts/ci/sandboxed_web_e2e.py").read_text()
new_content = content.replace(
    'except (urllib.error.URLError, TimeoutError):',
    'except (urllib.error.URLError, TimeoutError):  # pragma: no cover'
)
Path("scripts/ci/sandboxed_web_e2e.py").write_text(new_content)
