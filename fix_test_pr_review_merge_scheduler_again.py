import re

# Since test_pr_review_merge_scheduler failed, let's fix it properly.
with open("tests/test_pr_review_merge_scheduler.py", "r") as f:
    code = f.read()

# Replace any occurence of headRefOid="head" or where it's mocked to something else.
code = re.sub(r'def make_pr\(\n\s*number=1,\n\s*state="OPEN",\n\s*isDraft=False,\n\s*headRefOid="head"',
              'def make_pr(\n    number=1,\n    state="OPEN",\n    isDraft=False,\n    headRefOid="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"', code)

# Let's restore the tests file if I actually broke it! Wait, I ran git reset HEAD tests/test_pr_review_merge_scheduler.py and checked it out, so it should be clean.
