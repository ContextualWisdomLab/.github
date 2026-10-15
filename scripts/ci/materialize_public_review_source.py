"""공개 PR의 고정 base/head를 credential-free Git child로 재구성한다.

신뢰된 metadata가 명시한 public 대상만 받는다. API 재조회, 자격증명,
artifact fallback 및 제품 코드 실행은 하지 않는다. 실행 전 runner의 독점
job directory와 시스템 Git/Python은 신뢰 경계다. 동일 UID의 경쟁 writer나
Actions worker ancestor의 자격증명까지 이 helper가 격리한다고 주장하지 않는다.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Callable


class MaterializationError(RuntimeError):
    """민감한 외부 출력 없이 source admission 실패를 표시한다."""


GIT_CONFIG = (
    "credential.helper=", "credential.interactive=false", "http.extraHeader=",
    "http.followRedirects=false", "http.sslVerify=true", "http.proxy=",
    "protocol.allow=never", "protocol.https.allow=always", "core.hooksPath=/dev/null",
    "core.attributesFile=/dev/null", "core.fsmonitor=false", "core.sshCommand=/usr/bin/false",
    "commit.gpgSign=false", "tag.gpgSign=false", "merge.gpgSign=false",
    "core.autocrlf=false", "core.protectHFS=true", "core.protectNTFS=true",
    "submodule.recurse=false", "fetch.recurseSubmodules=false", "gc.auto=0",
    "maintenance.auto=false", "user.name=github-actions[bot]",
    "user.email=41898282+github-actions[bot]@users.noreply.github.com",
)


def _temporary_root(path: Path) -> Path:
    """실제 runner temp와 모든 조상에서 symlink/비디렉터리를 거부한다."""
    if not path.is_absolute() or any(ord(c) < 32 for c in str(path)):
        raise MaterializationError("invalid temporary root")
    for part in (path, *path.parents):
        mode = part.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise MaterializationError("invalid temporary root")
    info = path.stat()
    if path == Path("/") or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise MaterializationError("invalid temporary root")
    return path


def _environment(home: Path) -> dict[str, str]:
    """상속 env 대신 고정된 Git 실행 환경만 전달한다."""
    return {
        "PATH": "/usr/bin:/bin", "HOME": str(home), "XDG_CONFIG_HOME": str(home),
        "TMPDIR": str(home), "LC_ALL": "C", "LANG": "C",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_EDITOR": "/usr/bin/false", "GIT_SEQUENCE_EDITOR": "/usr/bin/false",
        "GIT_MERGE_AUTOEDIT": "no", "GIT_PAGER": "/bin/cat",
    }


def _admit_entries(inventory: bytes) -> None:
    """Checkout 전에 archive와 같은 regular-file/tree 경계를 검사한다."""
    for record in inventory.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, _oid = metadata.split(b" ")
            name = raw_path.decode("utf-8")
        except (ValueError, UnicodeError):
            raise MaterializationError("invalid source entry") from None
        path = PurePosixPath(name)
        if (mode not in (b"100644", b"100755") or kind != b"blob"
                or not name or path.is_absolute() or "\\" in name
                or any(ord(c) < 32 for c in name)
                or any(p in ("", ".", "..") or p.casefold() == ".git" for p in name.split("/"))):
            raise MaterializationError("invalid source entry")


def materialize_public_source(
    *, repository: str, base_sha: str, head_sha: str, is_private: str,
    runner_temp: Path, run_id: str, run_attempt: str,
    git_executable: Path = Path("/usr/bin/git"), runner: Callable = subprocess.run,
) -> Path:
    """정상 공개 tuple의 완전한 history와 merge tree를 job 전용 경로에 만든다."""
    if is_private != "false":
        raise MaterializationError("explicit public visibility required")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.][A-Za-z0-9_.-]{0,99}", repository)
            or repository.split("/")[-1] in (".", "..")):
        raise MaterializationError("invalid repository")
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (base_sha, head_sha)):
        raise MaterializationError("invalid commit SHA")
    if not all(re.fullmatch(r"[1-9][0-9]{0,19}", value) for value in (run_id, run_attempt)):
        raise MaterializationError("invalid run identity")
    if not git_executable.is_absolute() or not git_executable.is_file():
        raise MaterializationError("trusted git executable unavailable")
    root = _temporary_root(runner_temp)
    output = root / f"opencode-coverage-{run_id}-{run_attempt}"
    try:
        output.mkdir(mode=0o700)
    except FileExistsError:
        raise MaterializationError("output already exists") from None
    identity = output.stat()
    succeeded = False
    try:
        with tempfile.TemporaryDirectory(prefix="public-source-home-", dir=root) as private_home:
            environment = _environment(Path(private_home))

            def git(*args: str) -> bytes:
                """고정 env/config로 Git만 실행하고 외부 오류 텍스트를 숨긴다."""
                argv = [str(git_executable)]
                for value in GIT_CONFIG:
                    argv.extend(("-c", value))
                argv.extend(args)
                try:
                    result = runner(argv, cwd=output, env=environment,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, shell=False, check=False, timeout=300)
                except (OSError, subprocess.TimeoutExpired):
                    raise MaterializationError("git command failed") from None
                if result.returncode:
                    raise MaterializationError("git command failed")
                return result.stdout

            git("init", "-q", "--template=", "--object-format=sha1", ".")
            git("fetch", "--no-tags", "--no-recurse-submodules",
                f"https://github.com/{repository}.git", base_sha, head_sha)
            for commit in (base_sha, head_sha):
                if (git("cat-file", "-t", commit).strip() != b"commit"
                        or git("rev-parse", "--verify", f"{commit}^{{commit}}").strip() != commit.encode()):
                    raise MaterializationError("invalid commit object")
                _admit_entries(git("ls-tree", "-rz", commit))
            git("config", "--local", "core.hooksPath", "/dev/null")
            git("checkout", "--detach", base_sha)
            git("merge", "--no-ff", "--no-edit", head_sha)
            _admit_entries(git("ls-tree", "-rz", "HEAD"))
            succeeded = True
        return output
    finally:
        if not succeeded:
            # 동일 UID의 경쟁 writer는 caller의 독점 job directory 계약 범위다.
            current = output.lstat()
            if stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                shutil.rmtree(output)


def main(argv: list[str] | None = None) -> int:
    """환경의 실제 run identity를 사용하고 실패 시 nonzero를 반환한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--is-private", required=True)
    args = parser.parse_args(argv)
    try:
        materialize_public_source(
            repository=args.repository, base_sha=args.base_sha, head_sha=args.head_sha,
            is_private=args.is_private, runner_temp=Path(os.environ.get("RUNNER_TEMP", "")),
            run_id=os.environ.get("GITHUB_RUN_ID", ""), run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        )
    except (MaterializationError, OSError):
        print("::error::Public review source materialization refused.")
        return 1
    print("Materialized exact public base/head without credentials or artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
