import re

# 1. Path traversal fixes
files_to_update_path = {
    'scripts/ci/reconcile_repository_metadata.py': [
        (r'r"^[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/agent_mention_sweep.py': [
        (r'r"^[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"'),
        (r'r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$"', r'r"^ContextualWisdomLab/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/organization_commercial_readiness_loop.py': [
        (r'r"^[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/reconcile_repository_labels.py': [
        (r'r"^[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/review_admission_controller.py': [
        (r'r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$"', r'r"^ContextualWisdomLab/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/noema_review_handoff.py': [
        (r'r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$"', r'r"^ContextualWisdomLab/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/agent_mention_router.py': [
        (r'r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$"', r'r"^ContextualWisdomLab/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/pr_auto_rebase.py': [
        (r'r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/pr_review_autofix_context.py': [
        (r'r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/pr_review_fix_scheduler.py': [
        (r'r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/pr_review_merge_scheduler_core.py': [
        (r'r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/pingora_edge_policy.py': [
        (r'r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ],
    'scripts/ci/verify_exact_artifact_sbom_handoff.py': [
        (r'r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"', r'r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$"')
    ]
}

for file, replacements in files_to_update_path.items():
    with open(file, 'r') as f:
        content = f.read()
    for search, replace in replacements:
        content = content.replace(search, replace)
    with open(file, 'w') as f:
        f.write(content)

# 2. 502 Bad Gateway
with open('scripts/ci/strix_quick_gate.sh', 'r') as f:
    content = f.read()
content = content.replace(
    "grep -Eiq 'litellm(\\.exceptions)?\\.APIConnectionError' \"$STRIX_LOG\" &&\n\t\tgrep -Eiq '(GeminiException|Server disconnected without sending a response|LLM CONNECTION FAILED|Could not establish connection to the language model)' \"$STRIX_LOG\"",
    "grep -Eiq 'litellm(\\.exceptions)?\\.(APIConnectionError|APIError)' \"$STRIX_LOG\" &&\n\t\tgrep -Eiq '(GeminiException|Server disconnected without sending a response|LLM CONNECTION FAILED|Could not establish connection to the language model|bad gateway)' \"$STRIX_LOG\""
)
content = content.replace(
    "|internal server error)'",
    "|internal server error|bad gateway)'"
)
with open('scripts/ci/strix_quick_gate.sh', 'w') as f:
    f.write(content)

# 3. YAML fix
with open('.github/workflows/agent-review-runtime-quality-ci.yml', 'r') as f:
    lines = f.readlines()
new_lines = []
for idx, line in enumerate(lines):
    if "-r requirements-opencode-review-ci-hashes.txt" in line and "python -m pip install" in lines[idx-1]:
        if "Install exact review dependencies" in lines[idx-3] or "Install exact review dependencies" in lines[idx-2]:
            new_lines.append(line.replace("-r requirements-opencode-review-ci-hashes.txt", "-r requirements-opencode-review-ci-hashes.txt -r requirements-noema-document-ci-hashes.txt"))
            continue
    new_lines.append(line)
with open('.github/workflows/agent-review-runtime-quality-ci.yml', 'w') as f:
    f.writelines(new_lines)

with open('.github/workflows/opencode-review-dispatch.yml', 'r') as f:
    content = f.read()
content = content.replace(
    "-r /tmp/requirements-opencode-review-ci-hashes.txt \\",
    "-r /tmp/requirements-opencode-review-ci-hashes.txt -r /tmp/requirements-noema-document-ci-hashes.txt \\"
)
content = content.replace(
    "COPY requirements-opencode-review-ci-hashes.txt /tmp/requirements-opencode-review-ci-hashes.txt",
    "COPY requirements-opencode-review-ci-hashes.txt requirements-noema-document-ci-hashes.txt /tmp/"
)
content = content.replace(
    "&& rm -f /tmp/requirements-opencode-review-ci-hashes.txt",
    "&& rm -f /tmp/requirements-opencode-review-ci-hashes.txt /tmp/requirements-noema-document-ci-hashes.txt"
)
with open('.github/workflows/opencode-review-dispatch.yml', 'w') as f:
    f.write(content)

# 4. SHA updates
files_to_update_sha = {
    'tests/test_opencode_rust_coverage_toolchain_contract.py': [
        (r'f83861fb0b355da3ec83a6828b6d4b245ddabce2', r'8ef001721ff3f783fc690f9b031a2d4abde9a244')
    ],
    'tests/test_pr_review_autofix_nvidia_nim_contract.py': [
        (r'f83861fb0b355da3ec83a6828b6d4b245ddabce2', r'8ef001721ff3f783fc690f9b031a2d4abde9a244')
    ]
}
for file, replacements in files_to_update_sha.items():
    with open(file, 'r') as f:
        content = f.read()
    for search, replace in replacements:
        content = content.replace(search, replace)
    with open(file, 'w') as f:
        f.write(content)
