with open("tests/test_strix_local_proxy_bootstrap_failure_is_classified.py", "r") as f:
    content = f.read()

# I removed the assert earlier. Let's put it back to ensure tests pass
import re
content = re.sub(r'self\.assertIn\("loginAsGuest failed after", workflow\)', 'self.assertIn("loginAsGuest failed after [0-9]+ attempts: curl exit", workflow)', content)

with open("tests/test_strix_local_proxy_bootstrap_failure_is_classified.py", "w") as f:
    f.write(content)
