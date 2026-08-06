from pathlib import Path


WORKFLOW_PATH = Path('.github/workflows/opencode-review-dispatch.yml')


def _coverage_dockerfile(workflow: str) -> str:
    """Return the trusted coverage Dockerfile embedded in the OpenCode workflow.

    The coverage image is generated inside one YAML shell block. Isolating only
    that heredoc keeps these assertions focused on the networked, trusted image
    build and prevents unrelated workflow text from satisfying the contract.
    """

    start_marker = 'cat >"$coverage_build_dir/Dockerfile" <<\'DOCKERFILE\''
    start = workflow.index(start_marker) + len(start_marker)
    end = workflow.index('\n          DOCKERFILE', start)
    return workflow[start:end]


def test_trusted_rust_coverage_image_supplies_matching_llvm_binaries() -> None:
    """Require cargo-llvm-cov to use the LLVM tools matching Debian rustc.

    Debian's Rust package does not install rustup's ``llvm-tools-preview``
    component. The trusted image must therefore install Debian LLVM 19 and bind
    cargo-llvm-cov to those exact binaries, otherwise every Rust repository
    fails before any current-head coverage can be measured.
    """

    workflow = WORKFLOW_PATH.read_text(encoding='utf-8')
    dockerfile = _coverage_dockerfile(workflow)

    assert 'llvm-19 \\\n' in dockerfile
    assert 'ENV LLVM_COV=/usr/bin/llvm-cov-19' in dockerfile
    assert 'ENV LLVM_PROFDATA=/usr/bin/llvm-profdata-19' in dockerfile
    assert 'test -x "$LLVM_COV"' in dockerfile
    assert 'test -x "$LLVM_PROFDATA"' in dockerfile
    assert 'LLVM version: 19' in dockerfile
    assert 'https://sh.rustup.rs' not in dockerfile
