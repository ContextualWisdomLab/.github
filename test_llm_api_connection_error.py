import re

log_content = """
2026-08-23T22:11:18.0163094Z │  LLM CONNECTION FAILED                                                       │
2026-08-23T22:11:18.0163972Z │                                                                              │
2026-08-23T22:11:18.0165159Z │  Could not establish connection to the language model.                       │
2026-08-23T22:11:18.0166232Z │  Please check your configuration and try again.                              │
2026-08-23T22:11:18.0167140Z │                                                                              │
2026-08-23T22:11:18.0168096Z │  Error: litellm.BadRequestError: LLM Provider NOT provided. Pass in the LLM  │
2026-08-23T22:11:18.0169184Z │  provider you are trying to call. You passed                                 │
2026-08-23T22:11:18.0170196Z │  model=openai-direct/gpt-5.6-luna                                            │
"""

if re.search(r'(?i)litellm(\.exceptions)?\.APIConnectionError', log_content) and re.search(r'(?i)(GeminiException|Server disconnected without sending a response|LLM CONNECTION FAILED|Could not establish connection to the language model)', log_content):
    print("Matched APIConnectionError")

if re.search(r'(?i)litellm(\.exceptions)?\.BadRequestError', log_content) and re.search(r'(?i)LLM Provider NOT provided', log_content):
    print("Matched BadRequestError: LLM Provider NOT provided")
