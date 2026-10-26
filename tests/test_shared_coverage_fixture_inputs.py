"""Pin the root coverage fixture inputs to the actual admitted sandbox shape."""
from __future__ import annotations

import importlib.util
import inspect
import os
from pathlib import Path
import shutil
import subprocess
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 repository contract
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    """Load the exact fixture helper, without executing a native workload."""
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tests' / (name + '.py'))
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_maturin_fixture_matches_base_admitted_pyo3():
    """The networkless test can resolve only the protected fixture's PyO3."""
    fixture = tomllib.loads((ROOT / 'tests/fixtures/coverage-cargo/Cargo.toml').read_text())
    native = module('test_maturin_offline_build_contract')
    declared = tomllib.loads(native._CARGO_TOML.format(extra_dependency=''))
    assert declared['dependencies']['pyo3'] == fixture['dependencies']['pyo3']


def test_law_temp_fallback_fits_real_sandbox_home():
    """A deliberately long temp layout must still fit the canonical sandbox HOME."""
    law = module('test_law_ai_agent_ci')
    # Inspect only the test's fallback expression; no host /work or system /tmp write.
    import ast
    tree = ast.parse(inspect.getsource(law.short_temp_root))
    suffixes = [n.right.value for n in ast.walk(tree)
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
                and isinstance(n.right, ast.Constant) and isinstance(n.right.value, str)
                and n.right.value.startswith('.cache/')]
    assert len(suffixes) == 1
    assert len('/work/.opencode-sandbox-home/' + suffixes[0] + '/l.XXXXXXXX/lawci.XXXXXX') < 65


def test_law_synthetic_identity_does_not_require_passwd_entry(tmp_path):
    """The uv/cleanup fixture supplies only its synthetic username, not ownership."""
    law = module('test_law_ai_agent_ci')
    source = inspect.getsource(law.test_synthetic_child_failure_and_cleanup_are_not_success)
    assert "'id':" in source
    # The synthetic identity must forward numeric/other id requests to the real tool.
    assert '/usr/bin/id' in source


def test_rust_hygiene_can_exclude_ambient_cargo(tmp_path, monkeypatch):
    """Native shell executes the missing-cargo branch despite ambient Cargo."""
    hygiene = module('test_opencode_coverage_runner_hygiene')
    params = inspect.signature(hygiene._run).parameters
    assert 'system_path' in params, 'fixture cannot exclude distro-installed cargo'
    result = hygiene._run(hygiene._step('Expose runner Rust toolchain')['run'], tmp_path,
                          home=tmp_path / 'home', path_dirs=[], system_path=False)
    assert result.returncode == 0, result.stderr
    assert '::warning::cargo is not installed' in result.stdout
