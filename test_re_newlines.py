import re
text = "{\n  // leading note\n  \"a\": 1, /* inline block\n  spanning lines */ \"b\": 2\n}\n"
pattern = re.compile(r'("(?:\\.|[^\\"])*")|(//[^\r\n]*|/\*.*?\*/)', re.DOTALL)
def replacer(match):
    return match.group(1) or ("\n" * match.group(2).count("\n"))
print(pattern.sub(replacer, text))
