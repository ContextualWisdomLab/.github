# Incident runbook: CWL automation control plane

Status: executable operator procedure for security, integrity, availability,
and protected-main acceptance incidents.

## Activate and classify

Open an incident when automation may have written the wrong ref, reused stale
evidence, bypassed an eligible review or ruleset, exposed a credential, lost
workflow provenance, affected multiple repositories, or repeatedly fails a
protected-main consumer path.

| Severity | Condition | Initial action |
|---|---|---|
| SEV-0 | confirmed unauthorized protected-ref/release mutation or active credential exfiltration | contain affected authority immediately; notify security owner |
| SEV-1 | credible cross-repository escape, forged approval/evidence, fleet-wide central failure | freeze affected mutation class; preserve read-only audit |
| SEV-2 | one repository/PR blocked or incorrectly classified with no unauthorized write | defer exact item; continue unrelated safe lanes |
| SEV-3 | documentation, telemetry, or non-blocking diagnostic defect | record bounded repair and owner |

## Record the incident identity

Capture before changing state:

- repository, PR, source ref/head, base branch, observed live-base SHA;
- workflow file/ref, run/job/attempt, event, actor, App/token class;
- check, status, review, thread, artifact, dispatch, and merge transaction ids;
- writer-lease holder and competing worker identity;
- first observed time, last known-good protected revision, and affected
  consumers;
- exact bounded error/command result after credential-safe transformation.

Do not copy raw authorization headers or suspected secrets into the incident.

## Contain

Choose the narrowest reversible containment:

1. Stop or disable only the affected mutation/credential path; keep read-only
   fleet audit and unaffected repositories running.
2. Cancel obsolete runs only when cancellation cannot remove newer valid
   evidence or cause a stale request to win.
3. Revoke or rotate only confirmed/credible affected credentials and App
   installations. Do not fall back automatically to a broader token.
4. Prevent merge/release/deploy while evidence identity or reviewer
   eligibility is uncertain. Never weaken the ruleset to clear the queue.
5. Preserve logs, workflow inputs, GitHub objects, and exact SHAs with bounded
   access and retention.

## Diagnose

Classify the first failing boundary, not the last visible symptom:

| Symptom | Questions | Safe next action |
|---|---|---|
| stale or wrong-head evidence | Which producer/head/base/run created it? Did either ref move? | invalidate predecessor evidence; re-run on the current tuple |
| unexpected write or merge | Who held the lease and credential? Did final head match? | freeze that authority, verify protected audit log, prepare reviewed revert |
| 401/403/ruleset denial | Is identity eligible and repository-scoped? | repair legitimate authority/configuration; no retry loop |
| API 5xx/rate limit/runner wait | Is it classified transient and within budget? | bounded retry, then defer exact item |
| provider timeout/exhaustion | Did deterministic gates pass? Is another configured provider within budget? | try distinct provider or defer; no synthetic approval |
| checksum/TLS/provenance failure | Which immutable input failed? | fail closed; repair source/pin/trust path |
| secret-shaped output | Was it published, retained, or sent externally? | restrict evidence, rotate affected credential, test expanded redaction fixture |
| central merge but consumer failure | Which protected-main workflow and target ran? | keep incident open; reproduce against real consumer boundary |
| no counted approval | Is reviewer independent, eligible, current, and formal? | wait for legitimate review; continue other work |

After three materially distinct failed remedies, reassess the architecture,
permissions, trigger, or dependency contract instead of repeating variants of
the same repair.

## Repair and verify

1. Add a realistic failing test or replay fixture for the incident identity.
2. Apply the narrowest fix on a branch based on the exact live protected tip.
3. Run focused tests, the full affected matrix, security/provenance gates,
   documentation contracts, and full repository checks.
4. Obtain an eligible independent review where policy requires it.
5. Merge with final exact-head protection.
6. Exercise the changed protected-main path in at least one enrolled real
   consumer and record target, run/job, source head, live base, conclusion, and
   recovery behavior.

An incident is not resolved because source merged or a model commented.

## Common recovery procedures

### Unauthorized or wrong revision mutation

Freeze the actor/credential, compare the protected ref and audit log to the
recorded expected head, preserve the unexpected revision, and prepare a normal
reviewed revert from the current protected tip. Re-run every gate and consumer
acceptance; do not rewrite protected history.

### Credential disclosure

Restrict/remove the published evidence through the platform's supported
mechanism, revoke or rotate the credential, inspect its audit scope from the
first exposure time, replace any derived credentials, add the exact output
shape as a synthetic fixture, and verify publication-boundary redaction.

### Stuck queue or provider outage

Record the exact deferred item and next trigger, stop redundant polling, and
continue other safe lanes. Resume only after a new head/base/review/check,
provider recovery, explicit authority change, or final sweep.

### Central workflow regression

Limit affected dispatches, identify the last known-good protected revision,
use a reviewed revert or explicit known-good caller pin, and validate one
representative consumer before restoring fleet-wide mutation.

## Closure and follow-up

Closure requires confirmed scope, root cause at the correct boundary, tests
that fail before and pass after the fix, credential/ruleset state verified,
protected-main consumer evidence, recovery/rollback exercised, threat-model and
ADR impact reviewed, and a durable issue/PR/run record. Any missing condition
keeps the incident in mitigated or monitoring state.
