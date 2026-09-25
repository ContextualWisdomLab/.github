import re

with open("scripts/ci/test_strix_quick_gate.sh", "r") as f:
    data = f.read()

data = re.sub(r'cp "\$REPO_ROOT/scripts/ci/strix_evidence_binding\.py" "\$repo_root_dir/scripts/ci/strix_evidence_binding\.py"\n(\s*cp "\$REPO_ROOT/scripts/ci/strix_evidence_binding\.py" "\$repo_root_dir/scripts/ci/strix_evidence_binding\.py"\n)*', 'cp "$REPO_ROOT/scripts/ci/strix_evidence_binding.py" "$repo_root_dir/scripts/ci/strix_evidence_binding.py"\n', data)

with open("scripts/ci/test_strix_quick_gate.sh", "w") as f:
    f.write(data)
