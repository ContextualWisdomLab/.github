import subprocess
import os

print(os.path.exists("gh"))
print(subprocess.run(["gh", "version"]))
