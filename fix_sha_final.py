import re

files_to_update_sha = {
    'tests/test_opencode_rust_coverage_toolchain_contract.py': [
        (r'8ef001721ff3f783fc690f9b031a2d4abde9a244', r'3a83766e02f60afb7022ed2acdde266962804f3d'),
        (r'fa9d42a7546d443e6e32929f729206c692853b8a', r'3a83766e02f60afb7022ed2acdde266962804f3d'),
        (r'f315683208d57ba89a2942502c525abe7355e2fd', r'3a83766e02f60afb7022ed2acdde266962804f3d')
    ],
    'tests/test_pr_review_autofix_nvidia_nim_contract.py': [
        (r'8ef001721ff3f783fc690f9b031a2d4abde9a244', r'3a83766e02f60afb7022ed2acdde266962804f3d'),
        (r'fa9d42a7546d443e6e32929f729206c692853b8a', r'3a83766e02f60afb7022ed2acdde266962804f3d'),
        (r'f315683208d57ba89a2942502c525abe7355e2fd', r'3a83766e02f60afb7022ed2acdde266962804f3d')
    ]
}

for file, replacements in files_to_update_sha.items():
    with open(file, 'r') as f:
        content = f.read()
    for search, replace in replacements:
        content = content.replace(search, replace)
    with open(file, 'w') as f:
        f.write(content)
