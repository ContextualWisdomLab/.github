import time
import timeit

def extract_model_prose_fast(raw_output: str) -> str:
    if "<!-- opencode-review-" not in raw_output:
        return "\n".join(raw_output.splitlines()).strip()
    return ""

def extract_model_prose_fast_optimized(raw_output: str) -> str:
    if "<!-- opencode-review-" not in raw_output:
        return raw_output.strip()
    return ""

text = "This is a simple text.\n" * 1000

print(timeit.timeit(lambda: extract_model_prose_fast(text), number=10000))
print(timeit.timeit(lambda: extract_model_prose_fast_optimized(text), number=10000))
