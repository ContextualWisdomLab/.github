export GITHUB_ACTIONS=true
export GH_TOKEN=fake_token
PYTHONPATH=$PWD python3 -m pytest tests/test_strix_rerun_job_selection.py
