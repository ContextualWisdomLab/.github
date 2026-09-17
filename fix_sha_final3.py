import re

files_to_update_sha = {
    'tests/test_opencode_rust_coverage_toolchain_contract.py': [
        (r'5b4305193ce8c8db21e8b1d5efaa2f4ba770d4dd', r'3a83766e02f60afb7022ed2acdde266962804f3d')
    ],
    'tests/test_pr_review_autofix_nvidia_nim_contract.py': [
        (r'5b4305193ce8c8db21e8b1d5efaa2f4ba770d4dd', r'3a83766e02f60afb7022ed2acdde266962804f3d')
    ]
}

for file, replacements in files_to_update_sha.items():
    with open(file, 'r') as f:
        content = f.read()
    for search, replace in replacements:
        content = content.replace(search, replace)
    with open(file, 'w') as f:
        f.write(content)
