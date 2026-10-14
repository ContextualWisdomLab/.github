import re

with open("scripts/ci/agent_mention_sweep.py", "r") as f:
    content = f.read()

# find where live_pull is
new_content = content.replace(
"""    comments = list_recent_comments(
        client,
        repository=repository,
        pull_request_number=number,
        since=since,
    )
    live_pull = client.request([f"repos/{repository}/pulls/{number}"])""",
"""    comments = list_recent_comments(
        client,
        repository=repository,
        pull_request_number=number,
        since=since,
    )
    if not comments:
        # Performance optimization: Skip the live pull request API fetch if there
        # are no recent comments to process. This eliminates a redundant network
        # request when a PR was updated (e.g. by a push) without new comments.
        return ()
    live_pull = client.request([f"repos/{repository}/pulls/{number}"])"""
)

with open("scripts/ci/agent_mention_sweep.py", "w") as f:
    f.write(new_content)
