# Trusted review archive transient retry

## Incident

Bounded Noema continuation run
[`36760921156`](https://github.com/ContextualWisdomLab/.github/actions/runs/36760921156),
job `110043067331`, resolved the trusted workflow source to protected
`main@37b10243cec3d160ecc9c1be75c71428b160a703` and then failed before model
setup. The GitHub archive API returned HTTP 502 while the workflow executed a
single `curl -fsSL` request. The source revision, target pull request, and model
route were not the cause.

## Decision

The three central workflows that materialize the same immutable trusted archive
use `curl --retry 3 --retry-all-errors --retry-delay 1 --retry-max-time 30`.
This is a bounded transport repair at the canonical `.github` owner. It does
not select a mutable ref, bypass archive extraction checks, change credentials,
or convert a terminal failure into success.

## Alternatives

- Manual rerun was rejected because it would not repair the repeated control
  path.
- A custom retry helper was rejected because native `curl` already provides the
  bounded behavior and another abstraction would enlarge the trusted surface.
- An unbounded loop was rejected because it could occupy review capacity without
  a terminal result.

## Verification and remaining gate

`tests/test_trusted_archive_retry_behavior.py` runs the production command from
each workflow against a local server that returns one 502 followed by a 200.
The test was RED on the predecessor and GREEN after the bounded retry options.
Hosted exact-head Checks, unresolved-thread review, qualifying independent
approval, and ordinary protected merge remain required. A local GREEN result is
not merge authorization.
