import timeit

def extract_model_prose_old(raw_output: str) -> str:
    if "<!-- opencode-review-" not in raw_output:
        return "\n".join(raw_output.splitlines()).strip()
    return ""

def extract_model_prose_new(raw_output: str) -> str:
    if "<!-- opencode-review-" not in raw_output:
        return raw_output.replace('\r\n', '\n').replace('\r', '\n').strip()
    return ""

text1 = "line one\r\nline two\r\n\r\nline three\n"
print(repr(extract_model_prose_old(text1)))
print(repr(extract_model_prose_new(text1)))
print(extract_model_prose_old(text1) == extract_model_prose_new(text1))

print(timeit.timeit(lambda: extract_model_prose_old(text1 * 100), number=10000))
print(timeit.timeit(lambda: extract_model_prose_new(text1 * 100), number=10000))
