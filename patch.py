with open('scripts/ci/strix_quick_gate.sh', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)
    if "grep -Eiq 'litellm(\\.exceptions)?\\.APIConnectionError' \"$STRIX_LOG\" &&" in line:
        pass
    if "is_llm_api_connection_error() {" in line:
        new_lines.append("\tif grep -Eiq 'litellm(\\.exceptions)?\\.BadRequestError' \"$STRIX_LOG\" &&\n\t\tgrep -Eiq 'LLM Provider NOT provided' \"$STRIX_LOG\"; then\n\t\treturn 0\n\tfi\n\n")

with open('scripts/ci/strix_quick_gate.sh', 'w') as f:
    f.writelines(new_lines)
