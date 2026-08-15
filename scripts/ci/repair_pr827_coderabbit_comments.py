#!/usr/bin/env python3
"""Apply the verified CodeRabbit repairs for pull request 827."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one exact fragment and fail closed on drift."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement marker, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    """Replace a uniquely delimited source section."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    start_index = text.find(start)
    if start_index < 0 or text.find(start, start_index + 1) >= 0:
        raise SystemExit(f"{path}: start marker missing or ambiguous")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{path}: end marker missing")
    file_path.write_text(
        text[:start_index] + replacement + text[end_index:], encoding="utf-8"
    )


SCRIPT = "scripts/ci/materialize_base_python_requirements.py"
TEST = "tests/test_materialize_base_python_requirements.py"
DOC = "docs/doctoring/opencode-rust-coverage-runtime-boundary.md"
WORKFLOW = ".github/workflows/opencode-review-dispatch.yml"

replace_between(
    SCRIPT,
    "def _is_bounded_requirement_include(line: str) -> bool:\n",
    "def _requirement_lines(content: bytes) -> list[str]:\n",
    '''def _bounded_requirement_include_target(
    line: str,
) -> pathlib.PurePosixPath | None:
    """Return the safe relative target of one bounded requirements include.

    The target may use any normalized relative ``.txt`` name, including names
    such as ``other-hashes.txt``. Eligibility does not confer trust: the exact
    base-tree target must later be a regular blob containing only exact
    SHA-256-pinned package requirements.
    """
    fields = line.split()
    if len(fields) != 2 or fields[0] not in {"-r", "--requirement"}:
        return None
    target = fields[1]
    if (
        target.startswith(("-", "~"))
        or "\\\\" in target
        or ":" in target
        or "?" in target
        or "#" in target
    ):
        return None
    include_path = pathlib.PurePosixPath(target)
    if (
        not include_path.parts
        or target != include_path.as_posix()
        or include_path.is_absolute()
        or "." in include_path.parts
        or ".." in include_path.parts
        or include_path.suffix != ".txt"
    ):
        return None
    return include_path


def _is_bounded_requirement_include(line: str) -> bool:
    """Return whether one include has a safe relative ``.txt`` target."""
    return _bounded_requirement_include_target(line) is not None


''',
)

replace_once(
    SCRIPT,
    "        if _is_candidate_lock_name(candidate.name):\n",
    "        if _is_candidate_lock_path(candidate):\n",
)

helpers = '''def _included_base_lock_blobs(
    repo_root: pathlib.Path,
    base_sha: str,
    source_path: str,
    content: bytes,
    regular_paths: set[str],
) -> list[tuple[pathlib.PurePosixPath, bytes]]:
    """Load direct bounded includes from the exact base as complete closures."""
    source_parent = pathlib.PurePosixPath(source_path).parent
    included: dict[pathlib.PurePosixPath, bytes] = {}
    for line in _requirement_lines(content):
        target = _bounded_requirement_include_target(line)
        if target is None:
            continue
        resolved = source_parent / target
        resolved_path = resolved.as_posix()
        if resolved_path not in regular_paths:
            raise RuntimeError(
                f"bounded include {target} from {source_path} is not a regular base blob"
            )
        included_content = _git(repo_root, "show", f"{base_sha}:{resolved_path}")
        if not _is_fully_hash_pinned_export(included_content):
            raise RuntimeError(
                f"bounded include {resolved_path} must contain only exact SHA-256 pins"
            )
        included[target] = included_content
    return sorted(included.items(), key=lambda item: item[0].as_posix())


def _rewrite_materialized_includes(content: bytes, include_directory: str) -> bytes:
    """Rewrite root include targets to their preserved generated subtree."""
    text = content.decode("utf-8", errors="strict")
    rewritten: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        body = raw_line.rstrip("\\r\\n")
        ending = raw_line[len(body) :]
        stripped = body.strip()
        target = _bounded_requirement_include_target(stripped)
        if target is None:
            rewritten.append(raw_line)
            continue
        indentation = body[: len(body) - len(body.lstrip())]
        option = stripped.split()[0]
        rewritten.append(
            f"{indentation}{option} {include_directory}/{target.as_posix()}{ending}"
        )
    return "".join(rewritten).encode("utf-8")


'''
replace_once(SCRIPT, "def materialize(\n", helpers + "def materialize(\n")

replace_between(
    SCRIPT,
    "def materialize(\n",
    "def main(argv: list[str] | None = None) -> int:\n",
    '''def materialize(
    repo_root: pathlib.Path,
    base_sha: str,
    output_dir: pathlib.Path,
) -> list[dict[str, str]]:
    """Write base locks and resolvable bounded includes into a safe context."""
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_repo = repo_root.resolve()
    entries = _git(resolved_repo, "ls-tree", "-r", "-z", "--full-tree", base_sha)
    regular_paths = {
        path for path, _candidate in _regular_base_blob_paths(entries)
    }
    manifest: list[dict[str, str]] = []
    for index, (source_path, content) in enumerate(
        base_hash_locks(resolved_repo, base_sha)
    ):
        generated_name = f"requirements-{index:03d}.txt"
        include_directory = f"includes-{index:03d}"
        included = _included_base_lock_blobs(
            resolved_repo,
            base_sha,
            source_path,
            content,
            regular_paths,
        )
        for relative_target, included_content in included:
            destination = output_dir / include_directory / Path(*relative_target.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(included_content)
        destination = output_dir / generated_name
        destination.write_bytes(
            _rewrite_materialized_includes(content, include_directory)
        )
        manifest.append({"file": generated_name, "source": source_path})

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    (output_dir / "manifest.txt").write_text(
        "".join(f"{entry['file']}\\n" for entry in manifest),
        encoding="utf-8",
    )
    return manifest


''',
)

replace_once(TEST, "import tarfile\n", "import tarfile\nimport zipfile\n")
replace_once(
    TEST,
    '    assert not materializer._is_hash_pinned(b"-r other-hashes.txt\\n")\n',
    '    assert materializer._is_hash_pinned(b"-r other-hashes.txt\\n")\n',
)
replace_once(
    TEST,
    '    assert not materializer._is_candidate_lock_name("pyproject.toml")\n',
    '    assert not materializer._is_candidate_lock_name("pyproject.toml")\n'
    '    assert materializer._is_candidate_lock_path(\n'
    '        materializer.pathlib.PurePosixPath("requirements/ci.txt")\n'
    '    )\n'
    '    assert materializer._is_candidate_lock_path(\n'
    '        materializer.pathlib.PurePosixPath("service/requirements/package.txt")\n'
    '    )\n'
    '    assert not materializer._is_candidate_lock_path(\n'
    '        materializer.pathlib.PurePosixPath("service/config/ci.txt")\n'
    '    )\n',
)
replace_once(
    TEST,
    '    (repo / "requirements-test.txt").write_text(\n'
    '        "hypothesis==6 --hash=sha256:" + ("b" * 64) + "\\n",\n'
    '        encoding="utf-8",\n'
    '    )\n',
    '    (repo / "requirements-test.txt").write_text(\n'
    '        "hypothesis==6 --hash=sha256:" + ("b" * 64) + "\\n",\n'
    '        encoding="utf-8",\n'
    '    )\n'
    '    requirements_dir = repo / "requirements"\n'
    '    requirements_dir.mkdir()\n'
    '    (requirements_dir / "ci.txt").write_text(\n'
    '        "pytest==9 --hash=sha256:" + ("c" * 64) + "\\n",\n'
    '        encoding="utf-8",\n'
    '    )\n',
)
replace_once(
    TEST,
    '        "requirements-test.txt",\n'
    '        "services/account_unification/requirements-dev.txt",\n',
    '        "requirements-test.txt",\n'
    '        "requirements/ci.txt",\n'
    '        "services/account_unification/requirements-dev.txt",\n',
)

integration_test = '''def test_materialized_bounded_include_is_resolvable_by_pip(tmp_path: Path) -> None:
    """A safe base-owned include survives flattening and pip hash preflight."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    wheel = wheel_dir / "demo-1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/__init__.py", "__version__ = '1'\\n")
        archive.writestr(
            "demo-1.dist-info/METADATA",
            "Metadata-Version: 2.1\\nName: demo\\nVersion: 1\\n",
        )
        archive.writestr(
            "demo-1.dist-info/WHEEL",
            "Wheel-Version: 1.0\\nGenerator: TEPP-test\\n"
            "Root-Is-Purelib: true\\nTag: py3-none-any\\n",
        )
        archive.writestr("demo-1.dist-info/RECORD", "")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()

    (repo / "requirements.txt").write_text(
        "-r other-hashes.txt\\n", encoding="utf-8"
    )
    (repo / "other-hashes.txt").write_text(
        f"demo==1 --hash=sha256:{digest}\\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)
    assert manifest == [{"file": "requirements-000.txt", "source": "requirements.txt"}]
    assert (output / "requirements-000.txt").read_text(encoding="utf-8") == (
        "-r includes-000/other-hashes.txt\\n"
    )
    assert (output / "includes-000" / "other-hashes.txt").is_file()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--disable-pip-version-check",
            "--no-index",
            "--find-links",
            str(wheel_dir),
            "--require-hashes",
            "-r",
            str(output / "requirements-000.txt"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_materialization_rejects_missing_or_nested_include(tmp_path: Path) -> None:
    """Includes must resolve to direct complete hash closures in the exact base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "requirements.txt").write_text("-r child.txt\\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "missing")
    missing_sha = git(repo, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError, match="not a regular base blob"):
        materializer.materialize(repo, missing_sha, tmp_path / "missing-output")

    (repo / "child.txt").write_text("-r grandchild.txt\\n", encoding="utf-8")
    (repo / "grandchild.txt").write_text(
        "demo==1 --hash=sha256:" + ("d" * 64) + "\\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "nested")
    nested_sha = git(repo, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError, match="must contain only exact SHA-256 pins"):
        materializer.materialize(repo, nested_sha, tmp_path / "nested-output")


'''
replace_once(TEST, "def test_rejects_invalid_base_sha", integration_test + "def test_rejects_invalid_base_sha")
replace_once(
    TEST,
    '    assert not materializer._is_bounded_requirement_include("-r /abs/requirements.txt")\n',
    '    assert not materializer._is_bounded_requirement_include("-r /abs/requirements.txt")\n'
    '    assert not materializer._is_bounded_requirement_include("-r pyproject.toml")\n',
)

replace_once(
    "CHANGELOG.md",
    "- Materialized base Python locks only when every package line is an exact SHA-256 pin or a bounded relative `-r`/`--requirement` include. A lone `--require-hashes` directive, a dotted include such as `./lock.txt`, or `-r other-hashes.txt` no longer enters the trusted build context.\n",
    "- Materialized base Python locks only when every package line is an exact SHA-256 pin or a bounded relative `-r`/`--requirement` include. Includes such as `-r other-hashes.txt` remain allowed when the exact base-tree target is a regular, complete SHA-256-pinned closure; a lone `--require-hashes` directive, dotted `./lock.txt`, traversal, absolute, URL, and option-like targets fail closed.\n",
)

replace_once(
    DOC,
    "NIST SP 800-218 PW.4.1 requires third-party software to come from expected,\ntrusted sources with integrity verification (Souppaya et al., 2022). Binding\ncoverage to the reviewed `/usr/bin/llvm-cov-19` and\n`/usr/bin/llvm-profdata-19` executables is that verification; an ambient\n`PATH` lookup would treat a runner-image change as a new producer.\n",
    "NIST SP 800-218 PW.4.1 requires third-party software to come from expected,\ntrusted sources with integrity verification (Souppaya et al., 2022). The exact\n`/usr/bin/llvm-cov-19` and `/usr/bin/llvm-profdata-19` bindings are\nproducer-selection controls: they select reviewed paths and `test -x` verifies\nexecutability. They do not hash or signature-verify the Debian package or binary.\nPackage/image hashes, signatures, repository metadata, and attestations are\nseparate integrity controls and must not be inferred from path equality.\n",
)
replace_once(
    DOC,
    "Debian bookworm currently publishes the versioned `llvm-19` package from\n`llvm-toolchain-19`; Debian package file inventories expose versioned LLVM 19\ntool entry points including `llvm-cov-19`. Pinning the reviewed executable names\ninside the image converts that mutable ambient dependency into an explicit\ncontract that can be checked before source execution.\n",
    "Debian publishes `llvm-19` from the `llvm-toolchain-19` source package; its\nofficial copyright record states `Apache-2.0 WITH LLVM-exception`. Debian package\nfile inventories expose versioned LLVM 19 tool entry points including\n`llvm-cov-19`. Pinning those reviewed executable names inside the image converts\nambient path selection into an explicit, testable producer contract; the Debian\ncopyright record supplies the package license basis, not executable integrity.\n",
)
replace_once(
    DOC,
    "Debian Project. (2026). *File list of package llvm-19*. Debian Packages.\nRetrieved August 10, 2026, from\nhttps://packages.debian.org/bookworm/amd64/llvm-19/filelist\n\n",
    "Debian Project. (2026). *File list of package llvm-19*. Debian Packages.\nRetrieved August 10, 2026, from\nhttps://packages.debian.org/bookworm/amd64/llvm-19/filelist\n\nDebian Project. (2026). *Copyright file for llvm-toolchain-19 19.1.7-20*.\nDebian FTP Masters. Retrieved August 15, 2026, from\nhttps://metadata.ftp-master.debian.org/changelogs/main/l/llvm-toolchain-19/llvm-toolchain-19_19.1.7-20_copyright\n\n",
)

replace_once(
    WORKFLOW,
    "              r-cran-testthat \\\n              llvm-19 \\\n",
    "              r-cran-testthat \\\n              # llvm-19 / llvm-toolchain-19: Apache-2.0 WITH LLVM-exception. \\\n              # See docs/doctoring/opencode-rust-coverage-runtime-boundary.md. \\\n              llvm-19 \\\n",
)
