## 2024-05-24 - Overriding Vulnerable dependencies for Python Lock File
**Vulnerability:** `anyio` v4.14.0 contains three known security vulnerabilities (CVE-2026-63374, CVE-2026-64847, CVE-2026-63349) affecting `pip-audit` checks in CI.
**Learning:** `requirements-strix-ci.txt` implicitly installs `anyio`, making it hard to pin directly inside `requirements-strix-ci.txt` without bloating it with unrelated dependency pins. Instead, to remediate this during `uv pip compile` lock file generation, the override file `requirements-strix-ci-overrides.txt` can be used to inject the `anyio==4.14.2` update securely.
**Prevention:** Always bump insecure dependencies reported by `pip-audit` using the `.txt`-overrides file specifically for overriding hashes before they propagate and fail CI runs.

## 2024-05-24 - Expected CI CodeQL dispatch flakes
**Vulnerability:** Not a codebase vulnerability; CodeQL dispatch workflows occasionally exit 1.
**Learning:** The pipeline logs note: `CodeQL scan dispatched. The dispatch workflow will rerun this exact failed CodeQL job after publishing its terminal verdict.` This failure (`pending` state) simply means the gate dispatched the scan and intentionally exits early so an external job can run. It is not a code regression.
**Prevention:** Acknowledge this failure mode and wait for external retries. Do not attempt to fix non-existent code issues when this known transient infrastructure pattern occurs.
