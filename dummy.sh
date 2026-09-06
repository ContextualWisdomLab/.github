export GITHUB_ACTIONS=true
export GH_TOKEN=fake_token
PYTHONPATH=$PWD python3 -m pytest tests/test_opencode_review_normalize_output.py
