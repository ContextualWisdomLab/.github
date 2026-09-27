# CodeQL metadata job admission bound

On 2026-09-27, central Strix admission job108624881622 was queued with the
correct self-hosted/cwlab-control labels while all three control runners were
busy. Contextual-orchestrator CodeQL job108620193038 occupied cwlab-s2-01 in
`Read current-head CodeQL dispatch verdict`. This establishes a shared control
lane and live metadata work; it does not prove which individual API call stalled.

All three central codeql-pr jobs are API-only language detection, verdict reads,
or dispatch coordination, with no job execution bound. A stalled gh call can
therefore occupy a control slot for the platform default six hours. Add the
same five-minute operational bound used by Strix metadata to these three jobs.
The separately dispatched scan and model inference keep their own contracts;
no elapsed inference time becomes a model-failure verdict. A timed-out metadata
job remains non-passing and cannot authorize a merge.

The new assertion fails against unchanged source. The CodeQL and runner
contracts pass in local and GITHUB_ACTIONS=true modes (36 each); actionlint
and whitespace checks pass. Runner access, source-ref guards, permissions,
head revalidation, concurrency and authenticated verdict checks are unchanged.
Existing runs retain their original source and were not cancelled. Native
post-merge execution is needed to prove slot recovery and queue latency.
