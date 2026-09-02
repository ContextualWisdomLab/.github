# Product goal directive — autonomous PR/merge/development loop

**Status:** active standing directive · **Owner intent recorded:** 2026-08-30 · **Last synced to
latest owner-authored directive text:** 2026-09-02 · **Scope:** the full ContextualWisdomLab
ecosystem (every repo an agent can reach from this org, leveraged in order of product responsibility
/ reuse boundary / docs / implementation / consumption — not by name).

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
elsewhere; link to this file instead. **This file intentionally does not track the numbered, per-cycle
backlog items (specific bug reports, feature asks, run/job URLs) the owner attaches to each `/loop`
re-invocation — those are transient and belong in the live GitHub Project #1 and
`docs/product-technical-gap-baseline.md`, per this repo's own "repo/Project, not private memory" rule.
Only the nine general-guideline sections below are durable directive text.**

## 1. Execution goal and continuous loop

> 실행 목표와 지속 Loop 열린 PR마다 보고 없이 리뷰→수정→Checks 재검증→병합→다음 개발을 반복하라. PRD로 Loop·Goal을 조정해 PR을 병합하거나 0개로 만들며 상용화한다. 목표는 200억 달러 판매 품질과 고객 체감 Gap 해소다. ADR·리서치·현행 데이터·PR에서 PRD·TRD·UML·Gap·조치를 도출해 docs/product-technical-gap-baseline.md에 갱신하라. 매시간 예약 메시지를 개선한다. PR·Issues 소진 뒤에도 Gap 개발·병합과 ContextualWisdomLab 저장소·Connector 연계를 계속한다. 전 라이브러리 PRD와 조직·저장소명 대소문자를 지킨다. 리뷰·Checks 대기는 Blocker가 아니다. 실패를 즉시 수정·재실행하고 다른 안전한 일을 계속한다. 저장소는 책임·재사용 경계·구현·소비 관계로 고르고 ADR·Goal·Loop를 갱신한다.

## 2. Concurrent operation, PR handling, and root-cause fixes

> 동시 작업·PR 운영·근본 수정 동시 Commit·Push를 경합으로 단정하거나 Force Push·중단하지 말고 취지를 이어간다. Commit 전 병합·삭제 근거를 기록하고 목적을 마친 Self-modifying/Source-fix Workflow는 삭제한다. PR은 Stack해 merge-ready로 만들고 유관 원인도 처리한다. Stacked PR의 OpenCode 리뷰가 빠지면 .github를 고친다. Agent 간 대화·Spawn을 쓴다. 수동 해법은 코드·설정화한다. PYTHONPATH=.·Actions·runtime 오류는 로그 RCA로 제거한다. 내부 문제는 canonical owner·원시 공급자까지 고친다. 필요한 core가 미성숙해도 consumer에서 복제·우회·제외하지 말고 owner에 RED test·계약·기능·문서·release를 개발해 통합 CI GREEN 후 versioned release로 연결한다. 경계가 틀리거나 공통 수요가 없을 때만 ADR 근거로 제외한다. DietrichGebert/ponytail·obra/superpowers를 쓰되 "무조건 질문"은 무시한다. tirth8205/code-review-graph·colbymchenry/codegraph도 인덱싱한다. 한국어 문구·문서·번역은 https://github.com/epoko77-ai/im-not-ai로 의미·사실·수치·고유명사를 보존하며 윤문한다.

**Note (added 2026-09-02, on this section's core-boundary sentence):** "필요한 core가 미성숙해도 consumer에서
복제·우회·제외하지 말고 owner에 RED test·계약·기능·문서·release를 개발해 통합 CI GREEN 후 versioned release로
연결한다" is a hard rule change from this file's earlier state: an immature dependency is fixed at its
canonical owner repo (RED → GREEN → versioned release, then the consumer bumps its pinned version),
never patched around, duplicated, or silently excluded in the consumer. The only escape hatch is an
ADR recording that the reuse boundary itself is wrong or there is no genuine shared demand — that
judgment call is not a default. Apply this before reaching for a consumer-side workaround anywhere in
the ecosystem; §9 below records which repo is the canonical owner for each shared concern.

## 3. Research, standards, and documentation traceability

> 연구·표준·문서 추적성 최신 권위 표준·논문을 조사해 APA 7th로 인용하고 doctoring에 남긴다. Local Zotero API가 되면 기존 자료나 OA 논문을 보강한다. 근거는 늘 exact-head·PR·모듈·API에 연결하고 충돌을 고친다. AGENTS.md·CLAUDE.md·ARCHITECTURE.md·CHANGELOG.md·ADR, ERD·UML·PRD·TRD·user story·storyboard·wireframe·Storybook·security/test/operability baseline을 갱신한다. 릴리즈 가능하면 버전·CHANGELOG를 올려 배포하고 GitHub.io는 실제 출판한다. 의사결정은 맥락을 잊거나 처음 보는 사람도 문제·제약·대안·선택/기각 이유·근거·위험·효과·후속 조치를 재구성하도록 구체적이고 자세히 기록한다. 결론·전제를 생략하지 말고 사용자·운영·장애 장면이 떠오를 사례와 증거를 exact-head·로그·이슈·PR·ADR·실험에 연결해 다른 Agent가 검증·계속하게 한다.

## 4. UX/UI, i18n, and customer-facing expression

> UX·UI·i18n과 고객 표현 Figma·Storybook·ui-ux-pro-max·Anti-Slop-UI를 쓴다. UI는 모두 재사용 객체이고 페이지는 조합으로 만든다. token·Figma ID를 ADR에 남긴다. Storybook에서 정상·로딩·빈·오류·권한·반응형·상호작용 상태를 격리 개발·문서화하고 스크린샷·E2E로 접근성·터치·성능·타이포그래피·색상·폼·탐색·차트를 감사한다. shadcn/ui는 component source로 Storybook과 대체 관계가 아니다. Frontend stack은 고정하지 않으며 React·Vite·shadcn/ui·jQuery 4 등은 보안·유지보수·표준·접근성·성능을 충족할 때 쓴다. 내부 경계를 숨기고 다음 행동을 안내한다. Keyverse는 인증 backend로 유지하되(Direct Grant/ROPC 또는 Keycloak REST API), 로그인·가입·복구는 제품 자체 form으로 만든다. token CSS·Action Edge·Interaction UX를 검증한다. i18n은 한국어·영어·일본어·중국어·베트남어·스페인어·독일어·프랑스어를 지원한다. UI 폭·줄바꿈·CJK·텍스트 팽창·font fallback·locale 형식을 고려하고 언어별 Storybook·E2E로 잘림·겹침·의미 축약을 막는다. 번역 원장은 파일·JS bundle이 아닌 DB의 versioned resource다. server/native가 화면 key만 조회·cache하며 browser에 전체 catalog·무거운 i18n JavaScript를 싣지 않고 SPA를 전제하지 않는다. 공통 관리 제품이 없으면 새 저장소를 만들어 제품별 번역·검토·승인·배포·rollback API·관리 UI를 제공한다.

**Note (added 2026-09-02):** the i18n paragraph is new-as-of-2026-09-02 and is a substantial addition —
a DB-backed, versioned translation ledger (not files/JS bundles), server/native fetching only the
needed screen keys (no full-catalog client payload, no SPA assumption), and — if no shared
translation-management product exists yet across the ecosystem — a new dedicated repo providing
translation/review/approval/deploy/rollback as an API plus an admin UI, for every product to consume.
As of this sync, no such shared i18n-management product has been confirmed to exist anywhere in the
org; before creating a new repo for this, an agent picking this up must first verify that absence
directly (do not assume) and check whether an existing core repo's boundary (§9) already fits before
defaulting to "create a new repo."

## 5. Architecture, ontology, naming, and database conventions

> 아키텍처·온톨로지·명명·데이터베이스 DDD의 Subdomain·Bounded Context·Context Map·Ubiquitous Language와 Aggregate·Entity·Value Object·Domain Service·Repository·Domain Event·Invariant를 ADR·코드·API·DB·test에 일치시킨다. Aggregate는 최소 transaction 경계로 두고 외부·legacy는 ACL로 격리하며 Shared Kernel을 최소화한다. 모듈러 MSA를 지향하고 비대한 Monolith는 책임별로 분리하며 옛 이름을 고친다. 통합 온톨로지는 ConceptWeave가 observe→discover→propose→align→validate→review→publish와 semantic release를, semantic-data-portal이 catalog·governance·소비를, context-graph-contracts가 상호운용 계약을, enterprise-architecture-core가 Context Map·결정을 맡는다. domain truth·Ubiquitous Language는 제품 owner에 남긴다. 개념·관계·dimension·measure·mapping은 evidence·provenance·validity·confidence·status·deprecation·locale label을 가진 immutable release로 배포한다. consumer는 released API/contract·ACL만 쓰고 파일 복사·cross-service SQL·미승인 publication을 금지한다. UI 번역과 ontology label의 원장은 분리한다. 변수·상수·매개변수·필드·함수·메서드·클래스·타입·모듈·패키지·API·DB 객체·파일·디렉터리는 두 단어 이상 snake_case·camelCase·PascalCase로 명명하고 snake_case를 우선한다. 언어·framework·외부 계약 관례는 경계에서 변환하고 위반명은 치환한다. DB는 3NF·Hot Partition 대비·Lock·필요시 Read/Write 분리·항목별 UPSERT를 지킨다. placeholder Buyer는 실제 도메인명으로 바꾼다. CSAP·SOC 2를 고려한다. PII Masking이 업무를 마비시키면 준수형 비Masking 대안을 설계한다. 실데이터 인명·기관명은 익명화하고 PYPI API Key·Public 배포 전제를 반영한다.

**Reconciliation (originally flagged by Devin Review on the 2026-08-30 PR, re-checked against the
2026-09-02 text above — see `docs/doctoring/product-goal-directive.md`):**

- The 2026-08-30 text named "wardnet" by name as an example of an "old name" (옛 이름) to rename *away
  from* — which was backwards, since `waf-ids-ai-soc` → wardnet is an already-completed rename per
  `docs/CWL-MASTER-CONTEXT.md` §3/§10, and wardnet is the current canonical name. **The 2026-09-02 text
  above has dropped that specific example** (it now just says "옛 이름을 고친다" with no named example),
  so the literal-misreading risk from the old wording no longer applies to this section's current text.
  The underlying fact remains: wardnet is current, not legacy — independently reconfirmed by §9's own
  "appguardrail·wardnet" bullet below, which lists wardnet as an active core-repo owner name.
- The 2026-08-30 text said "위반명은 전부 치환한다" ("replace ALL violating [DB object] names"), which read
  literally would force-rename existing CamelCase/PascalCase database objects — contradicting the
  binding convention in `docs/CWL-MASTER-CONTEXT.md` §7 (2+-word snake_case is required for **new** DB
  objects; existing CamelCase/PascalCase objects are grandfathered, not force-renamed). **The
  2026-09-02 text above has softened this to "위반명은 치환한다"** (dropping "전부") and now leads with an
  explicit boundary-conversion clause ("언어·framework·외부 계약 관례는 경계에서 변환하고") — this substantially
  narrows the original all-or-nothing reading, but is still not an explicit grandfather clause. Per this
  file's own conflict policy: `docs/CWL-MASTER-CONTEXT.md` §7 remains the resolving document — new
  snake_case naming applies to new objects and language/framework/external-contract boundary
  conversions; do not force-rename pre-existing Camel/Pascal DB objects on the strength of this
  section's wording alone.

## 6. Implementation language, computation, and measurement principles

> 구현 언어·연산·측정 원칙 Docstring·Test·Edge Case Coverage는 각 100%이고 초보자도 이해하게 쓴다. 수리과학·Psychometrics·EDA·데이터과학 core와 성능·안정성·보안 runtime은 Rust가 기본이다. Vector·Linear/Matrix Algebra·token size·GPU·CPU multithreading을 포함한다. Python은 비선호이며 LLM 편의·관성으로 고르지 않는다. 검증된 ML runtime이 Python 전용이고 Rust 대안이 기능·정확성·지원성을 못 맞출 때만 그 부분에 쓴다. 경계·근거·제거 조건을 ADR에 남기고 hot path는 Rust로 둔다. 확률표집은 설계·오차 목표·실패 분모를 명시한다. Atomistic fallacy 방지를 위해 다층·다중소속·시간을 모델링한다. 가중치는 fast-mlsirm·TEPP 등 논문 근거 모형에서 추정한다. 휴리스틱을 금지하고 미확정 근거는 추론 엔진과 SOLID로 해결한다. Deprecation Warning은 근본 해결한다. 합성 data는 Unit test에만 쓴다. 불가피한 Python web server는 multithreading을 지원하고 GIL 문제는 Python 3.14 또는 Rust로 푼다.

**Note (added 2026-09-02, policy change from the 2026-08-30 text):** the earlier wording made Rust
*unconditionally mandatory* ("무조건 Rust로 작성한다") for math/psychometrics/EDA/data-science core layers.
The 2026-09-02 text above narrows this: Python is *disfavored and must not be chosen for LLM
convenience/habit*, but is permitted specifically where a validated ML runtime is Python-only and no
Rust alternative meets it on functionality/correctness/supportability — and that boundary, its
justification, and its removal condition must be recorded in an ADR. Do not read this as a general
Rust-vs-Python free choice; the default is still Rust, with a narrow, ADR-documented exception path,
not a blanket allowance.

## 7. Realistic verification, load, and container testing

> 현실성 있는 검증과 부하·컨테이너 테스트는 현실 사례와 제품별 정확성 기준을 포함한다. Psychometrics는 true parameter 대비 estimation RMSE·추정 재현성을, 음악 분석은 실제 음원의 기대 분석값을 검증한다. 웹은 비동기 처리·k6 E2E를 적용하고 모든 페이지 p95≤20ms를 요구한다. 초과하면 알고리즘·query·I/O·rendering을 profile하고 runtime·언어·framework가 원인이면 계약·정확성을 보존해 Rust 우선 기술·hot path·개발 언어를 바꾼다. 표본 축소·측정 제외·비현실적 cache warm-up을 금지한다. JavaScript bundle·heap·DOM·hydration·main thread·GC가 메모리·지연을 키우면 dependency·Frontend stack을 교체한다. close_connection도 점검한다. Docker는 Podman·colima로 대체 가능하다. 병목이면 shm_size·PostgreSQL을 hardware에 맞춰 튜닝한다. compose로 k8s 전환성을 지키고 프로젝트명은 test 격리 때만 override한다. MLX·CPU·CUDA·OpenCL 처리법을 ADR에 반영하고 Native Module은 필요시 독립 service로 분리한다.

## 8. LLM, orchestration, and embedding

> LLM·오케스트레이션·Embedding LLM 작업은 contextual-orchestrator 기반 Agent로 만든다. BYTEZ_API_KEY·NVIDIA_NIM_API_KEY·NVIDIA_NIM_API_KEY_SUB·OPENROUTER_API_KEY·OPENAI_API_KEY로 auto discovery해 embedding·responses·completions·audio·video·image·omni-modal을 지원한다. 소스·adapter는 복사하지 않고 released API·client·schema로 연결한다. .github reusable workflow와 얇은 owner·consumer caller로 통합 CI를 구성한다. PR·release·consumer 변경마다 exact SHA로 build·contract·API/schema·E2E·fallback·streaming·structured output·timeout·security·SBOM·provenance를 검증한다. 결함은 owner에서 RED→fix→GREEN→release한 뒤 consumer version을 올린다. mutable sibling head·branch URL·cross-repo path·workflow 복제를 금지한다. 임시 bridge는 owner issue·만료·삭제 조건을 ADR·CI에 둔다. Provider group명은 하드코딩하지 않는다. 별칭일 뿐이며 modality·context·reasoning·tool·structured output·streaming·가격·지연·가용성·정확도 등 검증된 특성으로 선택·fallback한다. Model timeout은 공통 상한 없이 기본값을 무제한(null)로 둔다. 통신 장애는 upstream provider timeout·오류로 끝난다. 관리자 Web에서 모델별 조회·설정·해제·복원, 단위·우선순위·상속·검증·감사·API를 제공하고 설정된 모델만 제한한다. reasoning·streaming·tool call을 경과시간만으로 끊지 않으며 사용자 취소·provider 종료·관리자 timeout을 구분한다. Fugu·Conductor·TRINITY 근거로 단일·다중 Agent의 test-time compute를 단계·재귀·분해·접근·역할별 effort로 배분·ablation한다. 정확성을 우선하고 OpenCode·Strix·Noema의 모델당 2시간 이상을 수용한다. Chat은 completions·responses와 json_object·json_schema를 지원한다. Embedding은 의미 단위로 나누며 base64 이미지 인식·검색·삽입 위치·맥락을 보존한다. GitHub Actions scheduler는 contextual-orchestrator 기반 OpenCode Agent로 전환한다. COPILOT_GITHUB_TOKEN은 쓰지 않고 기존 리뷰 Agent 키 체계를 유지한다.

**Note (added 2026-09-02):** the model-timeout paragraph above ("Model timeout은 공통 상한 없이...") is new
and now implemented for one gateway surface: `contextual-orchestrator`'s admin console gained
per-model timeout CRUD + audit history + live enforcement in
[PR #1010](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1010) — treat that as
the reference implementation pattern for extending the same admin-configurable, unlimited-by-default
timeout model to other transport paths (batch/embeddings/rerank/image), not a closed, finished item.

**Note (flagged by CodeRabbit on the 2026-08-30 PR, still applicable — this section's wording has not
changed in a way that affects it):** section 8's quoted text describes `contextual-orchestrator`'s
general product capability — broad model/modality support and all-five-secret auto model discovery as
a *design principle for the orchestrator itself*. It does not specify, and must not be read as
overriding, which pool each CI consumer routes through: that is governed exclusively by
`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` and its doctoring records — `OpenCode` and
`Noema` use the fail-closed, ZDR-prioritized `orchestrator/free` pool; only `Strix` security analysis
uses the provider-diverse `orchestrator/auto` pool; private/internal review targets require an attested
ZDR-only catalog and never fall back to a non-ZDR provider. Do not loosen any CI consumer's pool or
credential scope on the strength of this section's general wording alone.

**Note (2026-08-30/08-31, superseded by the merged pin flip):** an earlier draft of this note said
Strix stayed on `orchestrator/auto` pending `free_family_diversity` reaching `>= 2`. That is no longer
true: `.github/workflows/strix.yml` now hardcodes `STRIX_MODEL`/`CONTEXTUAL_ORCHESTRATOR_POOL` to
`orchestrator/free` and fails closed on any other value — confirmed by the owner on 2026-09-02 (see
[[project-orchestrator-free-pin-confirmed]] in this repo's agent-memory record and ADR-0003's own
Decision section). `free_account_diversity`
(`scripts/ci/contextual_orchestrator_review_policy.py`) remains useful as ongoing monitoring evidence,
not as a gate blocking the pin.

## 9. Core foundation and development/consumption boundaries

> Core foundation과 개발·사용 경계 @Superpowers @GitHub @Figma @Visualize @Context7 @Product Design @Consensus를 쓴다. 매 실행 README·PRD·ARCHITECTURE·release에서 책임을 확인한다. core는 완성도가 아닌 반복 수요·권위·재사용 경계로 정하고 미완성이면 owner에서 완성·release한다. transient head는 production에 쓰지 않는다.
>
> - **.github** — workflow·review/security/release owner이며 ruleset·얇은 workflow_call로만 쓴다.
> - **enterprise-architecture-core·context-graph-contracts** — 전사 결정·versioned context 계약 원장이며 runtime·제품 DB는 제외한다.
> - **ConceptWeave·semantic-data-portal** — ontology 생성·publish와 catalog·governance·소비를 분담한다.
> - **contextual-orchestrator·noema** — 모델 orchestration과 GitHub OIDC 단기 권한·exact-head evidence를 분담한다.
> - **keyverse** — identity 원장. 제품은 OIDC/OAuth·SCIM·자체 form을 쓰고 table은 복제하지 않는다.
> - **EgressWeave·OriginWeave·pingora-gateway·quarantine-sandbox-runtime** — outbound·browser·edge·격리 core이며 부족한 기능은 owner에서 완성한다.
> - **pg-llm-batch·EmbedRelay** — batch/token과 embedding identity·vector migration owner다.
> - **fast-mlsirm·TEPP** — IRT/MLSIRM과 다국어·시간·event·relation 측정 owner이며 kernel 재구현을 금지한다.
> - **RankWeave·ThreadWeave** — retrieval fusion/evaluation/TREC와 JWZ/RFC 5256 threading owner다.
> - **inkspan·DiagramWeave** — editor/serialization과 diagram patch/render/CLI/LSP package다.
> - **mhtml-etl-gateway** — MHTML 검사·schema proposal·load·lineage owner다.
> - **appguardrail·wardnet** — SAST/SARIF와 Rust gateway/SOC baseline owner이며 범위를 과장하지 않는다.
>
> naruon·LineageWeave·psychometrics-commons·disksage·PolicyWeave·CalendarWeave·supply-chain-control-plane은 완성도가 아니라 domain product/composition consumer라 분류한다. 공통 기능은 core owner로 추출해 통합 CI로 개발한다.

**Note (added 2026-09-02):** this section replaces the 2026-08-30 text's "참고 라이브러리와 호출" (reference
libraries and tool invocations) section, which listed individual repo descriptions (TEPP,
contextual-orchestrator, fast-mlsirm, keyverse, RankWeave, ThreadWeave, disksage, wardnet,
LineageWeave). The owner's 2026-09-02 revision replaced that with this ownership-boundary taxonomy
instead — a materially different organizing principle (who owns which *kind* of shared concern, not a
per-repo description list). This is the first place in this repo's own docs that names
`enterprise-architecture-core` and `context-graph-contracts` as canonical owners of org-wide
decisions/versioned context contracts; a cross-repo investigation on 2026-09-02 (see
`docs/product-technical-gap-baseline.md`'s corresponding dated entry and
[`context-graph-contracts#23`](https://github.com/ContextualWisdomLab/context-graph-contracts/pull/23))
found neither repo's own in-flight work yet reflects this ownership claim — both exist and are active,
but as of that investigation had no open PR/issue on org-hierarchy or ABAC/RBAC contracts specifically.
Treat this section's bullet list as the authoritative *intended* ownership map going forward; verify a
specific repo's *actual current* state before assuming it already implements what its bullet claims.

## How to point a `/goal` session at this directive

Because `/goal` truncates at 4000 characters, do not paste the sections above into it. Instead use a
short pointer, e.g. (Korean, ~280 chars, well under the cap):

```text
/goal ContextualWisdomLab/.github의 docs/product-goal-directive.md 전문을 지침으로 삼아 실행하라. 열린 PR마다 리뷰 확인→수정→Checks 재검증→병합→다음 개발을 중간 보고 없이 반복하고, PR·Issue 소진 후에도 Gap 기반 개발을 계속한다. 이 문서의 9개 절 전체(실행 루프, 동시작업/근본수정, 연구추적성, UX/UI/i18n, 아키텍처/온톨로지/DB, 언어/측정, 검증/부하, LLM/오케스트레이션, Core foundation)를 매 사이클 적용 대상으로 취급하고, 이 문서와 docs/CWL-MASTER-CONTEXT.md §7이 상충하면 상충을 해소하고 두 문서를 함께 갱신하라. 한 시간 간격으로 재예약하라.
```

When this directive itself changes (the user revises a section, or an agent finds it conflicts with
`docs/CWL-MASTER-CONTEXT.md` or a merged PR), edit this file in place and note the change in
`docs/doctoring/` per the repo's traceability convention — do not fork a second copy elsewhere.
