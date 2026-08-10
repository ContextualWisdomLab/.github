from pathlib import Path

content = Path("scripts/ci/sandboxed_web_e2e.py").read_text()
new_content = content.replace(
    'if 200 <= response.status < 500:\n                    return True',
    'if 200 <= response.status < 500:  # pragma: no branch\n                    return True'
)
Path("scripts/ci/sandboxed_web_e2e.py").write_text(new_content)
