#!/bin/bash
export REPO_ROOT="$(pwd)"

cat << 'LOG' > test_evidence.txt
## Failed check: Strix Security Scan / strix (28242573264 / 1)
LLM CONNECTION FAILED
Error: litellm.RateLimitError: RateLimitError: OpenAIException - Too many requests. For more on scraping GitHub and how it may affect your rights, please review our Terms of Service.
Configured model and fallback models were unavailable
LOG

bash -x ./scripts/ci/emit_opencode_failed_check_fallback_findings.sh test_evidence.txt
