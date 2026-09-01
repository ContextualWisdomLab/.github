"""One-shot repair for PR #1629 strict central free-pool entrypoints."""

from __future__ import annotations

from pathlib import Path

LAUNCHER = Path("scripts/ci/contextual_orchestrator_review_launcher.py")
SIDECAR = Path("scripts/ci/contextual_orchestrator_review_sidecar.sh")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    """Replace exactly one expected fragment and fail closed on source drift."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    """Restrict both central review entrypoints to orchestrator/free only."""
    replace_once(
        LAUNCHER,
        '    parser.add_argument("--pool", choices=("free", "auto"), default="free")\n',
        '    parser.add_argument("--pool", choices=("free",), default="free")\n',
        "launcher free-only parser",
    )
    replace_once(
        SIDECAR,
        '''orchestrator_pool="${CONTEXTUAL_ORCHESTRATOR_POOL:-free}"
case "$orchestrator_pool" in
  free|auto)
    pool_args=(--pool "$orchestrator_pool")
    ;;
  *)
    fail "CONTEXTUAL_ORCHESTRATOR_POOL must be free or auto"
    ;;
esac
''',
        '''orchestrator_pool="${CONTEXTUAL_ORCHESTRATOR_POOL:-free}"
if [ "$orchestrator_pool" != "free" ]; then
  fail "CONTEXTUAL_ORCHESTRATOR_POOL must be free"
fi
pool_args=(--pool "free")
''',
        "sidecar free-only pool",
    )


if __name__ == "__main__":
    main()
