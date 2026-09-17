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
