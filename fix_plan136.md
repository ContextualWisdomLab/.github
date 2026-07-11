Yes! `uv` is installed, because it runs `uv sync` right before it!
Wait! Does `install_python_project_dependencies()` run `uv pip install` if `uv` is available?
Yes! "Install Python coverage measurement tools" installs `uv`:
```yaml
      - name: Install Python coverage measurement tools
        run: |
          set -euo pipefail
          python3 -m venv .venv
          echo "${GITHUB_WORKSPACE}/.venv/bin" >> "$GITHUB_PATH"
          export PATH="${GITHUB_WORKSPACE}/.venv/bin:$PATH"
          pip install --disable-pip-version-check -r requirements-opencode-review-ci.txt >/dev/null
```
So `uv` IS installed globally in the virtual environment!
So I can replace `python3 -m pip install` with `uv pip install --system`!
Wait, if it's in a virtual environment, `uv pip install` works automatically.
So I can change:
`python3 -m pip install --disable-pip-version-check -r requirements.txt`
to:
`uv pip install -r requirements.txt`

Let's do this in `opencode-review.yml` for lines 288, 309, 368, and 372!
