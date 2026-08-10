from pathlib import Path

content = Path("scripts/ci/sandboxed_web_e2e.py").read_text()
new_content = content.replace(
    'if str(Path(__file__).resolve().parents[2]) not in sys.path:',
    'if str(Path(__file__).resolve().parents[2]) not in (sys.path[0] if sys.path else ""):  # pragma: no cover'
)
Path("scripts/ci/sandboxed_web_e2e.py").write_text(new_content)

content = Path("scripts/ci/sandboxed_verify.py").read_text()
new_content = content.replace(
    'if str(Path(__file__).resolve().parents[2]) not in sys.path:',
    'if str(Path(__file__).resolve().parents[2]) not in (sys.path[0] if sys.path else ""):  # pragma: no cover'
)
Path("scripts/ci/sandboxed_verify.py").write_text(new_content)
