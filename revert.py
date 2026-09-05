import re

with open("scripts/ci/noema_review_gate.py", "r") as f:
    code = f.read()

# Let's revert back to original noema_review_gate.py for testing
