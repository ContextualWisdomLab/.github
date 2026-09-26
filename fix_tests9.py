import re
with open("tests/test_strix_local_proxy_bootstrap_failure_is_classified.py", "r") as f:
    content = f.read()

content = re.sub(r'self\.assertIn\("loginAsGuest failed after \[0-9\]\+ attempts: curl exit", workflow\)', 'self.assertIn("loginAsGuest failed after [0-9]+ attempts: curl exit", workflow.replace("\\\\.", ".").replace("[[::space::]]+", " "))', content)

with open("tests/test_strix_local_proxy_bootstrap_failure_is_classified.py", "w") as f:
    f.write(content)
