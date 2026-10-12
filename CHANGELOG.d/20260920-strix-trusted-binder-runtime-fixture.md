### Strix keeps trusted evidence binding outside consumer workspaces

- The executable Strix harness now pins the trusted binder owner: the gate must
  resolve `strix_evidence_binding.py` beside its trusted source, never from the
  consumer `STRIX_REPO_ROOT`, and the consumer fixture fails if it carries the
  binder.
- The commercial-readiness receipt contract now compares the complete parsed
  harden-runner endpoint set instead of treating an expected hostname as a URL
  substring. This closes the exact CodeQL
  `py/incomplete-url-substring-sanitization` finding without suppressing it or
  widening egress.
