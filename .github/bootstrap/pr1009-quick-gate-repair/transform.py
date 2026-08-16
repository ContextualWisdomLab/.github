"""Remove stale reviewer-coupled Strix assertions from the central quick gate."""

from pathlib import Path


PATH = Path("scripts/ci/test_strix_quick_gate.sh")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact block and fail closed if the branch has drifted."""
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one old block, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    """Keep Strix evidence tests on their owning workflow and collector."""
    text = PATH.read_text(encoding="utf-8")
    old_first = '''\tassert_file_contains "$workflow_file" 'current_head_manual_strix_success_status()' "opencode approval can identify same-head manual Strix success status evidence"
\tassert_file_not_contains "$workflow_file" 'manual_run_line="$(latest_current_head_manual_strix_run || true)"' "opencode approval must not treat an unbound manual Strix run as successful evidence"
\tassert_file_contains "$workflow_file" 'filter_superseded_strix_failures()' "opencode approval filters only explicitly superseded stale Strix failures"
\tassert_file_contains "$workflow_file" '"- Strix Security Scan/"*|"- strix:"*' "opencode approval filters stale Strix workflow helper checks after newer manual evidence"
\tassert_file_contains "$workflow_file" 'Default-branch repository_dispatch Strix structured evidence binding passed' "opencode approval requires an explicit structured manual Strix evidence status description"
'''
    new_first = '''\t# Manual Strix evidence is owned by the Strix workflow and failed-check collector,
\t# not by the immutable independent reviewer. Focused assertions below bind those
\t# two boundaries to artifact, head, status-description, and supersession rules.
'''
    text = replace_once(text, old_first, new_first, "manual evidence ownership block")

    old_second = '''\tassert_file_contains "$workflow_file" "A successful same-head default-branch repository_dispatch Strix run with the exact structured evidence-binding status may supersede a stale failed PR statusCheckRollup Strix context only when failed-check evidence explicitly lists it under Superseded failed checks with the exact target URL" "opencode review prompt allows only exact structured same-head Strix evidence to supersede stale rollup failures"
\tassert_file_contains "$workflow_file" "current_head_manual_strix_structured_success_status" "opencode approval gate treats only structured same-head Strix status as stale Strix failure superseder"
\tassert_file_not_contains "$workflow_file" "current_head_successful_strix_check_run" "opencode approval must not supersede failures from an unbound generic successful check run"
'''
    new_second = '''\t# Do not couple Strix post-merge evidence semantics to the read-only reviewer.
\t# The collector assertions immediately below require explicit structured binding,
\t# exact-head artifact download, and an enumerated superseded-failure section.
'''
    text = replace_once(text, old_second, new_second, "structured supersession ownership block")
    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
