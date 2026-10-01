# Maturin download response-lifecycle RCA

## Incident

Trusted uv Materializer run `36811202519`, job `110206427182`, checked out
`.github#1653@5cd141ec2c33b631d164af936cd1c9de70e4c9a4`. All 5,314 tests passed,
but the complete repository gate reported 99% coverage. The only incomplete
owner was `scripts/ci/verify_release_maturin_tool_assets.py`: five statements
and two branches in its non-200 and `HTTPError` response paths.

## Root cause and boundary

The bounded downloader belongs to the central `.github#2530` successor, not
the #1653 label-taxonomy delta. Its nullable `response` finalizer encoded a
false branch that cannot fall through: when `opener.open()` raises, control
re-raises from the `HTTPError` handler before the code following the finalizer.
That made honest 100% branch evidence impossible even though successful
responses were closed. The Trusted uv workflow path filter also omitted this
verifier and its tests, so fixing the canonical owner would not itself request
the complete gate that originally exposed the defect downstream. After the
path repair, owner head `8cf2ea5f73976d47b2267fb52ac28284323404b7`
still produced no gate because the workflow admitted only PRs whose base was
`main`, while #2530 is correctly stacked on canonical owner #2531.

## Repair

The downloader now closes every returned response in one unconditional nested
`finally` block. An opener-raised `HTTPError` remains independently closed by
its handler. Tests assert closure for both an HTTP 503 response and an HTTP 502
exception. The error fixture preserves the real `HTTPError.close()` and observes
its body closing; replacing the method with a spy had suppressed the actual
close and leaked pytest's temporary capture object until a later test, where
warnings-fatal execution correctly rejected the `ResourceWarning`. A workflow
contract now requires both verifier paths in pull-request
and protected-branch triggers, and a separate contract admits stacked PR bases
while the push trigger remains restricted to protected `main`. The repair does
not change admitted hosts, the one-hop redirect
contract, credentials, request timeout, byte bounds, digests, or error mapping.

Exact-tree verification then found that the verifier's archive extractor and
CLI entry point lacked docstrings even though the PR claimed complete
production docstring coverage. A RED regression now binds both symbols, the
two trust-boundary docstrings close the omission, and Trusted uv measures all
of `scripts/ci` instead of only the materializer module.

## Evidence and remaining gates

- Hosted RED: 5,314 passed, 5 skipped, 40 subtests; 18,775 statements with 5
  missing, 7,652 branches with 2 partial; total 99%.
- Local integrated GREEN: 18 lifecycle/prescreen tests; complete warnings-fatal
  suite 5,363 passed, 5 skipped, 40 subtests; 18,767/18,767 statements and
  7,648/7,648 branches; verifier 107/107 statements and 34/34 branches;
  production docstrings 1,456/1,456; `git diff --check` clean.
- Required before acceptance: complete exact-head hosted suite, security and
  CodeQL verdicts, qualifying independent approval, ordinary owner integration,
  then ordinary merge-forward into #1653 and fresh consumer Checks.
