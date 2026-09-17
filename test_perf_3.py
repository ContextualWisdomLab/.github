import re
import timeit

ADVERSARIAL_BLOCK_RE = re.compile(
    r"<!--\s*opencode-adversarial-evidence-v1[\s\S]*?-->"
)

text = "This is a simple text.\n" * 1000

def original():
    for match in ADVERSARIAL_BLOCK_RE.finditer(text):
        pass

def optimized():
    if "opencode-adversarial-evidence-v1" not in text:
        return
    for match in ADVERSARIAL_BLOCK_RE.finditer(text):
        pass

print(timeit.timeit(original, number=10000))
print(timeit.timeit(optimized, number=10000))
