Wait, if `coverage-evidence` was skipping the checkout check because it didn't know it was an untrusted checkout?
In `scripts/ci/install_python_requirements_for_coverage.py`:
```python
def main(argv: list[str]) -> int:
    ...
```
I need to add `--require-hashes` to the `pip install` commands in `opencode-review.yml`.
But there's no hash file for `coverage` and `pytest`!
Wait, `tests/test_opencode_agent_contract.py` does NOT assert `pip install --disable-pip-version-check coverage pytest >/dev/null`.
But wait! If there is no hash file, where do I get the hashes?
I can just put the hashes inline in `opencode-review.yml`? No, Scorecard just checks if the command uses `-r <lockfile>` or `== <version>`.
Wait, Scorecard says:
"Replace the bare pip install <pkg>==<ver> with pip install --require-hashes -r <lock>"

Let's check `opencode-review.yml`:
```yaml
      - name: Install Python coverage measurement tools
        run: |
          pip install --disable-pip-version-check -r requirements-opencode-review-ci.txt >/dev/null
```
Wait, is `requirements-opencode-review-ci.txt` pinned?
Let's see: `cat requirements-opencode-review-ci.txt`
