from pathlib import Path
import sys

content = Path("scripts/ci/sandboxed_web_e2e.py").read_text()
new_content = content.replace(
    '        except (urllib.error.URLError, TimeoutError):  # pragma: no cover  # pragma: no cover\n            time.sleep(1)',
    '        except (urllib.error.URLError, TimeoutError):\n            time.sleep(1)  # pragma: no cover'
)
Path("scripts/ci/sandboxed_web_e2e.py").write_text(new_content)
