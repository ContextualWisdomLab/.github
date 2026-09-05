import re

with open("scripts/ci/noema_review_gate.py", "r") as f:
    code = f.read()

# remove the first fast path using loads since the tests are mocking json internals directly causing type error and recursion error.
# The previous solution I tried (only loads when within nesting bound) didn't work because it bypassed the catch for recursion error in tests.
code = code.replace(
'''    try:
        # Fast path for pure JSON payloads
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass''',
''
)

with open("scripts/ci/noema_review_gate.py", "w") as f:
    f.write(code)
