with open(".github/workflows/strix.yml", "r") as f:
    content = f.read()
content = content.replace("loginAsGuest failed after [0-9]+ attempts: curl exit 7: curl: \\(7\\) Failed to connect to 127\\.0\\.0\\.1 port 48080", "loginAsGuest failed after [0-9]+ attempts: curl exit")
with open(".github/workflows/strix.yml", "w") as f:
    f.write(content)
