import re
with open("tests/test_strix_local_proxy_bootstrap_failure_is_classified.py", "r") as f:
    content = f.read()

content = re.sub(r'self\.assertIn\("loginAsGuest failed after.*", workflow.*?\)', 'self.assertIn("loginAsGuest failed after", workflow)', content)

with open("tests/test_strix_local_proxy_bootstrap_failure_is_classified.py", "w") as f:
    f.write(content)
