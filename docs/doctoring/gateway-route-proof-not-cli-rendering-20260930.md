# Gateway route proof and CLI rendering

The executed route test introduced in `9c6d05374` correctly observes the
installed OpenCode CLI's request URL, but its negative case additionally
required `not found` to appear in CLI output before fixture cleanup. On a busy
host the expected `/chat/completions` request and gateway 404 occurred without
that display text. A full run therefore failed with 5,176 other tests passing,
while the same two CLI tests separately passed in 47.70 seconds.

The fixture intentionally stops the CLI after observing a request; that is
transport evidence, not a terminal CLI error-rendering receipt. No production
request timeout, provider retry, review verdict, or sanitizer is changed.

The repair records HTTP statuses only after the stub writes its response.
The real installed CLI must still request `/v1/chat/completions` for the shipped
configuration and `/chat/completions` for the bare-origin regression. Those
requests must respectively receive a sent 200 and 404 response. Delayed or
redacted CLI text is no longer confused with the network path. The stub retains
the pinned gateway's error body; this does not require production logs to expose
raw provider errors.

Before repair: the unchanged negative case failed at the display-text assertion.
After repair: both real CLI cases passed in 40.56 seconds. The complete suite
and current-head hosted evidence remain separate acceptance steps.

This is an inherited test-reliability repair, separated from the Noema
input-modality catalog change. It is not a security-finding exception or proof
that any provider HTTP 400 incident has been resolved.
