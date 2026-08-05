import re
import time

text = "This is a dummy text to simulate the performance optimization effect." * 100

start = time.monotonic()
for i in range(100000):
    pattern = re.compile(re.escape("performance"))
    match = pattern.finditer(text)
end = time.monotonic()

print(f"Uncached regex compile: {end - start:.5f}s")

pattern = re.compile(re.escape("performance"))
start = time.monotonic()
for i in range(100000):
    match = pattern.finditer(text)
end = time.monotonic()

print(f"Cached regex compile: {end - start:.5f}s")
