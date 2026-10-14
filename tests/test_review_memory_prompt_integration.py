"""The real launcher renderer includes the memory protocol, not just an unused doc."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'scripts/ci/render_opencode_prompt_template.py'


def load():
    spec = importlib.util.spec_from_file_location('renderer_memory_test', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_contract_gains_partition_protocol_without_losing_existing_policy(tmp_path, monkeypatch):
    renderer = load()
    prompt = tmp_path / 'opencode-review-contract-orchestrator-free.md'
    prompt.write_text('Existing source/probe rules. Head ${HEAD_SHA}.\n')
    monkeypatch.setenv('HEAD_SHA', 'b'*40)
    assert renderer.main([str(prompt)]) == 0
    text = prompt.read_text()
    assert text.startswith('Existing source/probe rules. Head ' + 'b'*40)
    assert '<!-- cwl-review-memory/v1 -->' in text
    assert 'review_memory.py' in text
    assert 'relationship' in text
    assert 'not approval' in text


def test_plain_templates_remain_byte_compatible(tmp_path, monkeypatch):
    renderer = load()
    prompt = tmp_path / 'prompt.md'
    prompt.write_text('Head ${HEAD_SHA}\n$(do-not-execute)\n')
    monkeypatch.setenv('HEAD_SHA', 'exact')
    assert renderer.main([str(prompt)]) == 0
    assert prompt.read_text() == 'Head exact\n$(do-not-execute)\n'


def test_review_contract_render_is_idempotent(tmp_path):
    renderer = load()
    prompt = tmp_path / 'opencode-review-contract-test.md'
    prompt.write_text('Original policy\n')
    renderer.main([str(prompt)])
    first = prompt.read_text()
    renderer.main([str(prompt)])
    assert prompt.read_text() == first
