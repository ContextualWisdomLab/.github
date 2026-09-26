# ADR-0029: Review sidecar preflight fills the served set lazily to a readiness target

- **Status:** Proposed
- **Date:** 2026-09-06
- **Scope:** `scripts/ci/contextual_orchestrator_review_launcher.py` (`_preflight_review_agents`, the stage limits), `scripts/ci/contextual_orchestrator_review_sidecar.sh` (`ORCHESTRATOR_CATALOG_LIMIT` default), ADR-0003 §2's stage budget sentence
- **Amends:** ADR-0003 (the "twelve-route startup budget" clause). ADR-0005's attempt counts are historical and are not restored.

## Problem

The review sidecar selected a fixed catalog of twelve routes and probed every one of them, then served whatever was ready. `.github#1939` made the selection diverse (round-robin across credential accounts inside each cost/ZDR tier, four routes per account), which was right, but it exposed a second defect: the per-account slice is filled from an alphabetically sorted model list, and for both NVIDIA NIM keys the first four models are `deepseek-v4-flash`, `deepseek-v4-pro`, `gemma-3-12b`, `gemma-3-4b`. NIM lists the two `gemma-3` models but answers `404` to every chat request on every run observed. Each NVIDIA key therefore served two working routes, both the most contended models, while the pre-#1939 eight-slot fill had reached `meta/llama-3.2-11b`, `llama-3.2-90b` and `meta/muse-glimmer-30b`, which were ready in every Strix artifact of that afternoon.

Measured on `ContextualWisdomLab/.github` (lane jan's census on `#1948`, verdict-step conclusions only, draft skips excluded):

| window | preflight ready of 12 | `noema-review` success / failure |
|---|---|---|
| before `#1939` (`main@f2f91b80`, 2026-09-05T17:25Z) | 6, 6, 5 (16:37–16:56Z artifacts) | 7 / 14 |
| after | 1–3 (23:47Z onward) | 0 / 22 |

The evening's rate-limit pressure is a confound; the mechanism is not. A fixed slice from a list with dead entries wastes the slice, and probing every candidate regardless of how many are already ready spends per-key rate budget (`#1948`) for nothing.

## Constraints

1. No model name is hard-coded anywhere in the fill; a dead candidate is discovered by its probe, not by a list.
2. Probe spend per sidecar boot stays bounded and is stated as a number, because the probes themselves consume the per-key budgets the served routes need (`#1948`).
3. `#1947`'s deferral (a probed route that answered a transient status is kept behind the ready routes) applies unchanged to whatever was probed.
4. ADR-0003's evidence-triggered priced fallback (only after every free candidate rejects) keeps its shape; the two stages still share one startup budget.
5. `ready_count` keeps its meaning (routes proven ready by a probe) so the peers' post-merge discriminators stay comparable.

## Decision

The catalog is a **candidate list**, not the served set. `build_zdr_prioritized_catalog` keeps its tier-then-round-robin order (`#1939`) and is asked for up to `REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES = 24` candidates (per-account cap unchanged at 8; the sidecar's `ORCHESTRATOR_CATALOG_LIMIT` default rises from 12 to 24). `_preflight_review_agents` probes candidates **in that order and stops** as soon as `REVIEW_PREFLIGHT_TARGET_READY = 8` routes are ready or `REVIEW_PREFLIGHT_MAX_PROBES = 16` probes have been spent, whichever comes first. The auto pool's split becomes 16 free candidates and up to 8 priced fallback candidates; the production `free` pool (the sidecar default; it has no fallback stage) lists all 24. A silent candidate's probe costs up to one transport timeout (one artifact spent 805 s on 19 probes), so the probe cap bounds preflight wall time as well as request count.

**Account skip.** *(The "skipped without a probe" and "two probes per account" claims in this paragraph are superseded by the 2026-09-06 amendment below: such a candidate is postponed, and the leftover budget is spent on it.)* A 429 at preflight is a per-key answer, not a per-model one. Once one credential account has answered 429 to `REVIEW_PREFLIGHT_ACCOUNT_SKIP_AFTER_429 = 2` consecutive probes, its remaining candidates are skipped without a probe and the walk continues with the other accounts' next candidates; the two probed routes are still deferred. Under the real 2026-09-06 candidate order (lane jan's table on `#1949`, rebuilt from `#1938`'s Strix artifact: both NVIDIA keys list deepseek ×2, gemma-3 ×2 (404), gemma-4-31b (empty), then the llama and muse routes; every OpenRouter free route answers 429) the plain sixteen-probe walk yields about five ready and five deferred and the readiness target is unreachable, because five probes go to an account whose every route had answered 429 in every artifact since 21:00Z and four to the dead gemma-3 entries. With the skip, the same sixteen probes reach both keys' `llama-3.2` routes and the target of eight. This is why the free pool lists 24 candidates while probing at most 16: the tail is reachable exactly when an account is skipped, and the report separates `skipped_count` from the unreached remainder (`candidate_count − probed_count − skipped_count`). A rate-limited hour therefore costs two probes per account instead of the full budget.

The sidecar's job-log echo of the preflight JSON (`sed -n '1,400p'`, previously 160 lines) now fits 16 probed routes; the artifact copy was always complete.

The report gains `candidate_count`, `target_ready` and `probe_budget`; `probed_count` now counts probes actually sent, and `rejected_count` is `probed − ready − deferred`. Unprobed candidates get no `routes` row.

## Consequences

- **Good:** a dead candidate costs one probe and yields its place to the next candidate in the same account's list; a healthy hour stops after about eight to twelve probes instead of always twelve; a bad hour is bounded at sixteen probes per stage.
- **Cost:** in an hour where nothing is ready the sidecar sends up to 16 probes per stage where it sent 12, a third more against already exhausted keys. This is the price of finding routes past the dead ones; `#1948`'s shared rate ledger is the lever above it. The cap is also a wall-time bound: a 16-token probe can hold the full 90 s receive timeout (`#1661` run 34008191123, 04:48Z, both NVIDIA keys' deepseek-v4-pro probes at 90.06 s and 90.10 s), so a fully silent hour costs at most 16 × 90 s = 24 minutes of preflight against 18 today, and the account-skip rule cuts a rate-limited hour to two probes per account. *(That last clause is superseded by the 2026-09-06 amendment: a rate-limited hour now spends the whole probe budget rather than two probes per account.)*
- **Unchanged:** a route that answers the probe and then goes silent at request time still costs the gateway's full retry budget (`contextual-orchestrator#1045`); readiness is measured at 16 tokens (`#1454`).
- **Discriminator:** post-merge, `probed_count` versus `candidate_count` per boot and `ready_count` of the served set, read from the `runtime preflight summary` in the job log or the `noema-sidecar-evidence` artifact, compared with the table above.

## Alternatives considered

- **Raise the per-account cap back to 8 with a 12-route limit** — restores the pre-#1939 pool but reintroduces the single-account fill that `#1939` fixed; the 404s would still occupy slots.
- **Exclude models that 404 by name** — a hard-coded exclusion list the next discovery change silently invalidates; rejected by constraint 1. The discovery-side question (why NIM lists models it does not serve) remains open in `contextual-orchestrator`.
- **Family-level interleave inside each account's list before the cap** (jan's second layer) — would make each NVIDIA key's first six candidates span deepseek, gemma, llama, muse, minimax, mistral, but it needs a model-family equivalence derived from names, which ADR-0003/#1468 deliberately avoid; kept in reserve if the post-merge census shows same-family contention as the residual after the account skip.
- **Probe all 24 candidates** — best served set, double the probe spend in the hour that can least afford it; rejected by constraint 2.

## Amendment 2026-09-06: a set-aside candidate is postponed, not banned

**Evidence.** Sixteen sidecar artifacts were collected on 2026-09-06 across `.github`, `argos`, `bandscope` and `naruon`; **fourteen** ran the merged rule (two, `argos` 34013128112 and `bandscope` 34013146167, still carry the pre-`#1949` report shape and are excluded). The fourteen fall into three classes, not two.

| class | boots | `probed / skipped / ready` | second pass? | outcome |
|---|---|---|---|---|
| budget spent in the first pass | 8 | 16 / 4 / 5–6 | no — budget already gone | served; the sixth ready route (`llama-3.2-11b` on the second NVIDIA key, catalog position 17, ready in exactly these 8 artifacts) is reached **only** because four OpenRouter probes were set aside — the benefit the rule was designed for |
| candidates exhausted, budget left | 1 | 12 / 12 / 3 (`argos` 34014143870, 06:56Z) | **yes**, up to 4 probes | served with 5 deferred, but the target of 8 was unmet with 4 probes unspent |
| every account set aside | 5 | 6 / 18 / 0 (`rejected 6`, all 429) | **yes**, up to 10 probes | preflight failed closed |

So the change is not confined to bursts: one served, ordinary-minute boot also ends its first pass under target with budget in hand. Only a boot that spends all sixteen probes in the first pass is untouched.

The sidecar stderr of `.github` run 34016207820 shows its six probes (both NVIDIA keys' two deepseek routes, two OpenRouter routes) refused 429 between 07:49:35.111Z and 07:49:35.767Z. Because the walk is a round-robin across three accounts, "two consecutive 429s" on one account is two requests about **310 ms** apart (`nvidia_nim` at .111 and .422), not two probes a tenth of a second apart. The rule set all three accounts aside, the walk ended **with ten of its sixteen probes unspent**, and because deferral requires one ready route (`#1947`) nothing was served either. The five boots of that class span 07:24:50Z to 08:04:41Z.

A refusal is not a verdict on the account. Run 34016093772 was inside its *own* preflight while that burst happened (its probes run from 07:46:21Z), and its `llama-3.2-11b` probes on the **same two NVIDIA keys** answered ready at 07:50:58.7Z and 07:50:59.0Z — 84 seconds after those keys refused 429 at 07:49:35Z. That boot ended `probed 16 / ready 5`.

What is **not** measured: whether the ten unspent probes would have found a ready route *inside* the burst itself. No artifact answers it, because nothing records how long a refusal lasts — hence `retry_after_s` below. The pre-`#1949` walk failed similar windows for a different reason (`.github` runs 34006939646 / 34008191123 / 34008575125, 04:24–05:11Z: the same six 429s, then six gemma 404s, `ready 0` at `probed 12`), so the ban is not a regression this amendment invents; it is the ban meeting a 24-candidate list whose tail it can no longer reach.

**Decision.** A candidate set aside by the account rule is appended to a postponed list in catalog order. Once the first pass ends with the readiness target unmet and probe budget left, the postponed candidates are probed in that order until the budget is spent; no account rule applies in that second pass. A boot that spends all sixteen probes in the first pass is unchanged; the other two classes above gain a second pass. The justification is not that the second pass rescues a burst — that is unmeasured — but that ending a walk under target with probe budget in hand is indefensible when the catalog's tail is where the ready routes live. Constraint 2 holds unchanged: at most sixteen probes per stage, and a silent second-pass probe is bounded by that count, not by a clock (ADR-0003 admits no time rule here).

**Cost.** The second pass spends probes the walk used to abandon, so it lengthens the boot it rescues and the boot it does not. A refused probe costs about 120 ms. A **silent** one costs up to the full 90 s receive timeout (`#1661` run 34008191123, both NVIDIA keys' `deepseek-v4-pro` probes at 90.06 s and 90.10 s), and the postponed tail is full of them: `google/gemma-4-31b-it` answered `TimeoutError` in 15 of the 19 probes that reached it across these artifacts. The measured burst is therefore not a 1.2-second case — replaying 34016207820's catalog, its second pass would reach both `gemma-4-31b-it` entries, so about 3 minutes — and the worst case is 10 × 90 s ≈ **15 minutes** added to a boot that will still fail, taking a dead window from about 4 minutes to about 19 and holding the runner slot for it.

**The two-stage path costs more than the free pool's figure.** Whenever a stage lists no more candidates than the probe budget — which is exactly the auto split, 16 free primary and 8 priced fallback — the account rule now saves nothing there, because the second pass re-probes everything it set aside. Measured on a two-account, all-429 auto run: `origin/main` sends 8 requests (4 primary, 4 priced), this design sends 24 (16 primary, 8 priced). The priced stage spends paid credit, so it doubles from 4 probes to 8 in a rate-limited hour. That is accepted for the same reason as the free pool — the priced stage only runs after every free route rejected, and stopping it half-probed is the same defect one layer down — but it is a real, stated cost, not a side effect.

Two things are deliberately **not** traded away. The second pass never draws on the shared escalation budget (`REVIEW_PREFLIGHT_MAX_ESCALATIONS`, one counter for the whole run, carried into the priced stage by `#1458`): a postponed candidate that answers with the budget-too-small signature is rejected as `escalation_reserved_for_first_pass` rather than escalating, because otherwise candidates the previous design never probed would take escalations from the priced stage that had them, and a two-stage run measurably stops serving a route it used to serve.

That competes directly with the org's 60-job ceiling work, and `#1949`'s measured benefit ("a dead window fails closed in about 4 minutes and returns the slot") is partly traded back for the chance to reach the catalog tail. It stays inside the probe budget this ADR bounds, `postponed_probed_count` plus the provisioning step's duration make the trade visible per boot, and `REVIEW_PREFLIGHT_MAX_PROBES` is the lever if the census says the exchange is bad.

The report adds `postponed_probed_count`; `skipped_count` now means "postponed and never reached", and `candidate_count − probed_count − skipped_count` keeps its meaning. A refused probe additionally records `retry_after_s` when the response carried a whole-seconds `Retry-After` header (the HTTP-date form and out-of-range values record nothing). Nothing waits on that value; it exists so the next census can answer the question this amendment could not.

**Discriminator.** `postponed_probed_count > 0` marks any boot that reached a second pass, which includes the `12 / 12 / 3` class as well as the burst class. To isolate the all-429 class, read the first `probed_count − postponed_probed_count` rows of `routes` (they are in probe order) and require every one to carry `http_status` 429. The next census asks (a) whether such boots end with `ready_count ≥ 1`, (b) what fraction of 429 rows carry `retry_after_s` and how long the refusals claim to last, (c) whether the healthy-minute figures (`ready 5–6`) are unchanged, and (d) the provisioning step's duration on those boots, so the benefit in (a) and the cost above are read from one table. If (a) is consistently 0 **and** (b) shows providers publishing a usable delay, the follow-up is to spend the second pass after that delay rather than immediately — a decision this ADR deliberately leaves to that data. `#1948`'s shared rate ledger remains the lever above all of it.
