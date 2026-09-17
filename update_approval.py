import pathlib
p = pathlib.Path('scripts/ci/opencode_existing_approval_gate.py')
text = p.read_text()
new_text = text.replace(
    '    evidence: dict[str, Any] | None = None\n    for match in ADVERSARIAL_BLOCK_RE.finditer(body):',
    '    if "opencode-adversarial-evidence-v1" not in body:\n        return None\n    evidence: dict[str, Any] | None = None\n    for match in ADVERSARIAL_BLOCK_RE.finditer(body):'
)
p.write_text(new_text)
