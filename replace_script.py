import re

with open("scripts/ci/opencode_review_normalize_output.py", "r") as f:
    code = f.read()

# I will revert the change for opencode_review_normalize_output.py that I made as it seems to be failing CI due to something unrelated and the tests passing locally shows it wasn't the cause of the failure. No wait, the tests did fail, there is a `SyntaxError: unterminated string literal`.
# Wait, let me just fix the syntax error! I wrote:
#         while next_index < len(text) and text[next_index] in " \t\r\n":
# Python doesn't allow raw strings to have actual newlines in a replace script unless properly escaped, but the original text had `in " \t\r\n":`. I used a standard string replacement that got messed up in `cat` maybe.
# Oh, the failure in CI is in the actual CI job which didn't run my local tests! The failure is `opencode-review`. That runs an actual workflow which might be hitting my code change in noema_review_gate.py. Wait, no, the check run failed because the output of the workflow is: `No APPROVED or CHANGES_REQUESTED from opencode-agent on the current head.`
