# Product goal directive — autonomous PR/merge/development loop

**Status:** active standing directive · **Owner intent recorded:** 2026-08-30 · **Scope:** the full
ContextualWisdomLab ecosystem (every repo an agent can reach from this org, leveraged in order of
product responsibility / reuse boundary / docs / implementation / consumption — not by name).

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

The directive is recorded verbatim (Korean, as authored) in the nine sections below, each given a short
English heading for navigability. Do not paraphrase or shorten these sections when copying them
elsewhere; link to this file instead.

## 1. Execution goal and continuous loop

> 실행 목표와 지속 Loop 열린 PR마다 별도 중간 보고 없이 리뷰 확인→수정→GitHub Checks 재검증→병합→다음 개발을 반복하라. PRD를 읽고 Loop·Goal을 자율 생성·수정·제거해 PR을 병합 또는 0개로 만들며 상용화하라. 200억 달러에 판매할 자신이 있을 품질과 구매자가 체감할 제품 Gap 해소가 목표다. ADR·리서치·현행 데이터·PR로 기능 명세·PRD·TRD·UML·Gap·조치 상태를 도출해 docs/product-technical-gap-baseline.md에 갱신하라. 한 시간 간격으로 예약하고 메시지도 개선·갱신하라. PR·Issues 소진 후에도 제품 Gap 개발과 병합 Loop를 계속한다. 내가 온전히 소유한 ContextualWisdomLab 저장소를 레버리지 순으로 연계해 PR 병합·추가와 Connector 추가·수정 등 Ecosystem을 구축하라. Ecosystem 전 라이브러리 PRD를 숙지하고 조직·저장소명 대소문자를 지킨다. 리뷰·Checks 대기는 Blocker가 아니며, 실패 원인·수정·재실행 필요에 즉시 대응하며 안전한 작업을 계속한다. 결과 보고에 멈추지 말고 다음 Loop로 이동하라. 저장소는 이름이 아니라 제품 책임·재사용 경계·문서·구현·소비 저장소를 대조해 선택한다. ADR·Goal을 수시로 갱신하고 Goal 수정 불가 시 Loop를 갱신한다.

## 2. Concurrent operation, PR handling, and root-cause fixes

> 동시 작업·PR 운영·근본 수정 원격 Agent의 동시 Commit·Push를 경합으로 단정해 Force Push·중단하지 말고 변경 취지·이유를 확인해 이어간다. Commit·Push 전 병합 여부를 확인하고 삭제 근거를 남긴다. Self-modifying/Source-fix Workflow는 목적 달성 후 삭제하고 잔존 시 관찰·제거한다. 가능한 PR은 Stack하고 not-merge-ready를 merge-ready로 전환한다. 유관 프로젝트 원인이 엮이면 함께 처리하고 Stacked PR을 중앙 OpenCode Agent가 리뷰하지 않으면 ContextualWisdomLab/.github를 수정한다. Agent 간 대화·Spawn을 활용한다. 수동 해법은 모두 코드·설정에 반영한다. PYTHONPATH=. 누락은 설정하고 GitHub Actions·런타임 오류는 로그·Root Cause Analysis로 제거한다. 전체 GitHub Checks 실패를 확인·수정한다. ContextualWisdomLab 내부 라이브러리 문제라면 원시 공급자 오류까지 고쳐 PR한다. 개발 프로세스에 https://github.com/DietrichGebert/ponytail 및 https://github.com/obra/superpowers 를 사용하되 superpowers의 "무조건 질문" 규칙은 무시한다. https://github.com/tirth8205/code-review-graph 와 https://github.com/colbymchenry/codegraph 도 사용하고 인덱싱은 스스로 수행한다. 이는 명시적으로 허가됐다.

## 3. Research, standards, and documentation traceability

> 연구·표준·문서 추적성 모든 개발은 최신 권위 국제 표준·논문을 조사해 APA 7th로 인용하고 doctoring에 기록하며 누락 근거를 보충한다. Local Zotero API가 되면 기존 자료를 읽거나 OA 논문을 추가한다. 논문·표준은 exact-head·전체 PR·내부 모듈·API에 모순 없이 결합하고 충돌을 수정한다. AGENTS.md, CLAUDE.md, ARCHITECTURE.md, CHANGELOG.md 등 ADR 문서를 상시 갱신하고 Core ERD, UML, PRD, TRD, user stories, storyboard, wireframes, Storybook inventory, security·test·operability baseline 및 필요한 그림을 포함한다. 릴리즈 가능하면 버전을 올려 배포하고 CHANGELOG.md를 갱신한다. GitHub.io를 언급하려면 페이지를 실제 출판한다.

## 4. UX/UI and customer-facing expression

> UX·UI와 고객 표현 필요하면 Figma와 Storybook(https://github.com/storybookjs/storybook), https://github.com/nextlevelbuilder/ui-ux-pro-max-skill, https://github.com/local-over/Anti-Slop-UI 를 함께 쓴다. 반복 웹 객체는 디자인 토큰화·모듈화하고 Figma File ID를 ADR에 기록한다. Storybook 장면별·Edge case별 Event를 조사·구현한다. UX·UI는 반드시 스크린샷으로 검수하고 ui-ux-pro-max로 Accessibility, Touch & Interaction, Performance, Style Selection, Layout & Responsive, Typography & Color, Animation, Forms & Feedback, Navigation Patterns, Charts & Data를 정의·검토·반영·적용·감사한다. 내부 구현 경계를 고객 화면에 노출하지 않고 문구로 고객의 다음 행동을 돕는다. Frontend는 디자인 토큰 CSS, 버튼 Action Edge, Interaction UX, i18n 번역 일관성까지 테스트한다.

## 5. Architecture, naming, and database conventions

> 아키텍처·명명·데이터베이스 소프트웨어는 중앙 .github, naruon, 다른 저장소와 연결 가능하게 만든다. DDD를 적용해 핵심·지원·일반 Subdomain, Bounded Context, Context Map, Ubiquitous Language를 ADR에 정의하고 Aggregate·Entity·Value Object·Domain Service·Repository·Domain Event·Invariant를 코드·API·DB·테스트에 일치시킨다. Aggregate는 최소 트랜잭션 경계로 두며 외부·레거시는 Anti-Corruption Layer로 격리하고 Shared Kernel은 최소화한다. 단독·반입 모듈 모두 우수한 모듈러 MSA를 지향하고 단일 소프트웨어가 Monolithic Architecture처럼 비대해지면 책임 경계에 따라 저장소를 분리한다. 소프트웨어명과 내부 호출자·클래스명이 다르거나 옛 이름(예: wardnet)을 쓰면 정식 이름으로 바꾼다. DB 객체명은 두 단어 이상의 snake case, Carmel case 또는 pascal case여야 하고 snake case를 우선한다. 위반명은 전부 치환한다. DB는 제3정규화와 Hot Partition 대비를 준수한다. Lock을 관리하고 불가하면 Read/Write DB를 분리한다. 영속화 경로의 항목별 UPSERT를 추적하고 없으면 계약을 보강한다. 명시적 구매자가 없는 제품은 코드 안팎의 Buyer를 정상 객체명으로 바꾼다. CSAP·SOC 2 인증을 고려한다. PII Masking이 업무를 마비시키므로 규정 준수형 비Masking 보호 대안을 설계한다. 실데이터 테스트·개발의 인명·기관명은 코드·ADR에서 익명화한다. GitHub Secrets의 PYPI API Key와 대부분 Public 배포라는 전제를 반영한다.

## 6. Implementation language, computation, and measurement principles

> 구현 언어·연산·측정 원칙 Docstring Coverage, Test Coverage, Edge Case Test Coverage를 각각 100%로 만든다. 초보자가 별도 코드 분석 없이 이해할 수 있을 만큼 충분한 docstring을 제공한다. 수리과학, Psychometrics, Exploratory Data Analysis, 데이터과학의 모든 core 연산 레이어는 Python으로 구현하지 말고 무조건 Rust로 작성한다. Vector 연산, Linear Algebra, Matrix Algebra, LLM token size 연산도 포함한다. GPU와 CPU multithreaded 실행을 지원하고 context switching을 최소화한다. 속도·안정성·보안이 중요한 일반 소프트웨어도 Rust를 사용하며, 기존 타 언어 구현은 전환·리팩터링하거나 명확한 Rust API Call 경계로 분리한다. 확률표집 계약에는 표본 설계, 오차 목표, 실패 분모를 명시해 ADR과 감사 코드에 반영한다. Atomistic fallacy를 막도록 다층구조·다중소속 모델링을 고려·구현하고 시간 흐름을 반영하는 모델도 포함한다. 가중치는 임의로 정하지 말고 수리과학·Psychometrics에서 추정된 값, 특히 fast-mlsirm이나 TEPP처럼 논문 근거가 있는 모형을 사용한다. 어떠한 휴리스틱과 Rule of thumbs도 금지하며, 근거 미확정 상태로 방치하지 말고 ContextualWisdomLab의 추론 엔진을 최대한 활용하고 SOLID 원칙을 지킨다. Deprecation Warning은 Suppression하지 말고 근본 문제를 해결한다. 합성 데모 데이터는 Unit test에는 쓸 수 있으나 Production에 반영하지 않는다. Python 웹 서버는 Multithreading을 지원하고 GIL이 문제면 Python 3.14를 사용한다.

## 7. Realistic verification, load, and container testing

> 현실성 있는 검증과 부하·컨테이너 테스트는 제품 특성에 맞는 현실 사례와 정확성 기준을 포함한다. Psychometrics는 true parameter 대비 estimation RMSE와 true parameter 추정 재현성을 검증하고, 음악 분석은 실제 음원이 기대 분석값을 내는지 확인한다. 웹을 지원하면 Asynchronous 처리를 구현해 무응답을 방지하고 k6 end-to-end load test로 동시 접속 능력과 병목을 측정·개선한다. close_connection을 인스턴스 속성으로만 가정하는 잠재 버그를 점검한다. Docker는 Podman 또는 colima로 대체할 수 있다. 컨테이너 병목이면 shm_size와 PostgreSQL 등 응용 설정을 하드웨어에 맞게 자동 튜닝한다. 주로 compose로 운영해 k8s 전환성을 확보한다. Docker container 프로젝트명은 고정하되 테스트 격리 때만 override하고 달성 후 격리 컨테이너를 제거한다. MLX·CPU·CUDA·OpenCL의 Docker/Podman/Colima 처리법을 ADR에 기록·반영하고 Native Module 분리가 필요하면 독립 서비스로 개발한다.

## 8. LLM, orchestration, and embedding

> LLM·오케스트레이션·Embedding LLM이 필요한 테스트는 contextual-orchestrator 기반 OpenCode Agent로 만든다. contextual-orchestrator는 GitHub Secrets의 BYTEZ_API_KEY, NVIDIA_NIM_API_KEY, NVIDIA_NIM_API_KEY_SUB, OPENROUTER_API_KEY, OPENAI_API_KEY를 모두 써 auto model discovery로 최적 모형을 제공한다. embedding·responses·completions, audio, video, image, ommi-modal 등 가용 모델을 폭넓게 지원한다. 가능하면 반입해 쓰고 발견한 해당 저장소 문제도 함께 수정한다. LLM 사용 소프트웨어와 contextual-orchestrator는 Fugu·Conductor·TRINITY 연구를 근거로 단일 모델 라우팅과 심층 다중 Agent 오케스트레이션 사이의 계산량을 배분한다. 워크플로 단계, 재귀 깊이, 작업 분해, 접근 목록으로 test-time compute를 조절하고 역할별 reasoning effort를 다르게 하며 추론 수준 ablation을 수행한다. 속도는 핵심 고려사항이 아니며 정확성을 우선한다. 중앙 OpenCode, Strix, Noema는 모델당 두 시간 이상 걸릴 수 있음을 수용한다. LLM Chat model은 chat completion API와 responses API를 모두 지원하고 json_object와 json_schema를 모두 처리한다. Embedding은 문단·구문·DOM·송수신자 등 의미 단위를 식별해 chunking한다. 본문에 base64 이미지가 있으면 텍스트 인식, 객체 인식, 태그 설명, 이미지 별도 검색 방법을 연구 근거와 함께 DB 설계에 넣고 원래 삽입 위치를 보존해 그림 맥락까지 검색·표현한다. GitHub Actions scheduler는 contextual-orchestrator 기반 OpenCode Agent로 전환한다. COPILOT_GITHUB_TOKEN은 쓰지 않고 기존 리뷰 Agent 키 체계를 유지한다.

## 9. Reference libraries, tool invocations, and ecosystem repositories

> 참고 라이브러리와 호출 @Superpowers @GitHub @Figma @Visualize @Context7 @Product Design @Consensus를 활용한다.

- **TEPP** — https://github.com/ContextualWisdomLab/TEPP — 다국어·시간·관계 측정용 Temporal Event Psychometrics Platform이며 통계·심리측정 산술은 Rust로 구현한다.
- **contextual-orchestrator** — https://github.com/ContextualWisdomLab/contextual-orchestrator — 논문 근거의 contextual model orchestration lab·enterprise admin design.
- **fast-mlsirm** — https://github.com/ContextualWisdomLab/fast-mlsirm — simple-structure MLSIRM/MLS2PLM은 Jeon, Jin, Schweinberger, and Baugh(2021), Kang and Jeon(2025), Molenaar and Jeon(2026)을 따른다. 인접 화면: Angoff delta-plot DIF(docs/delta_plot_dif.md), Bradley–Terry MM ranking(docs/bradley_terry_mm.md). 주요 인용·결정: docs/traceability/research-basis.md, docs/adr/README.md. 점수 해석·공정성은 AERA·APA·NCME(2014)를 따르며 이는 CWE/OWASP/NIST 통제가 아니다.
- **keyverse** — https://github.com/ContextualWisdomLab/keyverse — Keycloak 기반 독립 컴포넌트(Apache-2.0)이자 ContextualWisdom ecosystem 중앙 Identity Provider.
- **RankWeave** — https://github.com/ContextualWisdomLab/RankWeave — Python 3.10+용 무의존성·저장소 비종속 retrieval fusion/evaluation/statistical comparison/tuning/TREC benchmarking/auditable CLI workflow.
- **ThreadWeave** — https://github.com/ContextualWisdomLab/ThreadWeave — runtime dependency 없는 Python용 표준 기반 JWZ/RFC 5256 이메일 reference threading.
- **disksage** — https://github.com/ContextualWisdomLab/disksage — Windows/Linux/macOS 디스크 공간 관리자. 드라이브를 스캔하고 완전 오프라인 온디바이스 LLM이 삭제 안전성을 조언하며 OWL ontology로 파일을 정리한다.
- **wardnet** — https://github.com/ContextualWisdomLab/wardnet — ContextualWisdomLab Rust-first gateway·SOC control-plane baseline.
- **LineageWeave** — https://github.com/ContextualWisdomLab/LineageWeave — 명시적 선후행 링크 없는 짧은 timestamped record에서 git-branch식 lineage DAG를 재구성해 평면 자료를 탐색 가능한 branching thread로 바꾼다. 수리 연산은 소관이 아니므로 다른 라이브러리로 이관한다.

## How to point a `/goal` session at this directive

Because `/goal` truncates at 4000 characters, do not paste the sections above into it. Instead use a
short pointer, e.g. (Korean, ~260 chars, well under the cap):

```
/goal ContextualWisdomLab/.github의 docs/product-goal-directive.md 전문을 지침으로 삼아 실행하라. 열린 PR마다 리뷰 확인→수정→Checks 재검증→병합→다음 개발을 중간 보고 없이 반복하고, PR·Issue 소진 후에도 Gap 기반 개발을 계속한다. 이 문서의 9개 절 전체(실행 루프, 동시작업/근본수정, 연구추적성, UX/UI, 아키텍처/DB, 언어/측정, 검증/부하, LLM/오케스트레이션, 참고 라이브러리)를 매 사이클 적용 대상으로 취급하고, 이 문서와 docs/CWL-MASTER-CONTEXT.md §7이 상충하면 상충을 해소하고 두 문서를 함께 갱신하라. 한 시간 간격으로 재예약하라.
```

When this directive itself changes (the user revises a section, or an agent finds it conflicts with
`docs/CWL-MASTER-CONTEXT.md` or a merged PR), edit this file in place and note the change in
`docs/doctoring/` per the repo's traceability convention — do not fork a second copy elsewhere.
