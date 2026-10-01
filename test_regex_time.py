import re
import timeit

def strip_jsonc_comments_orig(text: str) -> str:
    result: list[str] = []
    in_string = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if in_string:
            result.append(char)
            if char == "\\" and index + 1 < length:
                result.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            index += 2
            while index < length and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index + 1 < length and not (
                text[index] == "*" and text[index + 1] == "/"
            ):
                if text[index] in "\r\n":
                    result.append(text[index])
                index += 1
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)

def strip_jsonc_comments_re(text: str) -> str:
    pattern = re.compile(r'("(?:\\.|[^\\"])*")|(//[^\r\n]*|/\*.*?\*/)', re.DOTALL)
    def replacer(match):
        return match.group(1) or ("\n" * match.group(2).count("\n"))
    return pattern.sub(replacer, text)

with open('opencode.jsonc', 'r', encoding='utf-8') as f:
    text = f.read()

text = text * 1000

print(strip_jsonc_comments_orig(text) == strip_jsonc_comments_re(text))
print("Original:", timeit.timeit("strip_jsonc_comments_orig(text)", globals=globals(), number=10))
print("Regex:", timeit.timeit("strip_jsonc_comments_re(text)", globals=globals(), number=10))
