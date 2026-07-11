If I just remove `actions: write` and `contents: write` from `opencode-review-target` job, will tests fail?
Let's see: `tests/test_opencode_agent_contract.py`
Does it assert permissions for `opencode-review-target`?
