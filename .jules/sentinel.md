## 2024-06-20 - Prevent HTML Comment Breakout in JSON Serialization
**Vulnerability:** Markdown Injection / HTML Comment Breakout
**Learning:** JSON serialized into HTML comments (like `<!-- json -->`) can contain `-->` in string values, causing GitHub's Markdown parser to close the comment prematurely and render the remaining JSON as attacker-controlled text or Markdown.
**Prevention:** Always escape `<` and `>` as `\u003c` and `\u003e` (and `&` as `\u0026`) when embedding JSON in HTML contexts (even Markdown comments) to prevent breakout.
## 2024-06-25 - Force Python JSON Normalizer to Prevent CI Gate Bypass
**Vulnerability:** Workflow CI Security Bypass / Markdown Injection
**Learning:** The GitHub Actions workflow `opencode-review.yml` attempted to optimize performance by doing a fast-path bash string extraction. If this succeeded, it skipped the Python JSON normalizer (`opencode_review_normalize_output.py`). This is a security flaw because the bash script does not escape `<, >, &` characters, allowing attackers to inject `-->` directly in JSON strings to break out of HTML comment sections.
**Prevention:** Removed the fast-path check entirely. We must always enforce JSON normalization via `opencode_review_normalize_output.py` because it correctly parses the JSON payload and safely escapes all characters as `\u003c`, `\u003e` and `\u0026`.
## 2026-06-28 - Align Sensitive Log Redaction Across Languages
**Vulnerability:** Information Disclosure / Secret Leakage
**Learning:** The Bash CI script (`collect_failed_check_evidence.sh`) aggressively redacted a broad range of secrets like AWS keys, Slack tokens, and generic API keys. However, the Python PR review scheduler script (`pr_review_merge_scheduler.py`) only redacted a very narrow set of standard GitHub tokens (`ghp_` and `github_pat_`). This disparity left the Python-driven command logs vulnerable to exposing other high-value secrets on command failure if they were passed via environment or arguments and inadvertently caught in error tracebacks.
**Prevention:** We must maintain parity between cross-language redaction strategies that operate on CI environments. Replicated the extensive regular expressions for secrets (e.g., Slack, AWS, password combinations, all GitHub token prefixes) to the Python error handler.
## 2026-06-25 - Prevent CI Logs Security Exposure and Explicit Shell Usage
**Vulnerability:** Information Disclosure / Command Injection
**Learning:** `subprocess.run` defaults to `shell=False`, but linters like Bandit require explicit `shell=False` to pass security checks. Furthermore, failing GitHub CLI commands or curl requests can include full command arguments and stderr in raised errors. These strings can contain GitHub PATs, Bearer/token authorizations, API keys, or specialized GitHub token prefixes such as `gho_`, `ghu_`, `ghs_`, and `ghr_`.
**Prevention:** Always explicitly define `shell=False` when using `subprocess.run()`. Scrub sensitive tokens from both command arguments and `stderr` before including them in exceptions or logs from CI scripts, including the `gh[pousr]_` prefix family and `github_pat_`.
## 2026-06-30 - Prevent Security Theater in Subprocess Fixes
**Vulnerability:** Command Injection / Incomplete Fix
**Learning:** Fixing a `shell=True` vulnerability by replacing it with `shell=False` and wrapping the command string in `["/bin/bash", "-c", command]` is security theater. If `command` contains untrusted input, passing it to `bash -c` as a single string means it is still completely vulnerable to shell injection, while misleading linters into reporting the code as secure.
**Prevention:** When refactoring away from `shell=True`, avoid invoking shells entirely. Use `shlex.split(command)` to safely parse the string into a list of arguments and pass that list directly to `subprocess.Popen` or `subprocess.run`, ensuring untrusted input is never evaluated by a shell.
## 2026-06-30 - Prevent SSRF and Local File Inclusion via Unvalidated URL Schemes
**Vulnerability:** Server-Side Request Forgery (SSRF) / Local File Inclusion
**Learning:** Functions that fetch URLs provided via user inputs (e.g., `wait_for_url` fetching `--backend-ready-url` in CI scripts) can inadvertently read local files if they do not validate the scheme. Python's `urllib.request.urlopen` supports `file://` schemes, allowing attackers to access arbitrary file contents from the host machine or sandbox if they can control the URL parameter.
**Prevention:** Always validate URL inputs to restrict allowed schemes. Check that URLs explicitly start with `http://` or `https://` before fetching them with standard libraries like `urllib`.
## 2026-07-03 - Prevent SSRF via URL Scheme Validation
**Vulnerability:** Server-Side Request Forgery (SSRF) / Local File Inclusion
**Learning:** External URL fetching with `urllib.request.urlopen` (like API endpoints passed via environment variables) can accept schemes like `file://` implicitly, which could allow arbitrary file reading or internal network scanning if the environment is misconfigured or manipulated.
**Prevention:** Always validate that URLs explicitly start with `http://` or `https://` before using them in standard library requests. Append  to suppress linter warnings only after verifying the input is validated.
## 2026-07-09 - Prevent SSRF via Redirects in urllib

**Vulnerability:** Initial URL validation for SSRF (e.g., checking scheme and IP address) is insufficient if the HTTP client automatically follows redirects. In `urllib.request.urlopen`, redirects are followed by default, allowing an attacker to bypass initial checks by returning a 302 redirect to an internal IP (like `169.254.169.254` or `127.0.0.1`).
**Learning:** `urllib.request.urlopen` does not inherit the security properties of the initial URL string check. It will follow HTTP redirects unconditionally to any target URL, creating a severe SSRF risk when dealing with external API endpoints that can be manipulated by malicious responses.
**Prevention:** Explicitly disable redirects by subclassing `urllib.request.HTTPRedirectHandler`, overriding `redirect_request` to raise an `urllib.error.HTTPError`, and using `urllib.request.build_opener(NoRedirectHandler())` instead of the default `urlopen`.
## 2026-07-13 - Complete the Fix for Command Injection Security Theater
**Vulnerability:** Command Injection
**Learning:** Fixing a `shell=True` vulnerability by replacing it with `shell=False` and wrapping the command string in `["/bin/bash", "-lc", command]` is incomplete and still leaves the code vulnerable to shell injection. It acts as security theater, as it misleads linters while executing untrusted input via the bash wrapper. The vulnerability was still present in `sandboxed_web_e2e.py`.
**Prevention:** Remove `/bin/bash` wrapper from `subprocess` calls in CI scripts. Always use `shlex.split(command)` to safely parse strings into a list of arguments and pass the list directly to `subprocess.Popen` or `subprocess.run`.
## 2026-08-24 - SSRF Vulnerability in sandboxed_web_e2e.py
**Vulnerability:** The `wait_for_url` function in `scripts/ci/sandboxed_web_e2e.py` did not validate the URL hostname before making requests, creating a Server-Side Request Forgery (SSRF) risk.
**Learning:** Arbitrary URLs passed to internal utilities must be rigorously validated, especially in CI environments, to ensure they do not access unintended network locations or internal services.
**Prevention:** Always use `urllib.parse.urlparse` to validate that the parsed URL hostname is restricted to safe loopback addresses (e.g., `localhost` or `127.0.0.1`) before opening the URL, particularly for sandbox or internal healthcheck endpoints.
## 2026-08-24 - Classify Strix Text-Only Turn as ModelBehaviorError
**Vulnerability:** Unreliable LLM Fallback Mechanism
**Learning:** If the agent fails to call the `finish_scan` tool and instead emits a plain-text turn, the Strix workflow fails. If this failure isn't mapped to `ModelBehaviorError`, the CI system treats it as a hard CI failure rather than falling back to alternative models.
**Prevention:** Include `ended without calling finish_scan` in the regex for `ModelBehaviorError` in `.github/workflows/strix.yml` and `scripts/ci/strix_quick_gate.sh` so that the pipeline can gracefully fall back to a stronger model.
## 2026-08-24 - Explicit shell=False in Subprocess Calls
**Vulnerability:** Subprocess Command Injection
**Learning:** Even when using `shlex.split()` to separate command arguments, if `shell=False` is not explicitly defined in `subprocess.Popen` and `subprocess.run` calls, security scanners like Bandit and Strix may flag the code as vulnerable to command injection.
**Prevention:** Always explicitly define `shell=False` when invoking `subprocess.Popen` or `subprocess.run` with untrusted commands, even when pre-processing with `shlex.split()`, to ensure robust safety and satisfy strict security linting.
