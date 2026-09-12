# Actions 용량 한도와 workflow 부하: 관측 및 추론의 경계

2026-09-07 정정: 아래 2026-09-03 관측은 역사적 기록으로 보존한다.
용량 한도와 workflow 부하를 배타적 원인으로 단정했던 해석만 좁혔다.
현재 운영 상태나 이번 수리의 효과를 증명하는 문서가 아니다.

- **Date:** 2026-09-03
- **Subject:** two peer sessions independently observed the org's GitHub Actions run queue growing rather
  than shrinking this week and, in that tick, proposed auditing/consolidating/centralizing workflow files
  across the org as the fix. 당시 사용자 보고는 동시 job 한도에 가까운 사용량을
  뒷받침한다. 그러나 한도 포화와 중복 실행·장시간 점유·admission 결함은 함께
  존재할 수 있다. 이 기록만으로 지배적 원인을 확정하거나 workflow 부하 원인을
  배제할 수 없다. 파일 통합은 계약상 한도를 높이지 않지만 실행량은 줄일 수 있다.
- **Decision record:** none in `docs/adr/` — this is a diagnostic/root-cause finding for the org owner's
  awareness and eventual plan-tier decision, not an architecture decision this repository can make.
- **PR:** see the PR that carries this commit.

## Primary evidence

The user directly reported, and shared a screenshot of, the organization's GitHub Actions usage view
earlier in this session showing **58-60 of a 60 concurrent-job plan limit in use**. That is the primary
source for the specific ceiling figure in this record. The raw screenshot itself is not reproducible from
this doc (it was shared inline in conversation, not committed to the repository), so the number here is
reported as the user stated it, not independently re-derived pixel-for-pixel — flagged explicitly so a
reader can tell primary-source-observed-directly-by-the-user apart from what this session could verify
itself via the API (below). GitHub does not expose an org's concurrent-job plan ceiling through the
standard REST API available to this session (it is a billing/plan-settings value, visible only in the
org's own Settings → Actions/Billing UI) — confirming the exact number and its precise scope (whether it
counts standard-runner jobs only, whether larger/self-hosted runners have a separate pool, which plan tier
the org is on) requires the org owner to check that page directly; this record does not claim to have
re-verified those specifics independently.

## Corroborating evidence (live, reproducible, gathered for this record)

A live sample taken 2026-09-03 across three of the org's most CI-active repositories, using:

```bash
gh api "repos/ContextualWisdomLab/<repo>/actions/runs?status=in_progress&per_page=1" --jq '.total_count'
gh api "repos/ContextualWisdomLab/<repo>/actions/runs?status=queued&per_page=1"       --jq '.total_count'
```

| Repository | `in_progress` workflow runs | `queued` workflow runs |
|---|---|---|
| `.github` | 5 | 1,877 |
| `contextual-orchestrator` | 0 | 727 |
| `naruon` | 5 | 416 |
| **Total (3-repo sample)** | **10** | **3,020** |

이 표는 당시 63개 저장소 전수가 아닌 세 저장소 표본이다. 당시 전체 조회는
멈춘 상태가 지속돼 중단했고, 이후 `gh api rate_limit`은 5,000/5,000을 반환했다.
실패 당시 응답과 헤더가 보존되지 않아 원인은 미확정이다. 사후 잔여량만으로
같은 인증 주체·resource의 실패 당시 primary quota, reset 또는 secondary 제한을
배제할 수 없다.

이 API가 세는 대상은 job이나 점유 runner가 아니라 workflow run이다. Run 하나에
여러 job이 있을 수 있고, in-progress run 안에서도 job이 대기할 수 있다.
세 저장소의 비원자적 표본만으로 조직 전체 동시 job 수, 실제 한도 포화 또는
저장소별 원인과 조직 공통 원인의 우선순위를 식별할 수 없다. 사용자 보고의
58–60/60과 양립하는 관측이지만 그 수치를 독립적으로 증명하지는 않는다.

## Relationship to other queue-related findings already in this repository

This is not the first queue-depth observation recorded here, and this finding does not supersede or
contradict the earlier ones — they describe different, plausibly-compounding causes:

- `docs/product-technical-gap-baseline.md`'s 2026-08-31 entry (chained required-workflow poller removal)
  cites "53 concurrent Actions runs and a growing runner queue" as the trigger for removing roughly eleven
  runner-hours of polling per PR — a real, already-fixed contributor to total load, but framed as a
  mechanism-level fix (reduce runner-hours consumed per PR), not a claim about the plan's own ceiling.
- The later `ubuntu-latest` starved-floating-image finding (same file, referencing 822 queued Actions runs
  observed at merge time) diagnosed a *scheduling* problem — GitHub-hosted runners requesting the floating
  `ubuntu-latest` label sitting `queued` with no runner assignment for hours even when capacity should have
  been available, fixed by pinning off the floating label. That is a distinct failure mode from a hard
  concurrency quota: a starved image can leave slots idle *despite* available capacity, whereas a plan
  ceiling caps how many jobs can ever run concurrently even with perfect scheduling. Both can be true at
  once and both can slow the same queue; neither finding invalidates the other.
- A separate, still-unmerged-as-of-this-writing finding (`project_strix_concurrency_starvation_unfixed` in
  this session's own working notes) identifies that `strix.yml`'s concurrency group is scoped per-repository
  rather than per-PR, which starves cross-PR Strix evidence specifically — again a distinct, compounding
  mechanism, not the same thing as the org-wide plan ceiling this record documents.

## Implication for workflow-consolidation proposals

Consolidating or centralizing workflow files — the idea both peer sessions were independently converging
on this tick as *the* fix for the growing queue — is real hygiene and can reduce the *total number of
runs triggered* (fewer redundant CI paths competing for the same slots), which helps the queue drain
somewhat faster once jobs are submitted. It does **not** change how many jobs GitHub will run concurrently
for this organization at once: that number is set by the plan tier, not by how many `.yml` files exist or
how many of them are centralized versus per-repository.

저장소 간 workflow 통합·삭제는 파일 재배치와 실제 중복 trigger·job·점유시간 감소를 구분해야 한다.
후자는 한도를 바꾸지 않고도 backlog를 줄일 수 있다. 삭제할 때는 저장소별
branch-protection required checks와 입력 조정값을 재검증하고 보존해야 한다.

## Recommendation

용량 확대와 workflow 부하 감소는 별도 선택지다. 요금제·유료 용량·runner 추가는
실제 설정과 비용을 확인한 조직 소유자의 결정이 필요하다. 그 판단과 별개로 중복
실행, 불필요한 대기, stale-head 실행과 admission 결함은 기존 권한 안에서 수리한다.
정확한 전후 revision, trigger, job 실행시간, 취소 원인과 queue 표본 범위를 남겨
효과를 검증한다. 로컬 테스트 통과나 파일 수 감소만으로 운영 적체 해소를 주장하지 않는다.

## Audit trail

- User-reported screenshot of the organization's Actions usage view, shared earlier in this session
  (primary source for the 58-60/60 figure; not independently re-verifiable from this record alone).
- Live `gh api` sample gathered 2026-09-03 for this record (table above); `gh api rate_limit` confirmed
  5,000/5,000 REST calls remaining immediately after the aborted full-org sweep. 사후 해당
  primary quota 소진이 관측되지 않았다는 뜻이며 실패 당시 rate-limit을 배제하지 않는다.
- `docs/product-technical-gap-baseline.md` — the 2026-08-31 chained-poller-removal entry and the
  `ubuntu-latest` starved-image entry, both cross-referenced above.
- `docs/doctoring/ci-workflow-duplication-audit-20260902.md` — the org-wide workflow-duplication sweep this
  record's "Implication" section points back to.

## 정정 근거

- GitHub. (n.d.). *Using jobs in a workflow*. Retrieved September 7, 2026, from
  https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-jobs
  — 하나의 workflow에 여러 job이 존재할 수 있으므로 두 개수를 구분한다.
- GitHub. (n.d.). *Rate limits for the REST API*. Retrieved September 7, 2026, from
  https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
  — 인증 방식과 resource별 primary 제한, 별도 secondary 제한 및 조회 한계를 구분한다.
