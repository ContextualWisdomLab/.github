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
