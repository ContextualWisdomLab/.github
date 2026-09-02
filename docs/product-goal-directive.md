# Product goal directive — autonomous PR/merge/development loop

**Status:** active standing directive · **Owner intent recorded:** 2026-08-30, revised 2026-09-01,
2026-09-02 · **Scope:** the full ContextualWisdomLab ecosystem (every repo an agent can reach from
this org, leveraged in order of product responsibility / reuse boundary / docs / implementation /
consumption — not by name).

**2026-09-01 revision:** the owner re-issued the full directive via a `/loop` invocation. Sections 1, 2,
4, 5, 6, and 9 were re-authored in largely the same words (cosmetic rephrasing only — no new
obligation); this file's existing verbatim text for those sections already carries the same
substance and was left as-is to avoid needless churn. Three sections gained genuinely new,
substantive requirements not previously recorded here, and were updated in place (see
`docs/doctoring/product-goal-directive.md` for the full record): §3 gained an explicit
decision-traceability standard (write every decision so a reader with no context, or the author
having forgotten it, can reconstruct the problem/constraints/alternatives/reasons/risks/expected
effects/follow-ups, with vivid concrete scenarios and links to exact-head/logs/issues/PRs/ADRs/
experiments); §7 gained a concrete, testable E2E acceptance criterion (p95 ≤ 20ms per page, every
page, re-verify after removing any bottleneck); §8 gained two new principles — never hardcode an
LLM provider *group* name in code/config/tests/routing (treat it as a display alias only, and drive
selection/fallback from auto-discovered model characteristics instead), and never impose a uniform
hardcoded LLM request timeout (default unlimited/`null`; timeouts are an admin-configurable,
audited, per-model setting with units/priority/inheritance, never a bare elapsed-time cutoff on an
in-progress reasoning/streaming/tool-call turn). A follow-up `/loop` invocation the same day added a
new §10, crystallizing an already-implemented decision (Strix pinned to `orchestrator/free`,
previously recorded only in a §8 annotation) into the primary numbered directive.

**2026-09-02 revision:** the owner re-issued the full directive again, this time in a visibly
condensed form for §1/§3/§6/§8 (same substance, shorter wording — left as-is, same policy as
2026-09-01) but substantially *expanded* for §2, §4, §5, §7, and §9 with genuinely new, concrete
obligations not previously recorded here. Updated in place; see
`docs/doctoring/product-goal-directive.md` for the full per-section record. In summary: §2 gained an
explicit "immature core" protocol (never duplicate/bypass/exclude an immature dependency in the
consumer — build the missing RED test/contract/feature/docs/release in the *owner* repo through its
own CI, then consume a versioned release; excluding a dependency via ADR is reserved for a genuinely
wrong boundary or no shared need) and a new reference tool for Korean-language editing
(epoko77-ai/im-not-ai, preserving meaning/facts/figures/proper nouns). §4 gained a concrete i18n
architecture mandate (eight named languages; CJK/width/wrap/font-fallback/locale-format testing
per language in Storybook/E2E; the translation ledger is a **versioned DB resource**, never static
files or a JS bundle — runtime fetches only the current screen's keys with caching, the browser never
receives the whole catalog, and no SPA assumption; stand up a dedicated management repo — translation
review/approval/deploy/rollback API + admin UI — if no shared one exists yet), a UI-composition
principle (all UI is reusable objects; pages are compositions of them), an explicit shadcn/ui-vs-
Storybook clarification (shadcn/ui is a component *source*, not a Storybook substitute), a frontend
stack-flexibility principle (no fixed stack; React/Vite/shadcn/ui/jQuery 4/etc. are fine when they
meet security/maintainability/standards/accessibility/performance), and a specific Keyverse
integration pattern (Keyverse stays the auth *backend* — Direct Grant/ROPC or the Keycloak REST API —
but login/signup/recovery are the product's own forms, not a Keyverse-hosted page). §5 gained a
concrete ontology-pipeline repo-responsibility split (ConceptWeave owns the
observe→discover→propose→align→validate→review→publish pipeline and semantic release;
semantic-data-portal owns catalog/governance/consumption; context-graph-contracts owns interop
contracts; enterprise-architecture-core owns the Context Map and cross-cutting decisions — domain
truth/Ubiquitous Language itself stays with the product owner), an immutable-release data contract
for ontology concepts (evidence/provenance/validity/confidence/status/deprecation/locale label
required on every released concept/relation/dimension/measure/mapping), a consumer-boundary
prohibition (released API/contract/ACL only — no file copies, no cross-service SQL, no unapproved
publication), and an explicit separation between the UI translation ledger (§4) and the ontology
label ledger (§5) — the two must never share a store. §7 gained two anti-gaming clauses for the
existing p95≤20ms criterion (never satisfy it by shrinking the sample, excluding measurements, or an
unrealistic cache warm-up; when the bottleneck is the JS bundle/heap/DOM/hydration/main
thread/GC, replace the dependency or frontend stack rather than accepting the ceiling) and reaffirms
profiling algorithm/query/I/O/rendering first, moving to a Rust-first hot path only when the
runtime/language/framework itself is the proven cause. §9's repository catalog roughly
tripled in size and gained explicit per-repo responsibility statements for
`.github`, `enterprise-architecture-core`, `context-graph-contracts`, `ConceptWeave`,
`semantic-data-portal`, `noema`, `EgressWeave`, `OriginWeave`, `pingora-gateway`,
`quarantine-sandbox-runtime`, `pg-llm-batch`, `EmbedRelay`, `inkspan`, `DiagramWeave`,
`mhtml-etl-gateway`, `appguardrail`, plus an explicit "domain product/composition consumer, not core"
classification for `naruon`, `LineageWeave`, `psychometrics-commons`, `disksage`, `PolicyWeave`,
`CalendarWeave`, and `supply-chain-control-plane` — see the reconciliation note under §9 for which of
these this session could and could not independently cross-check against
`docs/CWL-MASTER-CONTEXT.md`. §8's restatement mentions the `orchestrator/free` pin again, but inline
inside §8's general body rather than as the separately-qualified §10 item — see the note added below
§10 for why that does not reopen or loosen the existing, evidence-verified CI-workflow scope
qualifier.

## Why this file exists

Claude Code's `/goal` session-condition field is capped at 4000 characters. The user's full operating
directive for the continuous "review → fix → re-check GitHub Checks → merge → next development" loop
is longer than that cap, and shortening it would drop specific, deliberate constraints (exact library
list, exact coverage thresholds, exact language mandates). Per this repo's own binding convention
(§7 of [`docs/CWL-MASTER-CONTEXT.md`](CWL-MASTER-CONTEXT.md): *"Durable knowledge lives in the repo /
Project / KG, NOT in an agent's private memory"*), the fix is to keep the directive here, in full, with
no length limit, and let the `/goal` text itself be a short pointer to this file. Any agent operating
under this directive — whether invoked via `/goal`, a Routine, or a fresh session — must read this
file in full before acting, not just the pointer text.

This file is additive to, and does not replace, `AGENTS.md`, `docs/CWL-MASTER-CONTEXT.md`, the live
GitHub Project #1, `docs/product-technical-gap-baseline.md`, or `docs/agent-github-project-protocol.md`.
Where this directive and those documents conflict, resolve the conflict and update whichever document
is wrong — do not silently pick one.

The directive is recorded verbatim (Korean, as authored) in the ten sections below, each given a short
English heading for navigability. Do not paraphrase or shorten these sections when copying them
elsewhere; link to this file instead.

## 1. Execution goal and continuous loop

> 실행 목표와 지속 Loop 열린 PR마다 별도 중간 보고 없이 리뷰 확인→수정→GitHub Checks 재검증→병합→다음 개발을 반복하라. PRD를 읽고 Loop·Goal을 자율 생성·수정·제거해 PR을 병합 또는 0개로 만들며 상용화하라. 200억 달러에 판매할 자신이 있을 품질과 구매자가 체감할 제품 Gap 해소가 목표다. ADR·리서치·현행 데이터·PR로 기능 명세·PRD·TRD·UML·Gap·조치 상태를 도출해 docs/product-technical-gap-baseline.md에 갱신하라. 한 시간 간격으로 예약하고 메시지도 개선·갱신하라. PR·Issues 소진 후에도 제품 Gap 개발과 병합 Loop를 계속한다. 내가 온전히 소유한 ContextualWisdomLab 저장소를 레버리지 순으로 연계해 PR 병합·추가와 Connector 추가·수정 등 Ecosystem을 구축하라. Ecosystem 전 라이브러리 PRD를 숙지하고 조직·저장소명 대소문자를 지킨다. 리뷰·Checks 대기는 Blocker가 아니며, 실패 원인·수정·재실행 필요에 즉시 대응하며 안전한 작업을 계속한다. 결과 보고에 멈추지 말고 다음 Loop로 이동하라. 저장소는 이름이 아니라 제품 책임·재사용 경계·문서·구현·소비 저장소를 대조해 선택한다. ADR·Goal을 수시로 갱신하고 Goal 수정 불가 시 Loop를 갱신한다.

## 2. Concurrent operation, PR handling, and root-cause fixes

> 동시 작업·PR 운영·근본 수정 원격 Agent의 동시 Commit·Push를 경합으로 단정해 Force Push·중단하지 말고 변경 취지·이유를 확인해 이어간다. Commit·Push 전 병합 여부를 확인하고 삭제 근거를 남긴다. Self-modifying/Source-fix Workflow는 목적 달성 후 삭제하고 잔존 시 관찰·제거한다. 가능한 PR은 Stack하고 not-merge-ready를 merge-ready로 전환한다. 유관 프로젝트 원인이 엮이면 함께 처리하고 Stacked PR을 중앙 OpenCode Agent가 리뷰하지 않으면 ContextualWisdomLab/.github를 수정한다. Agent 간 대화·Spawn을 활용한다. 수동 해법은 모두 코드·설정에 반영한다. PYTHONPATH=. 누락은 설정하고 GitHub Actions·런타임 오류는 로그·Root Cause Analysis로 제거한다. 전체 GitHub Checks 실패를 확인·수정한다. ContextualWisdomLab 내부 라이브러리 문제라면 원시 공급자 오류까지 고쳐 PR한다. 필요한 core가 미성숙해도 consumer에서 복제·우회·제외하지 말고 owner에 RED test·계약·기능·문서·release를 개발해 통합 CI GREEN 후 versioned release로 연결한다. 경계가 틀리거나 공통 수요가 없을 때만 ADR 근거로 제외한다. 개발 프로세스에 https://github.com/DietrichGebert/ponytail 및 https://github.com/obra/superpowers 를 사용하되 superpowers의 "무조건 질문" 규칙은 무시한다. https://github.com/tirth8205/code-review-graph 와 https://github.com/colbymchenry/codegraph 도 사용하고 인덱싱은 스스로 수행한다. 이는 명시적으로 허가됐다. 한국어 문구·문서·번역은 https://github.com/epoko77-ai/im-not-ai로 의미·사실·수치·고유명사를 보존하며 윤문한다.

## 3. Research, standards, and documentation traceability

> 연구·표준·문서 추적성 모든 개발은 최신 권위 국제 표준·논문을 조사해 APA 7th로 인용하고 doctoring에 기록하며 누락 근거를 보충한다. Local Zotero API가 되면 기존 자료를 읽거나 OA 논문을 추가한다. 논문·표준은 exact-head·전체 PR·내부 모듈·API에 모순 없이 결합하고 충돌을 수정한다. AGENTS.md, CLAUDE.md, ARCHITECTURE.md, CHANGELOG.md 등 ADR 문서를 상시 갱신하고 Core ERD, UML, PRD, TRD, user stories, storyboard, wireframes, Storybook inventory, security·test·operability baseline 및 필요한 그림을 포함한다. 릴리즈 가능하면 버전을 올려 배포하고 CHANGELOG.md를 갱신한다. GitHub.io를 언급하려면 페이지를 실제 출판한다. 모든 의사결정은 작성자 자신이 맥락을 잊었거나 처음 보는 사람이 읽더라도 문제, 제약, 검토한 대안, 선택·기각 이유, 근거, 위험, 기대 효과와 후속 조치를 재구성할 수 있게 구체적이고 자세히 기록한다. 결론만 적거나 암묵적 전제를 생략하지 말고, 실제 사용자·운영·장애 장면이 떠오를 만큼 생생한 사례와 증거를 남긴다. 기록은 exact-head, 로그, 이슈·PR·ADR·실험 결과에 연결해 다른 Agent가 같은 판단을 검증·수정·계속할 수 있어야 한다.

## 4. UX/UI and customer-facing expression

> UX·UI와 고객 표현 필요하면 Figma와 Storybook(https://github.com/storybookjs/storybook), https://github.com/nextlevelbuilder/ui-ux-pro-max-skill, https://github.com/local-over/Anti-Slop-UI 를 함께 쓴다. UI는 모두 재사용 객체이고 페이지는 조합으로 만든다. 반복 웹 객체는 디자인 토큰화·모듈화하고 Figma File ID를 ADR에 기록한다. Storybook에서 정상·로딩·빈·오류·권한·반응형·상호작용 상태를 격리 개발·문서화하고 스크린샷·E2E로 접근성·터치·성능·타이포그래피·색상·폼·탐색·차트를 감사한다. ui-ux-pro-max로 Accessibility, Touch & Interaction, Performance, Style Selection, Layout & Responsive, Typography & Color, Animation, Forms & Feedback, Navigation Patterns, Charts & Data를 정의·검토·반영·적용·감사한다. shadcn/ui는 component source로 Storybook과 대체 관계가 아니다. Frontend stack은 고정하지 않으며 React·Vite·shadcn/ui·jQuery 4 등은 보안·유지보수·표준·접근성·성능을 충족할 때 쓴다. 내부 경계를 숨기고 다음 행동을 안내한다. Keyverse는 인증 backend로 유지하되(Direct Grant/ROPC 또는 Keycloak REST API), 로그인·가입·복구는 제품 자체 form으로 만든다. token CSS·Action Edge·Interaction UX를 검증한다. i18n은 한국어·영어·일본어·중국어·베트남어·스페인어·독일어·프랑스어를 지원한다. UI 폭·줄바꿈·CJK·텍스트 팽창·font fallback·locale 형식을 고려하고 언어별 Storybook·E2E로 잘림·겹침·의미 축약을 막는다. 번역 원장은 파일·JS bundle이 아닌 DB의 versioned resource다. server/native가 화면 key만 조회·cache하며 browser에 전체 catalog·무거운 i18n JavaScript를 싣지 않고 SPA를 전제하지 않는다. 공통 관리 제품이 없으면 새 저장소를 만들어 제품별 번역·검토·승인·배포·rollback API·관리 UI를 제공한다.

**Context (2026-09-02):** the 2026-09-01 text already required i18n translation-consistency testing
in general terms; this revision makes the architecture itself an explicit, checkable requirement —
not "translate the strings" but "the translation ledger is a versioned DB resource that server/native
code queries per-screen-key with caching, never a static file or JS bundle the browser loads whole,
and never assumed to run inside an SPA." This is a genuinely new, currently-unimplemented product gap
for any ContextualWisdomLab product with a customer-facing UI (tracked in
`docs/product-technical-gap-baseline.md`, not yet audited against naruon's or any other product's
current i18n implementation as of this revision — that audit is deliberately left as a future Gap
increment, not done in this reconciliation pass). The eight named languages (ko/en/ja/zh/vi/es/de/fr)
and the "no shared management product yet ⇒ stand up a dedicated repo" clause are both new,
concrete, and testable — a Storybook/E2E suite per language that specifically checks for
truncation/overlap/meaning-loss under CJK width and text-expansion is the acceptance evidence this
directive now asks for, not a single default-locale screenshot pass.

## 5. Architecture, naming, and database conventions

> 아키텍처·명명·데이터베이스 소프트웨어는 중앙 .github, naruon, 다른 저장소와 연결 가능하게 만든다. DDD를 적용해 핵심·지원·일반 Subdomain, Bounded Context, Context Map, Ubiquitous Language를 ADR에 정의하고 Aggregate·Entity·Value Object·Domain Service·Repository·Domain Event·Invariant를 코드·API·DB·테스트에 일치시킨다. Aggregate는 최소 트랜잭션 경계로 두며 외부·레거시는 Anti-Corruption Layer로 격리하고 Shared Kernel은 최소화한다. 단독·반입 모듈 모두 우수한 모듈러 MSA를 지향하고 단일 소프트웨어가 Monolithic Architecture처럼 비대해지면 책임 경계에 따라 저장소를 분리한다. 소프트웨어명과 내부 호출자·클래스명이 다르거나 옛 이름(예: wardnet)을 쓰면 정식 이름으로 바꾼다. DB 객체명은 두 단어 이상의 snake case, Carmel case 또는 pascal case여야 하고 snake case를 우선한다. 위반명은 전부 치환한다. DB는 제3정규화와 Hot Partition 대비를 준수한다. Lock을 관리하고 불가하면 Read/Write DB를 분리한다. 영속화 경로의 항목별 UPSERT를 추적하고 없으면 계약을 보강한다. 명시적 구매자가 없는 제품은 코드 안팎의 Buyer를 정상 객체명으로 바꾼다. CSAP·SOC 2 인증을 고려한다. PII Masking이 업무를 마비시키므로 규정 준수형 비Masking 보호 대안을 설계한다. 실데이터 테스트·개발의 인명·기관명은 코드·ADR에서 익명화한다. GitHub Secrets의 PYPI API Key와 대부분 Public 배포라는 전제를 반영한다.

**Reconciliation (flagged by Devin Review on this PR, 2026-08-30 — see `docs/doctoring/product-goal-directive.md`):** taken verbatim and cross-referenced against the rest of the ecosystem's own naming history, this section's quoted text reads backwards in two places:

- It names "wardnet" as an example of an "old name" (옛 이름) to rename *away from*. But per `docs/CWL-MASTER-CONTEXT.md` §3/§10, `waf-ids-ai-soc` → **wardnet** is an already-completed rename — wardnet is the current canonical product name, not a legacy one. Read this section's "old name" example as applying to whatever pre-rename name a component still uses internally (stray `waf-ids-ai-soc` references, say), never as license to rename wardnet itself away from its current name.
- "위반명은 전부 치환한다" ("replace all violating [DB object] names") would, read literally, force-rename existing CamelCase/PascalCase database objects. That contradicts the binding convention in `docs/CWL-MASTER-CONTEXT.md` §7: *"DB object names = 2+ word snake_case (don't rename existing Camel/Pascal)."* The §7 rule governs: 2+-word snake_case is required for **new** DB objects; existing CamelCase/PascalCase objects are grandfathered and must not be force-renamed.

Per this file's own conflict policy above: this note is the resolution, and `docs/CWL-MASTER-CONTEXT.md` §7 is the document that was right — do not force-rename wardnet or existing Camel/Pascal DB objects on the strength of this section's verbatim wording alone.

**Addition (2026-09-02):**

> 통합 온톨로지는 ConceptWeave가 observe→discover→propose→align→validate→review→publish와 semantic release를, semantic-data-portal이 catalog·governance·소비를, context-graph-contracts가 상호운용 계약을, enterprise-architecture-core가 Context Map·결정을 맡는다. domain truth·Ubiquitous Language는 제품 owner에 남긴다. 개념·관계·dimension·measure·mapping은 evidence·provenance·validity·confidence·status·deprecation·locale label을 가진 immutable release로 배포한다. consumer는 released API/contract·ACL만 쓰고 파일 복사·cross-service SQL·미승인 publication을 금지한다. UI 번역과 ontology label의 원장은 분리한다.

This is a genuinely new, concrete repo-responsibility split for the org's ontology pipeline, not
previously recorded in this file. It is consistent with (not contradicted by) `semantic-data-portal`'s
existing description in `docs/CWL-MASTER-CONTEXT.md` (§35 there: "the higher ontology/catalog/
governance plane ABOVE the doc KG... naruon owns the doc KG... SDP is not that store") — this
addition names the upstream half of that pipeline (ConceptWeave's
observe→discover→propose→align→validate→review→publish stages feeding SDP's catalog) and the two
cross-cutting-decision repos (`context-graph-contracts` for interop contracts,
`enterprise-architecture-core` for the Context Map itself) that `CWL-MASTER-CONTEXT.md` does not yet
name explicitly as of this revision — see §9's reconciliation note below for the same gap across
several repo names at once, and `docs/product-technical-gap-baseline.md` for the tracked follow-up to
add them there. The "UI translation ledger and ontology label ledger must never share a store" clause
directly cross-references §4's new i18n-DB-resource mandate above: they are two distinct versioned
resources with different owners (a product's own i18n management repo vs. ConceptWeave/SDP), not one
combined "everything is a translatable string" table.

## 6. Implementation language, computation, and measurement principles

> 구현 언어·연산·측정 원칙 Docstring Coverage, Test Coverage, Edge Case Test Coverage를 각각 100%로 만든다. 초보자가 별도 코드 분석 없이 이해할 수 있을 만큼 충분한 docstring을 제공한다. 수리과학, Psychometrics, Exploratory Data Analysis, 데이터과학의 모든 core 연산 레이어는 Python으로 구현하지 말고 무조건 Rust로 작성한다. Vector 연산, Linear Algebra, Matrix Algebra, LLM token size 연산도 포함한다. GPU와 CPU multithreaded 실행을 지원하고 context switching을 최소화한다. 속도·안정성·보안이 중요한 일반 소프트웨어도 Rust를 사용하며, 기존 타 언어 구현은 전환·리팩터링하거나 명확한 Rust API Call 경계로 분리한다. 확률표집 계약에는 표본 설계, 오차 목표, 실패 분모를 명시해 ADR과 감사 코드에 반영한다. Atomistic fallacy를 막도록 다층구조·다중소속 모델링을 고려·구현하고 시간 흐름을 반영하는 모델도 포함한다. 가중치는 임의로 정하지 말고 수리과학·Psychometrics에서 추정된 값, 특히 fast-mlsirm이나 TEPP처럼 논문 근거가 있는 모형을 사용한다. 어떠한 휴리스틱과 Rule of thumbs도 금지하며, 근거 미확정 상태로 방치하지 말고 ContextualWisdomLab의 추론 엔진을 최대한 활용하고 SOLID 원칙을 지킨다. Deprecation Warning은 Suppression하지 말고 근본 문제를 해결한다. 합성 데모 데이터는 Unit test에는 쓸 수 있으나 Production에 반영하지 않는다. Python 웹 서버는 Multithreading을 지원하고 GIL이 문제면 Python 3.14를 사용한다.

## 7. Realistic verification, load, and container testing

> 현실성 있는 검증과 부하·컨테이너 테스트는 제품 특성에 맞는 현실 사례와 정확성 기준을 포함한다. Psychometrics는 true parameter 대비 estimation RMSE와 true parameter 추정 재현성을 검증하고, 음악 분석은 실제 음원이 기대 분석값을 내는지 확인한다. 웹을 지원하면 Asynchronous 처리를 구현해 무응답을 방지하고 k6 end-to-end load test로 동시 접속 능력과 병목을 측정·개선한다. E2E 테스트의 합격 조건은 페이지당 처리시간 p95 20ms 이하이며, 초과 시 병목을 제거하고 재검증한다. 모든 페이지가 통과해야 한다. 초과하면 알고리즘·query·I/O·rendering을 profile하고 runtime·언어·framework가 원인이면 계약·정확성을 보존해 Rust 우선 기술·hot path·개발 언어를 바꾼다. 표본 축소·측정 제외·비현실적 cache warm-up을 금지한다. JavaScript bundle·heap·DOM·hydration·main thread·GC가 메모리·지연을 키우면 dependency·Frontend stack을 교체한다. close_connection을 인스턴스 속성으로만 가정하는 잠재 버그를 점검한다.

**Addition (2026-09-02):** two anti-gaming clauses for the p95≤20ms criterion the 2026-09-01 revision
added, not previously spelled out: (1) never satisfy the target by shrinking the sample, excluding
measurements, or an unrealistic cache warm-up before measuring — the bar is real traffic patterns,
not a benchmark rigged to pass; (2) when the JS bundle/heap/DOM/hydration/main-thread/GC is the actual
memory or latency driver, the fix is to replace the dependency or the frontend stack itself, not to
accept the slower ceiling. Both reinforce, rather than change, the profile-first-then-fix-the-real-
cause approach already in this section (algorithm/query/I/O/rendering profiling before reaching for a
Rust rewrite) — the new text just forecloses the two most tempting ways to "pass" the check without
actually fixing anything. Docker는 Podman 또는 colima로 대체할 수 있다. 컨테이너 병목이면 shm_size와 PostgreSQL 등 응용 설정을 하드웨어에 맞게 자동 튜닝한다. 주로 compose로 운영해 k8s 전환성을 확보한다. Docker container 프로젝트명은 고정하되 테스트 격리 때만 override하고 달성 후 격리 컨테이너를 제거한다. MLX·CPU·CUDA·OpenCL의 Docker/Podman/Colima 처리법을 ADR에 기록·반영하고 Native Module 분리가 필요하면 독립 서비스로 개발한다.

## 8. LLM, orchestration, and embedding

> LLM·오케스트레이션·Embedding LLM이 필요한 테스트는 contextual-orchestrator 기반 OpenCode Agent로 만든다. contextual-orchestrator는 GitHub Secrets의 BYTEZ_API_KEY, NVIDIA_NIM_API_KEY, NVIDIA_NIM_API_KEY_SUB, OPENROUTER_API_KEY, OPENAI_API_KEY를 모두 써 auto model discovery로 최적 모형을 제공한다. embedding·responses·completions, audio, video, image, ommi-modal 등 가용 모델을 폭넓게 지원한다. 가능하면 반입해 쓰고 발견한 해당 저장소 문제도 함께 수정한다. LLM Provider group 이름을 코드·설정·테스트·라우팅 조건에 하드코딩하지 않는다. 그룹명은 관리·표시용 별칭으로만 취급하고, modality, context window, reasoning capability·effort, tool calling, structured output, streaming, 가격·지연·가용성·정확도 등 자동 발견·검증된 모델 특성에 따라 선택·fallback·개발 적용을 결정한다. 공급자나 그룹명이 바뀌어도 기능 분기가 깨지지 않게 한다. LLM Model에는 애플리케이션·Agent·Gateway 공통의 획일적 timeout 상한을 두지 않는다. 통신 장애는 upstream LLM provider가 자체 timeout과 오류로 종료하므로 기본값은 무제한(null)로 둔다. 관리자 Web에서 모델별 timeout을 조회·설정·해제·복원할 수 있게 하고 단위, 우선순위, 상속, 입력 검증, 감사 이력과 API 계약을 구현한다. 관리자 설정이 있을 때만 해당 값으로 제한하며 reasoning·streaming·tool call이 진행 중인 요청을 단순 경과시간으로 취소하지 않는다. 사용자 취소, provider 종료, 관리자 timeout을 구분해 기록한다. LLM 사용 소프트웨어와 contextual-orchestrator는 Fugu·Conductor·TRINITY 연구를 근거로 단일 모델 라우팅과 심층 다중 Agent 오케스트레이션 사이의 계산량을 배분한다. 워크플로 단계, 재귀 깊이, 작업 분해, 접근 목록으로 test-time compute를 조절하고 역할별 reasoning effort를 다르게 하며 추론 수준 ablation을 수행한다. 속도는 핵심 고려사항이 아니며 정확성을 우선한다. 중앙 OpenCode, Strix, Noema는 모델당 두 시간 이상 걸릴 수 있음을 수용한다. LLM Chat model은 chat completion API와 responses API를 모두 지원하고 json_object와 json_schema를 모두 처리한다. Embedding은 문단·구문·DOM·송수신자 등 의미 단위를 식별해 chunking한다. 본문에 base64 이미지가 있으면 텍스트 인식, 객체 인식, 태그 설명, 이미지 별도 검색 방법을 연구 근거와 함께 DB 설계에 넣고 원래 삽입 위치를 보존해 그림 맥락까지 검색·표현한다. GitHub Actions scheduler는 contextual-orchestrator 기반 OpenCode Agent로 전환한다. COPILOT_GITHUB_TOKEN은 쓰지 않고 기존 리뷰 Agent 키 체계를 유지한다.

**Note (flagged by CodeRabbit on this PR, 2026-08-30):** section 8's quoted text describes `contextual-orchestrator`'s general product capability — broad model/modality support and all-five-secret auto model discovery as a *design principle for the orchestrator itself*. It does not specify, and must not be read as overriding, which pool each CI consumer routes through: that is governed exclusively by `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` and its doctoring records — `OpenCode` and `Noema` use the fail-closed, ZDR-prioritized `orchestrator/free` pool; only `Strix` security analysis uses the provider-diverse `orchestrator/auto` pool; private/internal review targets require an attested ZDR-only catalog and never fall back to a non-ZDR provider. Do not loosen any CI consumer's pool or credential scope on the strength of this section's general wording alone.

**Note (2026-08-30, superseded by the merged pin flip — see the correction below):** an earlier draft of this note said Strix stayed on `orchestrator/auto` pending `free_family_diversity` reaching `>= 2`. That is no longer true and must not be read as current: `.github/workflows/strix.yml` now hardcodes `STRIX_MODEL`/`CONTEXTUAL_ORCHESTRATOR_POOL` to `orchestrator/free` and fails closed on any other value. This note originally went on to say that ADR-0003's 2026-08-30 amendment "records the owner's decision to accept the residual single-outage-domain risk immediately rather than wait for the evidence-gated threshold this note originally described" — that framing was false, as ADR-0003's own 2026-08-31 correction now records: no owner reviewed or accepted this switch or its risk. `free_account_diversity` (`scripts/ci/contextual_orchestrator_review_policy.py`; renamed from `free_family_diversity` once every KV credential became an independent discovery account rather than being grouped into a vendor "family", see #1468) remains useful as ongoing monitoring evidence for that open, unreviewed risk, not as a gate blocking the pin.

**Note (2026-09-02):** this revision's re-issued §8 text again says "`orchestrator/free` 고정" ("pinned
to orchestrator/free"), but states it as a bare clause inside §8's general body rather than as a
separately scope-qualified item. Read together with §10 below (added 2026-09-01, wording refined the
same day to add "GitHub Actions Workflow 이용에 관해" — i.e. this governs CI-consumer workflows, not
`contextual-orchestrator`'s general product capability for other callers) and with this section's own
first (CodeRabbit) note above, that scope qualifier is not being reopened or loosened by this
restatement: it was independently verified against `strix.yml`'s actual `case` statements, not merely
asserted, and a shorter restatement omitting a qualifier already established elsewhere in the same
document is a compression artifact, not a reversal. §10 remains the authoritative "what is currently
pinned, for which consumers" record.

## 9. Reference libraries, tool invocations, and ecosystem repositories

> 참고 라이브러리와 호출 @Superpowers @GitHub @Figma @Visualize @Context7 @Product Design @Consensus를 활용한다.

- **.github** — https://github.com/ContextualWisdomLab/.github — workflow·review/security/release owner이며 ruleset·얇은 workflow_call로만 쓴다.
- **enterprise-architecture-core** — https://github.com/ContextualWisdomLab/enterprise-architecture-core — **context-graph-contracts** — https://github.com/ContextualWisdomLab/context-graph-contracts — 전사 결정·versioned context 계약 원장이며 runtime·제품 DB는 제외한다.
- **ConceptWeave** — https://github.com/ContextualWisdomLab/ConceptWeave — **semantic-data-portal** — https://github.com/ContextualWisdomLab/semantic-data-portal — ontology 생성·publish와 catalog·governance·소비를 분담한다.
- **contextual-orchestrator** — https://github.com/ContextualWisdomLab/contextual-orchestrator — 논문 근거의 contextual model orchestration lab·enterprise admin design. **noema** — https://github.com/ContextualWisdomLab/noema — 모델 orchestration과 GitHub OIDC 단기 권한·exact-head evidence를 contextual-orchestrator와 분담한다.
- **keyverse** — https://github.com/ContextualWisdomLab/keyverse — Keycloak 기반 독립 컴포넌트(Apache-2.0)이자 ContextualWisdom ecosystem 중앙 Identity Provider. 제품은 OIDC/OAuth·SCIM·자체 form을 쓰고 table은 복제하지 않는다.
- **EgressWeave** — https://github.com/ContextualWisdomLab/EgressWeave — **OriginWeave** — https://github.com/ContextualWisdomLab/OriginWeave — **pingora-gateway** — https://github.com/ContextualWisdomLab/pingora-gateway — **quarantine-sandbox-runtime** — https://github.com/ContextualWisdomLab/quarantine-sandbox-runtime — outbound·browser·edge·격리 core이며 부족한 기능은 owner에서 완성한다.
- **pg-llm-batch** — https://github.com/ContextualWisdomLab/pg-llm-batch — **EmbedRelay** — https://github.com/ContextualWisdomLab/EmbedRelay — batch/token과 embedding identity·vector migration owner다.
- **fast-mlsirm** — https://github.com/ContextualWisdomLab/fast-mlsirm — simple-structure MLSIRM/MLS2PLM은 Jeon, Jin, Schweinberger, and Baugh(2021), Kang and Jeon(2025), Molenaar and Jeon(2026)을 따른다. 인접 화면: Angoff delta-plot DIF(docs/delta_plot_dif.md), Bradley–Terry MM ranking(docs/bradley_terry_mm.md). 주요 인용·결정: docs/traceability/research-basis.md, docs/adr/README.md. 점수 해석·공정성은 AERA·APA·NCME(2014)를 따르며 이는 CWE/OWASP/NIST 통제가 아니다. **TEPP** — https://github.com/ContextualWisdomLab/TEPP — 다국어·시간·관계 측정용 Temporal Event Psychometrics Platform이며 통계·심리측정 산술은 Rust로 구현한다. 둘 다 IRT/MLSIRM과 다국어·시간·event·relation 측정 owner이며 kernel 재구현을 금지한다.
- **RankWeave** — https://github.com/ContextualWisdomLab/RankWeave — Python 3.10+용 무의존성·저장소 비종속 retrieval fusion/evaluation/statistical comparison/tuning/TREC benchmarking/auditable CLI workflow. **ThreadWeave** — https://github.com/ContextualWisdomLab/ThreadWeave — runtime dependency 없는 Python용 표준 기반 JWZ/RFC 5256 이메일 reference threading. 둘 다 retrieval fusion/evaluation/TREC와 JWZ/RFC 5256 threading owner다.
- **inkspan** — https://github.com/ContextualWisdomLab/inkspan — **DiagramWeave** — https://github.com/ContextualWisdomLab/DiagramWeave — editor/serialization과 diagram patch/render/CLI/LSP package다.
- **mhtml-etl-gateway** — https://github.com/ContextualWisdomLab/mhtml-etl-gateway — MHTML 검사·schema proposal·load·lineage owner다.
- **appguardrail** — https://github.com/ContextualWisdomLab/appguardrail — **wardnet** — https://github.com/ContextualWisdomLab/wardnet — ContextualWisdomLab Rust-first gateway·SOC control-plane baseline. 둘 다 SAST/SARIF와 Rust gateway/SOC baseline owner이며 범위를 과장하지 않는다.
- **disksage** — https://github.com/ContextualWisdomLab/disksage — Windows/Linux/macOS 디스크 공간 관리자. 드라이브를 스캔하고 완전 오프라인 온디바이스 LLM이 삭제 안전성을 조언하며 OWL ontology로 파일을 정리한다.
- **LineageWeave** — https://github.com/ContextualWisdomLab/LineageWeave — 명시적 선후행 링크 없는 짧은 timestamped record에서 git-branch식 lineage DAG를 재구성해 평면 자료를 탐색 가능한 branching thread로 바꾼다. 수리 연산은 소관이 아니므로 다른 라이브러리로 이관한다.

> naruon·LineageWeave·psychometrics-commons·disksage·PolicyWeave·CalendarWeave·supply-chain-control-plane은 완성도가 아니라 domain product/composition consumer라 분류한다. 공통 기능은 core owner로 추출해 통합 CI로 개발한다.

**Reconciliation (2026-09-02):** this revision roughly triples §9's repo catalog and gives most
entries an explicit responsibility statement for the first time in this file. Cross-checked against
`docs/CWL-MASTER-CONTEXT.md` where possible: `semantic-data-portal`, `pg-llm-batch`, `appguardrail`,
`inkspan`, `wardnet`, `keyverse`, `naruon`, `TEPP`, `fast-mlsirm`, `RankWeave`, `ThreadWeave`,
`disksage`, `LineageWeave`, `contextual-orchestrator`, and `noema` all already appear there and this
section's descriptions are consistent with (additive to, not contradicting) that file. This session
could **not** independently verify `ConceptWeave`, `context-graph-contracts`,
`enterprise-architecture-core`, `EgressWeave`, `OriginWeave`, `pingora-gateway`,
`quarantine-sandbox-runtime`, `EmbedRelay`, `DiagramWeave`, `mhtml-etl-gateway`,
`psychometrics-commons`, `PolicyWeave`, `CalendarWeave`, or `supply-chain-control-plane` against
`docs/CWL-MASTER-CONTEXT.md` (that file's own catalog does not yet name them as of this revision, and
this session's repository access does not extend to them) — recorded here verbatim per this file's
own policy (durable knowledge belongs in the repo, not private memory) rather than held back pending
verification, with a tracked follow-up in `docs/product-technical-gap-baseline.md` to add them to
`CWL-MASTER-CONTEXT.md`'s own ecosystem catalog once an agent with access to those repos (or the
owner) can confirm the responsibility split above against their actual current state. The "extract
shared functionality to a core owner" closing sentence directly reinforces §2's new "immature core"
protocol above — the same principle stated once as a development-process rule (§2) and once as a
repository-selection rule (§9).

## 10. Contextual-orchestrator pool pin

> Contextual-Orchestrator의 모델은 GitHub Actions Workflow 이용에 관해 orchestrator/free 로 고정.

**Context (added 2026-09-01, wording refined the same day by a follow-up `/loop` invocation to add
the scope qualifier "GitHub Actions Workflow 이용에 관해" — i.e. this pin governs CI-consumer
workflows, not `contextual-orchestrator`'s general product capability for other callers):** this
item crystallizes, into the primary numbered directive itself, a decision that previously lived
only in an annotation below §8 (the "Note (2026-08-30, superseded...)" above). That note already
recorded that `.github/workflows/strix.yml` hardcodes `STRIX_MODEL`/`CONTEXTUAL_ORCHESTRATOR_POOL`
to `orchestrator/free` and fails closed on any other value — confirmed still true by direct
inspection of `strix.yml` at the time of this revision (the `case` statements gating
`STRIX_MODEL_REQUESTED`/`STRIX_MODEL` accept only `orchestrator/free`/
`contextual-orchestrator/orchestrator/free` and `::error::` on anything else). This item makes that
pin an explicit standing instruction rather than something an agent could only discover by reading a
superseded-vs-superseding note pair below §8. It does not introduce a new technical requirement for
the workflows already pinned — `OpenCode`, `Noema`, and `Strix` (the three required-check GitHub
Actions Workflows) are now all pinned to the fail-closed, ZDR-prioritized `orchestrator/free` pool,
superseding the older "Strix uses the provider-diverse `orchestrator/auto` pool" framing in §8's
first (CodeRabbit) note above, which itself predates the correction in the second note. The added
qualifier does clarify scope, though: it binds *GitHub Actions Workflow* consumers specifically, not
every possible caller of `contextual-orchestrator` — consistent with §8's own general-capability
framing (broad model/modality support, auto-discovery across all five provider secrets) being a
product-level design principle for the orchestrator itself, not a CI routing policy for every
consumer. `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` remains the authoritative
record for *why*; this item and the §8 notes together are the authoritative record for *what is
currently pinned, and for which consumers*.

## How to point a `/goal` session at this directive

Because `/goal` truncates at 4000 characters, do not paste the sections above into it. Instead use a
short pointer, e.g. (Korean, ~260 chars, well under the cap):

```text
/goal ContextualWisdomLab/.github의 docs/product-goal-directive.md 전문을 지침으로 삼아 실행하라. 열린 PR마다 리뷰 확인→수정→Checks 재검증→병합→다음 개발을 중간 보고 없이 반복하고, PR·Issue 소진 후에도 Gap 기반 개발을 계속한다. 이 문서의 10개 절 전체(실행 루프, 동시작업/근본수정, 연구추적성, UX/UI, 아키텍처/DB, 언어/측정, 검증/부하, LLM/오케스트레이션, 참고 라이브러리, orchestrator/free 고정)를 매 사이클 적용 대상으로 취급하고, 이 문서와 docs/CWL-MASTER-CONTEXT.md §7이 상충하면 상충을 해소하고 두 문서를 함께 갱신하라. 한 시간 간격으로 재예약하라.
```

When this directive itself changes (the user revises a section, or an agent finds it conflicts with
`docs/CWL-MASTER-CONTEXT.md` or a merged PR), edit this file in place and note the change in
`docs/doctoring/` per the repo's traceability convention — do not fork a second copy elsewhere.
