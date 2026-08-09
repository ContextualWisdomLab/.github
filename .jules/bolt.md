
## 2026-08-09 - Exponential backoff for web E2E readiness polling
**Performance Problem:** The `sandboxed_web_e2e.py` script was hardcoded to wait for backend/frontend readiness by sleeping for a full second (`time.sleep(1)`) on every failed request. If a service came up in 10ms, the script would unnecessarily block for 1 second, causing significant execution delays in CI pipelines, especially when running numerous quick E2E sandbox tasks.
**Optimization:** Replaced the static `time.sleep(1)` with an exponential backoff algorithm. It starts with an initial delay of `0.1s` and doubles upon each failure, bounded by `min(1.0, delay * 2)`. This drastically speeds up test latency by returning almost instantly when a service initializes quickly.
