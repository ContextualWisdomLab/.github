Line 368: `bash -c 'cd "$1" && python3 -m pip install --disable-pip-version-check coverage pytest >/dev/null && PYTHONPATH=. python3 -m coverage run -m pytest tests && python3 -m coverage report --show-missing' bash "$project_dir"`

Scorecard complains about `pip install --disable-pip-version-check coverage pytest >/dev/null` not being pinned by hash.
Wait, Seongho Bae's commit said:
"Scorecard Pinned-Dependencies (GHAS code-scanning alerts 84/85/86) flagged the bandit, pip-audit and semgrep installs as "pipCommand not pinned by hash". Replace the bare `pip install <pkg>==<ver>` (and the ineffective `--require-hashes=false`) with `pip install --require-hashes -r <lock>` against uv-generated, fully hash-pinned lockfiles..."

So I need to fix `pip install` in `.github/workflows/opencode-review.yml` by using `--require-hashes`!
BUT wait, in `opencode-review.yml` for `coverage-evidence`, it installs from the user's PR head `requirements.txt`!
`python3 -m pip install --disable-pip-version-check -r requirements.txt`
It's the user's PR head! How can we require hashes if the user didn't pin hashes?!
If we add `--require-hashes`, then PRs without hashes will fail coverage!
Wait, but what about `pip install --disable-pip-version-check coverage pytest >/dev/null`?
This installs `coverage` and `pytest` unpinned!
How can we pin them?
We can use a known locked file like `requirements-opencode-review-ci-hashes.txt`?
Actually, `tests/test_install_python_requirements_for_coverage.py` might be related! Wait, there is a script `scripts/ci/install_python_requirements_for_coverage.py`!
Is this script used instead of `pip install`?
