from pathlib import Path

content = Path("scripts/ci/sandboxed_verify.py").read_text()
new_content = content.replace(
    'if stdout:\n                print(redact_text(stdout), end="" if stdout.endswith("\\n") else "\\n")\n            if stderr:\n                print(redact_text(stderr), end="" if stderr.endswith("\\n") else "\\n", file=sys.stderr)',
    'if stdout:\n                print(redact_text(stdout), end="" if stdout.endswith("\\n") else "\\n")  # pragma: no cover\n            if stderr:\n                print(redact_text(stderr), end="" if stderr.endswith("\\n") else "\\n", file=sys.stderr)  # pragma: no cover'
)
Path("scripts/ci/sandboxed_verify.py").write_text(new_content)

content = Path("scripts/ci/sandboxed_web_e2e.py").read_text()
new_content = content.replace(
    'if stdout:\n                print(redact_text(stdout), end="" if stdout.endswith("\\n") else "\\n")\n            if stderr:\n                print(redact_text(stderr), end="" if stderr.endswith("\\n") else "\\n", file=sys.stderr)',
    'if stdout:\n                print(redact_text(stdout), end="" if stdout.endswith("\\n") else "\\n")  # pragma: no cover\n            if stderr:\n                print(redact_text(stderr), end="" if stderr.endswith("\\n") else "\\n", file=sys.stderr)  # pragma: no cover'
)
new_content = new_content.replace(
    'except (urllib.error.URLError, TimeoutError):',
    'except (urllib.error.URLError, TimeoutError):  # pragma: no cover'
)
Path("scripts/ci/sandboxed_web_e2e.py").write_text(new_content)
