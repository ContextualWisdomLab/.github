# Doctoring record: product-goal-directive.md (the `/goal` 4000-character cap)

- **Date:** 2026-08-30
- **Subject:** `/goal`'s session-condition field truncates at 4000 characters.
  The owner's full nine-section autonomous PR review→fix→merge→develop loop
  directive is ~7900 characters and would lose specific, deliberate
  constraints if summarized to fit. Introduced
  [`docs/product-goal-directive.md`](../product-goal-directive.md) to hold the
  directive verbatim, with no length limit, and linked it from `AGENTS.md`,
  `CLAUDE.md`, and `docs/CWL-MASTER-CONTEXT.md` §10 so any agent reads it
  during normal onboarding regardless of how a loop was started.
- **Decision record:** none yet in `docs/adr/` — this is a documentation/process
  change, not an architecture decision; §7 of `docs/CWL-MASTER-CONTEXT.md`
  ("Durable knowledge lives in the repo / Project / KG, NOT in an agent's
  private memory") is the binding convention this follows.
- **PR:** ContextualWisdomLab/.github#1429.

## What changed

- New file `docs/product-goal-directive.md`: the nine-section directive
  recorded verbatim (Korean, as authored), each section given a short English
  heading, plus a `/goal`-sized pointer text a future session can paste in
  instead of the full directive.
- `AGENTS.md`'s `<!-- CWL-ENTRY -->` read-first block, `CLAUDE.md`'s "Read
  first" section, and `docs/CWL-MASTER-CONTEXT.md` §10 ("Current state") each
  gained one linking sentence to the new file.

## Review findings and reconciliation (Devin Review, PR #1429)

Devin Review's automated pass on this PR raised two findings against the new
file, both confirmed valid and fixed in place (not by editing the verbatim
quoted directive text, which is meant to preserve the owner's own wording
unmodified):

1. **Missing traceability record.** The PR introduced a new standing policy
   (the `/goal`-pointer mechanism itself) without a `docs/doctoring/` entry,
   contradicting the pattern this repo already follows for standing-policy and
   infra changes (e.g. `docs/doctoring/contextual-orchestrator-vendored-sidecar.md`,
   `docs/doctoring/noema-orchestrator-free-zdr.md`). This file is that record.
2. **Naming section (§5) contradicts existing binding conventions.** The
   verbatim directive text (a) uses "wardnet" as an example of an "old name"
   to rename away from, when `docs/CWL-MASTER-CONTEXT.md` §3/§10 records
   `waf-ids-ai-soc` → **wardnet** as an already-completed rename — wardnet is
   the current canonical name, not a legacy one; and (b) says all DB names
   violating the snake_case convention "shall be replaced entirely," which
   contradicts `docs/CWL-MASTER-CONTEXT.md` §7's explicit grandfather clause,
   "DB object names = 2+ word snake_case (don't rename existing Camel/Pascal)."
   Read literally and combined with this org's stated "full autonomy, do not
   ask the user" convention, an agent following §5's wording alone could
   force-rename the wardnet product or existing database objects and violate
   the canonical schema/naming contract that a completed rename already
   established.

   Resolved per `docs/product-goal-directive.md`'s own stated conflict
   policy ("Where this directive and those documents conflict, resolve the
   conflict and update whichever document is wrong — do not silently pick
   one"): added a reconciliation note directly after §5's quoted text (not
   inside the quote) stating that `docs/CWL-MASTER-CONTEXT.md` §7 governs,
   that the snake_case rule applies to **new** DB objects only, and that
   wardnet must not be treated as a rename target.

## Follow-up findings (CodeRabbit, PR #1429)

CodeRabbit's automated pass raised two further findings, both verified and
fixed:

3. **Markdown lint (MD040).** The `/goal` pointer example's fenced code block
   had no language identifier. Changed the opening fence to ` ```text ` since
   the block is a command example, not executable code.
4. **Section 8 read as CI routing policy.** Section 8's quoted text describes
   `contextual-orchestrator`'s general auto-discovery capability across all
   five provider secrets — a product-level design principle, not CI routing
   policy. Read in isolation, an agent could mistake it for license to loosen
   which pool `OpenCode`/`Noema`/`Strix` route through. Added a note (not
   inside the quote) stating that pool/credential-scope routing is governed
   exclusively by `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`:
   `OpenCode`/`Noema` → fail-closed `orchestrator/free`; `Strix` →
   `orchestrator/auto`; private/internal targets require an attested
   ZDR-only catalog.

## Audit trail

- `docs/product-goal-directive.md` — the directive itself and the
  reconciliation note.
- `docs/CWL-MASTER-CONTEXT.md` §3, §7, §10 — the naming-history and DB-naming
  conventions this record reconciles against.
- ContextualWisdomLab/.github#1429 — the PR carrying this change and Devin
  Review's findings.

---

## 2026-09-02 revision: owner restated sections 1-9 in full

The owner sent the directive again, in full, expanding scope in several
places (i18n language list and translation-ledger architecture in §4; DDD/
ontology repo responsibilities in §5; a Rust-first escape-hatch policy in
§6; an unconditional p95≤20ms-per-page bar in §7; and, most substantially,
replacing §9's flat nine-library list with a ~25-repository core-owner /
consumer-boundary classification). `docs/product-goal-directive.md` §§1-9
were rewritten in place to the new verbatim text, per this file's own
stated update convention ("edit this file in place... do not fork a second
copy elsewhere").

The pre-2026-09-02 verbatim text (Korean, as authored, superseded by the
above) is preserved here for history:

### 1. Execution goal and continuous loop (pre-2026-09-02)

> 실행 목표와 지속 Loop 열린 PR마다 별도 중간 보고 없이 리뷰 확인→수정→GitHub Checks 재검증→병합→다음 개발을 반복하라. PRD를 읽고 Loop·Goal을 자율 생성·수정·제거해 PR을 병합 또는 0개로 만들며 상용화하라. 200억 달러에 판매할 자신이 있을 품질과 구매자가 체감할 제품 Gap 해소가 목표다. ADR·리서치·현행 데이터·PR로 기능 명세·PRD·TRD·UML·Gap·조치 상태를 도출해 docs/product-technical-gap-baseline.md에 갱신하라. 한 시간 간격으로 예약하고 메시지도 개선·갱신하라. PR·Issues 소진 후에도 제품 Gap 개발과 병합 Loop를 계속한다. 내가 온전히 소유한 ContextualWisdomLab 저장소를 레버리지 순으로 연계해 PR 병합·추가와 Connector 추가·수정 등 Ecosystem을 구축하라. Ecosystem 전 라이브러리 PRD를 숙지하고 조직·저장소명 대소문자를 지킨다. 리뷰·Checks 대기는 Blocker가 아니며, 실패 원인·수정·재실행 필요에 즉시 대응하며 안전한 작업을 계속한다. 결과 보고에 멈추지 말고 다음 Loop로 이동하라. 저장소는 이름이 아니라 제품 책임·재사용 경계·문서·구현·소비 저장소를 대조해 선택한다. ADR·Goal을 수시로 갱신하고 Goal 수정 불가 시 Loop를 갱신한다.

### 2. Concurrent operation, PR handling, and root-cause fixes (pre-2026-09-02)

> 동시 작업·PR 운영·근본 수정 원격 Agent의 동시 Commit·Push를 경합으로 단정해 Force Push·중단하지 말고 변경 취지·이유를 확인해 이어간다. Commit·Push 전 병합 여부를 확인하고 삭제 근거를 남긴다. Self-modifying/Source-fix Workflow는 목적 달성 후 삭제하고 잔존 시 관찰·제거한다. 가능한 PR은 Stack하고 not-merge-ready를 merge-ready로 전환한다. 유관 프로젝트 원인이 엮이면 함께 처리하고 Stacked PR을 중앙 OpenCode Agent가 리뷰하지 않으면 ContextualWisdomLab/.github를 수정한다. Agent 간 대화·Spawn을 활용한다. 수동 해법은 모두 코드·설정에 반영한다. PYTHONPATH=. 누락은 설정하고 GitHub Actions·런타임 오류는 로그·Root Cause Analysis로 제거한다. 전체 GitHub Checks 실패를 확인·수정한다. ContextualWisdomLab 내부 라이브러리 문제라면 원시 공급자 오류까지 고쳐 PR한다. 개발 프로세스에 https://github.com/DietrichGebert/ponytail 및 https://github.com/obra/superpowers 를 사용하되 superpowers의 "무조건 질문" 규칙은 무시한다. https://github.com/tirth8205/code-review-graph 와 https://github.com/colbymchenry/codegraph 도 사용하고 인덱싱은 스스로 수행한다. 이는 명시적으로 허가됐다.

### 3. Research, standards, and documentation traceability (pre-2026-09-02)

> 연구·표준·문서 추적성 모든 개발은 최신 권위 국제 표준·논문을 조사해 APA 7th로 인용하고 doctoring에 기록하며 누락 근거를 보충한다. Local Zotero API가 되면 기존 자료를 읽거나 OA 논문을 추가한다. 논문·표준은 exact-head·전체 PR·내부 모듈·API에 모순 없이 결합하고 충돌을 수정한다. AGENTS.md, CLAUDE.md, ARCHITECTURE.md, CHANGELOG.md 등 ADR 문서를 상시 갱신하고 Core ERD, UML, PRD, TRD, user stories, storyboard, wireframes, Storybook inventory, security·test·operability baseline 및 필요한 그림을 포함한다. 릴리즈 가능하면 버전을 올려 배포하고 CHANGELOG.md를 갱신한다. GitHub.io를 언급하려면 페이지를 실제 출판한다.

### 4. UX/UI and customer-facing expression (pre-2026-09-02)

> UX·UI와 고객 표현 필요하면 Figma와 Storybook(https://github.com/storybookjs/storybook), https://github.com/nextlevelbuilder/ui-ux-pro-max-skill, https://github.com/local-over/Anti-Slop-UI 를 함께 쓴다. 반복 웹 객체는 디자인 토큰화·모듈화하고 Figma File ID를 ADR에 기록한다. Storybook 장면별·Edge case별 Event를 조사·구현한다. UX·UI는 반드시 스크린샷으로 검수하고 ui-ux-pro-max로 Accessibility, Touch & Interaction, Performance, Style Selection, Layout & Responsive, Typography & Color, Animation, Forms & Feedback, Navigation Patterns, Charts & Data를 정의·검토·반영·적용·감사한다. 내부 구현 경계를 고객 화면에 노출하지 않고 문구로 고객의 다음 행동을 돕는다. Frontend는 디자인 토큰 CSS, 버튼 Action Edge, Interaction UX, i18n 번역 일관성까지 테스트한다.

### 5. Architecture, naming, and database conventions (pre-2026-09-02)

> 아키텍처·명명·데이터베이스 소프트웨어는 중앙 .github, naruon, 다른 저장소와 연결 가능하게 만든다. DDD를 적용해 핵심·지원·일반 Subdomain, Bounded Context, Context Map, Ubiquitous Language를 ADR에 정의하고 Aggregate·Entity·Value Object·Domain Service·Repository·Domain Event·Invariant를 코드·API·DB·테스트에 일치시킨다. Aggregate는 최소 트랜잭션 경계로 두며 외부·레거시는 Anti-Corruption Layer로 격리하고 Shared Kernel은 최소화한다. 단독·반입 모듈 모두 우수한 모듈러 MSA를 지향하고 단일 소프트웨어가 Monolithic Architecture처럼 비대해지면 책임 경계에 따라 저장소를 분리한다. 소프트웨어명과 내부 호출자·클래스명이 다르거나 옛 이름(예: wardnet)을 쓰면 정식 이름으로 바꾼다. DB 객체명은 두 단어 이상의 snake case, Carmel case 또는 pascal case여야 하고 snake case를 우선한다. 위반명은 전부 치환한다. DB는 제3정규화와 Hot Partition 대비를 준수한다. Lock을 관리하고 불가하면 Read/Write DB를 분리한다. 영속화 경로의 항목별 UPSERT를 추적하고 없으면 계약을 보강한다. 명시적 구매자가 없는 제품은 코드 안팎의 Buyer를 정상 객체명으로 바꾼다. CSAP·SOC 2 인증을 고려한다. PII Masking이 업무를 마비시키므로 규정 준수형 비Masking 보호 대안을 설계한다. 실데이터 테스트·개발의 인명·기관명은 코드·ADR에서 익명화한다. GitHub Secrets의 PYPI API Key와 대부분 Public 배포라는 전제를 반영한다.

### 6. Implementation language, computation, and measurement principles (pre-2026-09-02)

> 구현 언어·연산·측정 원칙 Docstring Coverage, Test Coverage, Edge Case Test Coverage를 각각 100%로 만든다. 초보자가 별도 코드 분석 없이 이해할 수 있을 만큼 충분한 docstring을 제공한다. 수리과학, Psychometrics, Exploratory Data Analysis, 데이터과학의 모든 core 연산 레이어는 Python으로 구현하지 말고 무조건 Rust로 작성한다. Vector 연산, Linear Algebra, Matrix Algebra, LLM token size 연산도 포함한다. GPU와 CPU multithreaded 실행을 지원하고 context switching을 최소화한다. 속도·안정성·보안이 중요한 일반 소프트웨어도 Rust를 사용하며, 기존 타 언어 구현은 전환·리팩터링하거나 명확한 Rust API Call 경계로 분리한다. 확률표집 계약에는 표본 설계, 오차 목표, 실패 분모를 명시해 ADR과 감사 코드에 반영한다. Atomistic fallacy를 막도록 다층구조·다중소속 모델링을 고려·구현하고 시간 흐름을 반영하는 모델도 포함한다. 가중치는 임의로 정하지 말고 수리과학·Psychometrics에서 추정된 값, 특히 fast-mlsirm이나 TEPP처럼 논문 근거가 있는 모형을 사용한다. 어떠한 휴리스틱과 Rule of thumbs도 금지하며, 근거 미확정 상태로 방치하지 말고 ContextualWisdomLab의 추론 엔진을 최대한 활용하고 SOLID 원칙을 지킨다. Deprecation Warning은 Suppression하지 말고 근본 문제를 해결한다. 합성 데모 데이터는 Unit test에는 쓸 수 있으나 Production에 반영하지 않는다. Python 웹 서버는 Multithreading을 지원하고 GIL이 문제면 Python 3.14를 사용한다.

### 7. Realistic verification, load, and container testing (pre-2026-09-02)

> 현실성 있는 검증과 부하·컨테이너 테스트는 제품 특성에 맞는 현실 사례와 정확성 기준을 포함한다. Psychometrics는 true parameter 대비 estimation RMSE와 true parameter 추정 재현성을 검증하고, 음악 분석은 실제 음원이 기대 분석값을 내는지 확인한다. 웹을 지원하면 Asynchronous 처리를 구현해 무응답을 방지하고 k6 end-to-end load test로 동시 접속 능력과 병목을 측정·개선한다. close_connection을 인스턴스 속성으로만 가정하는 잠재 버그를 점검한다. Docker는 Podman 또는 colima로 대체할 수 있다. 컨테이너 병목이면 shm_size와 PostgreSQL 등 응용 설정을 하드웨어에 맞게 자동 튜닝한다. 주로 compose로 운영해 k8s 전환성을 확보한다. Docker container 프로젝트명은 고정하되 테스트 격리 때만 override하고 달성 후 격리 컨테이너를 제거한다. MLX·CPU·CUDA·OpenCL의 Docker/Podman/Colima 처리법을 ADR에 기록·반영하고 Native Module 분리가 필요하면 독립 서비스로 개발한다.

### 8. LLM, orchestration, and embedding (pre-2026-09-02)

> LLM·오케스트레이션·Embedding LLM이 필요한 테스트는 contextual-orchestrator 기반 OpenCode Agent로 만든다. contextual-orchestrator는 GitHub Secrets의 BYTEZ_API_KEY, NVIDIA_NIM_API_KEY, NVIDIA_NIM_API_KEY_SUB, OPENROUTER_API_KEY, OPENAI_API_KEY를 모두 써 auto model discovery로 최적 모형을 제공한다. embedding·responses·completions, audio, video, image, ommi-modal 등 가용 모델을 폭넓게 지원한다. 가능하면 반입해 쓰고 발견한 해당 저장소 문제도 함께 수정한다. LLM 사용 소프트웨어와 contextual-orchestrator는 Fugu·Conductor·TRINITY 연구를 근거로 단일 모델 라우팅과 심층 다중 Agent 오케스트레이션 사이의 계산량을 배분한다. 워크플로 단계, 재귀 깊이, 작업 분해, 접근 목록으로 test-time compute를 조절하고 역할별 reasoning effort를 다르게 하며 추론 수준 ablation을 수행한다. 속도는 핵심 고려사항이 아니며 정확성을 우선한다. 중앙 OpenCode, Strix, Noema는 모델당 두 시간 이상 걸릴 수 있음을 수용한다. LLM Chat model은 chat completion API와 responses API를 모두 지원하고 json_object와 json_schema를 모두 처리한다. Embedding은 문단·구문·DOM·송수신자 등 의미 단위를 식별해 chunking한다. 본문에 base64 이미지가 있으면 텍스트 인식, 객체 인식, 태그 설명, 이미지 별도 검색 방법을 연구 근거와 함께 DB 설계에 넣고 원래 삽입 위치를 보존해 그림 맥락까지 검색·표현한다. GitHub Actions scheduler는 contextual-orchestrator 기반 OpenCode Agent로 전환한다. COPILOT_GITHUB_TOKEN은 쓰지 않고 기존 리뷰 Agent 키 체계를 유지한다.

### 9. Reference libraries, tool invocations, and ecosystem repositories (pre-2026-09-02)

> 참고 라이브러리와 호출 @Superpowers @GitHub @Figma @Visualize @Context7 @Product Design @Consensus를 활용한다.

- **TEPP** — https://github.com/ContextualWisdomLab/TEPP — 다국어·시간·관계 측정용 Temporal Event Psychometrics Platform이며 통계·심리측정 산술은 Rust로 구현한다.
- **contextual-orchestrator** — https://github.com/ContextualWisdomLab/contextual-orchestrator — 논문 근거의 contextual model orchestration lab·enterprise admin design.
- **fast-mlsirm** — https://github.com/ContextualWisdomLab/fast-mlsirm — simple-structure MLSIRM/MLS2PLM은 Jeon, Jin, Schweinberger, and Baugh(2021), Kang and Jeon(2025), Molenaar and Jeon(2026)을 따른다.
- **keyverse** — https://github.com/ContextualWisdomLab/keyverse — Keycloak 기반 독립 컴포넌트(Apache-2.0)이자 ContextualWisdom ecosystem 중앙 Identity Provider.
- **RankWeave** — https://github.com/ContextualWisdomLab/RankWeave — Python 3.10+용 무의존성·저장소 비종속 retrieval fusion/evaluation/statistical comparison/tuning/TREC benchmarking/auditable CLI workflow.
- **ThreadWeave** — https://github.com/ContextualWisdomLab/ThreadWeave — runtime dependency 없는 Python용 표준 기반 JWZ/RFC 5256 이메일 reference threading.
- **disksage** — https://github.com/ContextualWisdomLab/disksage — Windows/Linux/macOS 디스크 공간 관리자.
- **wardnet** — https://github.com/ContextualWisdomLab/wardnet — ContextualWisdomLab Rust-first gateway·SOC control-plane baseline.
- **LineageWeave** — https://github.com/ContextualWisdomLab/LineageWeave — 명시적 선후행 링크 없는 짧은 timestamped record에서 git-branch식 lineage DAG를 재구성한다. 수리 연산은 소관이 아니므로 다른 라이브러리로 이관한다.

(§10, provider pool pinning, was added 2026-09-02 same day as a new section and is unaffected by this
revision — see `docs/product-goal-directive.md` §10 directly.)

### Why no new reconciliation note was needed this round

Unlike the 2026-08-30 revision, this pass's §5 no longer names `wardnet` as an "old name" example (the
specific defect the 2026-08-30 reconciliation corrected), so that note is retired as no-longer-applicable
to the current text. The DB-naming force-rename ambiguity ("위반명은 치환한다") persists in the new
wording and its reconciliation note was carried forward, updated for the new surrounding sentence. No
Devin/CodeRabbit review pass had run against this specific revision at the time of writing; if one
surfaces a new finding against the 2026-09-02 text, record it as a further dated entry here, not by
editing this history section.

## 2026-09-02 second revision (same day): sections 1-9 restated again

The owner sent the directive a third time overall (second time on 2026-09-02 itself), a
tightening/condensation pass over the first 2026-09-02 restatement. It also carries genuine new
content, most notably: an explicit "repair finding, not Close" PR-lifecycle policy inserted into §2; a
resolved role split between `enterprise-architecture-core` and `context-graph-contracts` in §9 (they no
longer share one undifferentiated claimed role — this directly answers a gap this session's own 28-repo
survey had just flagged in `docs/product-technical-gap-baseline.md`); a regrouping of
`EmbedRelay`/`appguardrail`/`wardnet` into more specific individual responsibilities in §9; and new
consumer-boundary-protection mechanics (port/ACL/feature-flag/test-double; never read an owner repo's
source/DB/temp branch directly) appended to §9's closing paragraph. `docs/product-goal-directive.md`
§§1-9 were rewritten in place to this newest verbatim text, with inline reconciliation notes added per
section documenting each genuine delta (not mere rewording) found against the first-pass 2026-09-02
text. See that file directly for the current text and notes.

The first-pass 2026-09-02 verbatim text (Korean, as authored, superseded by the above) is preserved here
for history:

### 1. Execution goal and continuous loop (2026-09-02 first pass)

> 실행 목표와 지속 Loop 열린 PR마다 보고 없이 리뷰→수정→Checks 재검증→병합→다음 개발을 반복하라. PRD로 Loop·Goal을 조정해 PR을 병합하거나 0개로 만들며 상용화한다. 목표는 200억 달러 판매 품질과 고객 체감 Gap 해소다. ADR·리서치·현행 데이터·PR에서 PRD·TRD·UML·Gap·조치를 도출해 docs/product-technical-gap-baseline.md에 갱신하라. 매시간 예약 메시지를 개선한다. PR·Issues 소진 뒤에도 Gap 개발·병합과 ContextualWisdomLab 저장소·Connector 연계를 계속한다. 전 라이브러리 PRD와 조직·저장소명 대소문자를 지킨다. 리뷰·Checks 대기는 Blocker가 아니다. 실패를 즉시 수정·재실행하고 다른 안전한 일을 계속한다. 저장소는 책임·재사용 경계·구현·소비 관계로 고르고 ADR·Goal·Loop를 갱신한다.

### 2. Concurrent operation, PR handling, and root-cause fixes (2026-09-02 first pass)

> 동시 작업·PR 운영·근본 수정 동시 Commit·Push를 경합으로 단정하거나 Force Push·중단하지 말고 취지를 이어간다. Commit 전 병합·삭제 근거를 기록하고 목적을 마친 Self-modifying/Source-fix Workflow는 삭제한다. PR은 Stack해 merge-ready로 만들고 유관 원인도 처리한다. Stacked PR의 OpenCode 리뷰가 빠지면 .github를 고친다. Agent 간 대화·Spawn을 쓴다. 수동 해법은 코드·설정화한다. PYTHONPATH=.·Actions·runtime 오류는 로그 RCA로 제거한다. 내부 문제는 canonical owner·원시 공급자까지 고친다. 필요한 core가 미성숙해도 consumer에서 복제·우회·제외하지 말고 owner에 RED test·계약·기능·문서·release를 개발해 통합 CI GREEN 후 versioned release로 연결한다. 경계가 틀리거나 공통 수요가 없을 때만 ADR 근거로 제외한다. DietrichGebert/ponytail·obra/superpowers를 쓰되 "무조건 질문"은 무시한다. tirth8205/code-review-graph·colbymchenry/codegraph도 인덱싱한다. 한국어 문구·문서·번역은 https://github.com/epoko77-ai/im-not-ai로 의미·사실·수치·고유명사를 보존하며 윤문한다.

### 3. Research, standards, and documentation traceability (2026-09-02 first pass)

> 연구·표준·문서 추적성 최신 권위 표준·논문을 조사해 APA 7th로 인용하고 doctoring에 남긴다. Local Zotero API가 되면 기존 자료나 OA 논문을 보강한다. 근거는 늘 exact-head·PR·모듈·API에 연결하고 충돌을 고친다. AGENTS.md·CLAUDE.md·ARCHITECTURE.md·CHANGELOG.md·ADR, ERD·UML·PRD·TRD·user story·storyboard·wireframe·Storybook·security/test/operability baseline을 갱신한다. 릴리즈 가능하면 버전·CHANGELOG를 올려 배포하고 GitHub.io는 실제 출판한다. 의사결정은 맥락을 잊거나 처음 보는 사람도 문제·제약·대안·선택/기각 이유·근거·위험·효과·후속 조치를 재구성하도록 구체적이고 자세히 기록한다. 결론·전제를 생략하지 말고 사용자·운영·장애 장면이 떠오를 사례와 증거를 exact-head·로그·이슈·PR·ADR·실험에 연결해 다른 Agent가 검증·계속하게 한다.

### 4. UX/UI, i18n, and customer-facing expression (2026-09-02 first pass)

> UX·UI·i18n과 고객 표현 Figma·Storybook·ui-ux-pro-max·Anti-Slop-UI를 쓴다. UI는 모두 재사용 객체이고 페이지는 조합으로 만든다. token·Figma ID를 ADR에 남긴다. Storybook에서 정상·로딩·빈·오류·권한·반응형·상호작용 상태를 격리 개발·문서화하고 스크린샷·E2E로 접근성·터치·성능·타이포그래피·색상·폼·탐색·차트를 감사한다. shadcn/ui는 component source로 Storybook과 대체 관계가 아니다. Frontend stack은 고정하지 않으며 React·Vite·shadcn/ui·jQuery 4 등은 보안·유지보수·표준·접근성·성능을 충족할 때 쓴다. 내부 경계를 숨기고 다음 행동을 안내한다. Keyverse는 인증 backend로 유지하되(Direct Grant/ROPC 또는 Keycloak REST API), 로그인·가입·복구는 제품 자체 form으로 만든다. token CSS·Action Edge·Interaction UX를 검증한다. i18n은 한국어·영어·일본어·중국어·베트남어·스페인어·독일어·프랑스어를 지원한다. UI 폭·줄바꿈·CJK·텍스트 팽창·font fallback·locale 형식을 고려하고 언어별 Storybook·E2E로 잘림·겹침·의미 축약을 막는다. 번역 원장은 파일·JS bundle이 아닌 DB의 versioned resource다. server/native가 화면 key만 조회·cache하며 browser에 전체 catalog·무거운 i18n JavaScript를 싣지 않고 SPA를 전제하지 않는다. 공통 관리 제품이 없으면 새 저장소를 만들어 제품별 번역·검토·승인·배포·rollback API·관리 UI를 제공한다.

### 5. Architecture, ontology, naming, and database conventions (2026-09-02 first pass)

> 아키텍처·온톨로지·명명·데이터베이스 DDD의 Subdomain·Bounded Context·Context Map·Ubiquitous Language와 Aggregate·Entity·Value Object·Domain Service·Repository·Domain Event·Invariant를 ADR·코드·API·DB·test에 일치시킨다. Aggregate는 최소 transaction 경계로 두고 외부·legacy는 ACL로 격리하며 Shared Kernel을 최소화한다. 모듈러 MSA를 지향하고 비대한 Monolith는 책임별로 분리하며 옛 이름을 고친다. 통합 온톨로지는 ConceptWeave가 observe→discover→propose→align→validate→review→publish와 semantic release를, semantic-data-portal이 catalog·governance·소비를, context-graph-contracts가 상호운용 계약을, enterprise-architecture-core가 Context Map·결정을 맡는다. domain truth·Ubiquitous Language는 제품 owner에 남긴다. 개념·관계·dimension·measure·mapping은 evidence·provenance·validity·confidence·status·deprecation·locale label을 가진 immutable release로 배포한다. consumer는 released API/contract·ACL만 쓰고 파일 복사·cross-service SQL·미승인 publication을 금지한다. UI 번역과 ontology label의 원장은 분리한다. 변수·상수·매개변수·필드·함수·메서드·클래스·타입·모듈·패키지·API·DB 객체·파일·디렉터리는 두 단어 이상 snake_case·camelCase·PascalCase로 명명하고 snake_case를 우선한다. 언어·framework·외부 계약 관례는 경계에서 변환하고 위반명은 치환한다. DB는 3NF·Hot Partition 대비·Lock·필요시 Read/Write 분리·항목별 UPSERT를 지킨다. placeholder Buyer는 실제 도메인명으로 바꾼다. CSAP·SOC 2를 고려한다. PII Masking이 업무를 마비시키면 준수형 비Masking 대안을 설계한다. 실데이터 인명·기관명은 익명화하고 PYPI API Key·Public 배포 전제를 반영한다.

### 6. Implementation language, computation, and measurement principles (2026-09-02 first pass)

> 구현 언어·연산·측정 원칙 Docstring·Test·Edge Case Coverage는 각 100%이고 초보자도 이해하게 쓴다. 수리과학·Psychometrics·EDA·데이터과학 core와 성능·안정성·보안 runtime은 Rust가 기본이다. Vector·Linear/Matrix Algebra·token size·GPU·CPU multithreading을 포함한다. Python은 비선호이며 LLM 편의·관성으로 고르지 않는다. 검증된 ML runtime이 Python 전용이고 Rust 대안이 기능·정확성·지원성을 못 맞출 때만 그 부분에 쓴다. 경계·근거·제거 조건을 ADR에 남기고 hot path는 Rust로 둔다. 확률표집은 설계·오차 목표·실패 분모를 명시한다. Atomistic fallacy 방지를 위해 다층·다중소속·시간을 모델링한다. 가중치는 fast-mlsirm·TEPP 등 논문 근거 모형에서 추정한다. 휴리스틱을 금지하고 미확정 근거는 추론 엔진과 SOLID로 해결한다. Deprecation Warning은 근본 해결한다. 합성 data는 Unit test에만 쓴다. 불가피한 Python web server는 multithreading을 지원하고 GIL 문제는 Python 3.14 또는 Rust로 푼다.

### 7. Realistic verification, load, and container testing (2026-09-02 first pass)

> 현실성 있는 검증과 부하·컨테이너 테스트는 현실 사례와 제품별 정확성 기준을 포함한다. Psychometrics는 true parameter 대비 estimation RMSE·추정 재현성을, 음악 분석은 실제 음원의 기대 분석값을 검증한다. 웹은 비동기 처리·k6 E2E를 적용하고 모든 페이지 p95≤20ms를 요구한다. 초과하면 알고리즘·query·I/O·rendering을 profile하고 runtime·언어·framework가 원인이면 계약·정확성을 보존해 Rust 우선 기술·hot path·개발 언어를 바꾼다. 표본 축소·측정 제외·비현실적 cache warm-up을 금지한다. JavaScript bundle·heap·DOM·hydration·main thread·GC가 메모리·지연을 키우면 dependency·Frontend stack을 교체한다. close_connection도 점검한다. Docker는 Podman·colima로 대체 가능하다. 병목이면 shm_size·PostgreSQL을 hardware에 맞춰 튜닝한다. compose로 k8s 전환성을 지키고 프로젝트명은 test 격리 때만 override한다. MLX·CPU·CUDA·OpenCL 처리법을 ADR에 반영하고 Native Module은 필요시 독립 service로 분리한다.

### 8. LLM, orchestration, and embedding (2026-09-02 first pass)

> LLM·오케스트레이션·Embedding LLM 작업은 contextual-orchestrator 기반 Agent로 만든다. `orchestrator/free` 고정. BYTEZ_API_KEY·NVIDIA_NIM_API_KEY·NVIDIA_NIM_API_KEY_SUB·OPENROUTER_API_KEY·OPENAI_API_KEY로 auto discovery해 embedding·responses·completions·audio·video·image·omni-modal을 지원한다. 소스·adapter는 복사하지 않고 released API·client·schema로 연결한다. .github reusable workflow와 얇은 owner·consumer caller로 통합 CI를 구성한다. PR·release·consumer 변경마다 exact SHA로 build·contract·API/schema·E2E·fallback·streaming·structured output·timeout·security·SBOM·provenance를 검증한다. 결함은 owner에서 RED→fix→GREEN→release한 뒤 consumer version을 올린다. mutable sibling head·branch URL·cross-repo path·workflow 복제를 금지한다. 임시 bridge는 owner issue·만료·삭제 조건을 ADR·CI에 둔다. Provider group명은 하드코딩하지 않는다. 별칭일 뿐이며 modality·context·reasoning·tool·structured output·streaming·가격·지연·가용성·정확도 등 검증된 특성으로 선택·fallback한다. Model timeout은 공통 상한 없이 기본값을 무제한(null)로 둔다. 통신 장애는 upstream provider timeout·오류로 끝난다. 관리자 Web에서 모델별 조회·설정·해제·복원, 단위·우선순위·상속·검증·감사·API를 제공하고 설정된 모델만 제한한다. reasoning·streaming·tool call을 경과시간만으로 끊지 않으며 사용자 취소·provider 종료·관리자 timeout을 구분한다. Fugu·Conductor·TRINITY 근거로 단일·다중 Agent의 test-time compute를 단계·재귀·분해·접근·역할별 effort로 배분·ablation한다. 정확성을 우선하고 OpenCode·Strix·Noema의 모델당 2시간 이상을 수용한다. Chat은 completions·responses와 json_object·json_schema를 지원한다. Embedding은 의미 단위로 나누며 base64 이미지 인식·검색·삽입 위치·맥락을 보존한다.

### 9. Core foundation and development/consumption boundary (2026-09-02 first pass)

> Core foundation과 개발·사용 경계 @Superpowers @GitHub @Figma @Visualize @Context7 @Product Design @Consensus를 쓴다. 매 실행 README·PRD·ARCHITECTURE·release에서 책임을 확인한다. core는 완성도가 아닌 반복 수요·권위·재사용 경계로 정하고 미완성이면 owner에서 완성·release한다. transient head는 production에 쓰지 않는다.
>    * .github — workflow·review/security/release owner이며 ruleset·얇은 workflow_call로만 쓴다.
>    * enterprise-architecture-core·context-graph-contracts — 전사 결정·versioned context 계약 원장이며 runtime·제품 DB는 제외한다.
>    * ConceptWeave·semantic-data-portal — ontology 생성·publish와 catalog·governance·소비를 분담한다.
>    * contextual-orchestrator·noema — 모델 orchestration과 GitHub OIDC 단기 권한·exact-head evidence를 분담한다.
>    * keyverse — identity 원장. 제품은 OIDC/OAuth·SCIM·자체 form을 쓰고 table은 복제하지 않는다.
>    * EgressWeave·OriginWeave·pingora-gateway·quarantine-sandbox-runtime — outbound·browser·edge·격리 core이며 부족한 기능은 owner에서 완성한다.
>    * pg-llm-batch·EmbedRelay — batch/token과 embedding identity·vector migration owner다.
>    * fast-mlsirm·TEPP — IRT/MLSIRM과 다국어·시간·event·relation 측정 owner이며 kernel 재구현을 금지한다.
>    * RankWeave·ThreadWeave — retrieval fusion/evaluation/TREC와 JWZ/RFC 5256 threading owner다.
>    * inkspan·DiagramWeave — editor/serialization과 diagram patch/render/CLI/LSP package다.
>    * mhtml-etl-gateway — MHTML 검사·schema proposal·load·lineage owner다.
>    * appguardrail·wardnet — SAST/SARIF와 Rust gateway/SOC baseline owner이며 범위를 과장하지 않는다. naruon·LineageWeave·psychometrics-commons·disksage·PolicyWeave·CalendarWeave·supply-chain-control-plane은 완성도가 아니라 domain product/composition consumer라 분류한다. 공통 기능은 core owner로 추출해 통합 CI로 개발한다.

(§10, provider pool pinning, predates this pass and is unaffected by it — see
`docs/product-goal-directive.md` §10 directly for its current text and reading notes.)

### Why this round's deltas were recorded inline, not just here

Unlike the previous round, several of this pass's changes are substantive enough (the §2 repair-finding
policy; the §9 role split, regrouping, and boundary-protection addition) that recording them only as a
before/after diff here would bury operationally load-bearing content in a history file. Each affected
section in `docs/product-goal-directive.md` therefore carries its own dated reconciliation note
explaining exactly what changed and why it matters, with this history entry serving only as the
complete verbatim record of what the text looked like immediately before this round.
