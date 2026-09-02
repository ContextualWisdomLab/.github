# Product goal directive — autonomous PR/merge/development loop

**Status:** active standing directive · **Owner intent recorded:** 2026-08-30, revised 2026-09-02 ·
**Scope:** the full ContextualWisdomLab ecosystem (every repo an agent can reach from this org,
leveraged in order of product responsibility / reuse boundary / docs / implementation / consumption —
not by name).

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
elsewhere; link to this file instead. The 2026-09-02 revision replaced the full text of all nine
sections (the owner reissued the directive with substantially expanded detail in §2, §4, §5, §8, and
§9); see "Revision history" at the end of this file and `docs/doctoring/product-goal-directive.md` for
the reconciliation notes on both the original and this revision.

## 1. Execution goal and continuous loop

> 실행 목표와 지속 Loop 열린 PR마다 보고 없이 리뷰→수정→Checks 재검증→병합→다음 개발을 반복하라. PRD로 Loop·Goal을 조정해 PR을 병합하거나 0개로 만들며 상용화한다. 목표는 200억 달러 판매 품질과 고객 체감 Gap 해소다. ADR·리서치·현행 데이터·PR에서 PRD·TRD·UML·Gap·조치를 도출해 docs/product-technical-gap-baseline.md에 갱신하라. 매시간 예약 메시지를 개선한다. PR·Issues 소진 뒤에도 Gap 개발·병합과 ContextualWisdomLab 저장소·Connector 연계를 계속한다. 전 라이브러리 PRD와 조직·저장소명 대소문자를 지킨다. 리뷰·Checks 대기는 Blocker가 아니다. 실패를 즉시 수정·재실행하고 다른 안전한 일을 계속한다. 저장소는 책임·재사용 경계·구현·소비 관계로 고르고 ADR·Goal·Loop를 갱신한다.

## 2. Concurrent operation, PR handling, and root-cause fixes

> 동시 작업·PR 운영·근본 수정 동시 Commit·Push를 경합으로 단정하거나 Force Push·중단하지 말고 취지를 이어간다. Commit 전 병합·삭제 근거를 기록하고 목적을 마친 Self-modifying/Source-fix Workflow는 삭제한다. PR은 Stack해 merge-ready로 만들고 유관 원인도 처리한다. Stacked PR의 OpenCode 리뷰가 빠지면 .github를 고친다. Agent 간 대화·Spawn을 쓴다. 수동 해법은 코드·설정화한다. PYTHONPATH=.·Actions·runtime 오류는 로그 RCA로 제거한다. 내부 문제는 canonical owner·원시 공급자까지 고친다. 필요한 core가 미성숙해도 consumer에서 복제·우회·제외하지 말고 owner에 RED test·계약·기능·문서·release를 개발해 통합 CI GREEN 후 versioned release로 연결한다. 경계가 틀리거나 공통 수요가 없을 때만 ADR 근거로 제외한다. DietrichGebert/ponytail·obra/superpowers를 쓰되 "무조건 질문"은 무시한다. tirth8205/code-review-graph·colbymchenry/codegraph도 인덱싱한다. 한국어 문구·문서·번역은 https://github.com/epoko77-ai/im-not-ai로 의미·사실·수치·고유명사를 보존하며 윤문한다.

**Note (2026-09-02):** `epoko77-ai/im-not-ai` is a repository under a different GitHub account
(`epoko77-ai`), not `ContextualWisdomLab` — it is an external Korean-copyediting tool referenced by
URL, not an org-owned core repo, and is not part of the §9 core-repo list below.

## 3. Research, standards, and documentation traceability

> 연구·표준·문서 추적성 최신 권위 표준·논문을 조사해 APA 7th로 인용하고 doctoring에 남긴다. Local Zotero API가 되면 기존 자료나 OA 논문을 보강한다. 근거는 늘 exact-head·PR·모듈·API에 연결하고 충돌을 고친다. AGENTS.md·CLAUDE.md·ARCHITECTURE.md·CHANGELOG.md·ADR, ERD·UML·PRD·TRD·user story·storyboard·wireframe·Storybook·security/test/operability baseline을 갱신한다. 릴리즈 가능하면 버전·CHANGELOG를 올려 배포하고 GitHub.io는 실제 출판한다. 의사결정은 맥락을 잊거나 처음 보는 사람도 문제·제약·대안·선택/기각 이유·근거·위험·효과·후속 조치를 재구성하도록 구체적이고 자세히 기록한다. 결론·전제를 생략하지 말고 사용자·운영·장애 장면이 떠오를 사례와 증거를 exact-head·로그·이슈·PR·ADR·실험에 연결해 다른 Agent가 검증·계속하게 한다.

## 4. UX/UI, i18n, and customer-facing expression

> UX·UI·i18n과 고객 표현 Figma·Storybook·ui-ux-pro-max·Anti-Slop-UI를 쓴다. UI는 모두 재사용 객체이고 페이지는 조합으로 만든다. token·Figma ID를 ADR에 남긴다. Storybook에서 정상·로딩·빈·오류·권한·반응형·상호작용 상태를 격리 개발·문서화하고 스크린샷·E2E로 접근성·터치·성능·타이포그래피·색상·폼·탐색·차트를 감사한다. shadcn/ui는 component source로 Storybook과 대체 관계가 아니다. Frontend stack은 고정하지 않으며 React·Vite·shadcn/ui·jQuery 4 등은 보안·유지보수·표준·접근성·성능을 충족할 때 쓴다. 내부 경계를 숨기고 다음 행동을 안내한다. Keyverse는 인증 backend로 유지하되(Direct Grant/ROPC 또는 Keycloak REST API), 로그인·가입·복구는 제품 자체 form으로 만든다. token CSS·Action Edge·Interaction UX를 검증한다. i18n은 한국어·영어·일본어·중국어·베트남어·스페인어·독일어·프랑스어를 지원한다. UI 폭·줄바꿈·CJK·텍스트 팽창·font fallback·locale 형식을 고려하고 언어별 Storybook·E2E로 잘림·겹침·의미 축약을 막는다. 번역 원장은 파일·JS bundle이 아닌 DB의 versioned resource다. server/native가 화면 key만 조회·cache하며 browser에 전체 catalog·무거운 i18n JavaScript를 싣지 않고 SPA를 전제하지 않는다. 공통 관리 제품이 없으면 새 저장소를 만들어 제품별 번역·검토·승인·배포·rollback API·관리 UI를 제공한다.

## 5. Architecture, ontology, naming, and database conventions

> 아키텍처·온톨로지·명명·데이터베이스 DDD의 Subdomain·Bounded Context·Context Map·Ubiquitous Language와 Aggregate·Entity·Value Object·Domain Service·Repository·Domain Event·Invariant를 ADR·코드·API·DB·test에 일치시킨다. Aggregate는 최소 transaction 경계로 두고 외부·legacy는 ACL로 격리하며 Shared Kernel을 최소화한다. 모듈러 MSA를 지향하고 비대한 Monolith는 책임별로 분리하며 옛 이름을 고친다. 통합 온톨로지는 ConceptWeave가 observe→discover→propose→align→validate→review→publish와 semantic release를, semantic-data-portal이 catalog·governance·소비를, context-graph-contracts가 상호운용 계약을, enterprise-architecture-core가 Context Map·결정을 맡는다. domain truth·Ubiquitous Language는 제품 owner에 남긴다. 개념·관계·dimension·measure·mapping은 evidence·provenance·validity·confidence·status·deprecation·locale label을 가진 immutable release로 배포한다. consumer는 released API/contract·ACL만 쓰고 파일 복사·cross-service SQL·미승인 publication을 금지한다. UI 번역과 ontology label의 원장은 분리한다. 변수·상수·매개변수·필드·함수·메서드·클래스·타입·모듈·패키지·API·DB 객체·파일·디렉터리는 두 단어 이상 snake_case·camelCase·PascalCase로 명명하고 snake_case를 우선한다. 언어·framework·외부 계약 관례는 경계에서 변환하고 위반명은 치환한다. DB는 3NF·Hot Partition 대비·Lock·필요시 Read/Write 분리·항목별 UPSERT를 지킨다. placeholder Buyer는 실제 도메인명으로 바꾼다. CSAP·SOC 2를 고려한다. PII Masking이 업무를 마비시키면 준수형 비Masking 대안을 설계한다. 실데이터 인명·기관명은 익명화하고 PYPI API Key·Public 배포 전제를 반영한다.

**Reconciliation (naming scope, 2026-09-02 — supersedes the 2026-08-30 note below for this point):**
this section's identifier-naming rule is now explicitly broader than the original directive's — it
covers every code identifier (variables, functions, classes, modules, files, directories, API and DB
object names), not DB objects alone, and says a violating name "gets replaced" (위반명은 치환한다).
Read together with `docs/CWL-MASTER-CONTEXT.md` §7's binding, narrower rule — *"DB object names = 2+
word snake_case (don't rename existing Camel/Pascal)"* — the two do not contradict as long as this
broader rule is applied the same way: **going forward, on code an agent is already touching or
creating**, not as a mandate to sweep the ecosystem and force-rename every existing identifier that
doesn't fit. A repo-wide, blind rename of existing public APIs, classes, or DB objects is a
high-blast-radius, potentially breaking change for real consumers — exactly the kind of action this
org's own engineering conventions (minimal, reviewed, evidence-based changes; ADR-recorded reasoning)
guard against. §7's DB-object grandfather clause remains binding and unambiguous: existing Camel/Pascal
DB objects are not renamed on the strength of this section alone. Where a genuinely repo-wide rename is
warranted (a name is actively misleading or the repo/product itself was renamed), record it as an ADR
with its own migration plan, not as a blanket action under this directive.

**Note (2026-08-30, on the original wording, retained for history):** the original (2026-08-30)
version of this section named "wardnet" as an example of an "old name" (옛 이름) to rename *away
from*. Per `docs/CWL-MASTER-CONTEXT.md` §3/§10, `waf-ids-ai-soc` → **wardnet** is an already-completed
rename — wardnet is the current canonical product name. The 2026-09-02 revision above no longer
contains that specific wording, and §9 below lists wardnet as a current core-repo owner, consistent
with treating it as the canonical name. If a future revision of this directive reintroduces "wardnet"
as an old-name example, treat that as the same error this note originally corrected, not as new intent
to rename the product.

## 6. Implementation language, computation, and measurement principles

> 구현 언어·연산·측정 원칙 Docstring·Test·Edge Case Coverage는 각 100%이고 초보자도 이해하게 쓴다. 수리과학·Psychometrics·EDA·데이터과학 core와 성능·안정성·보안 runtime은 Rust가 기본이다. Vector·Linear/Matrix Algebra·token size·GPU·CPU multithreading을 포함한다. Python은 비선호이며 LLM 편의·관성으로 고르지 않는다. 검증된 ML runtime이 Python 전용이고 Rust 대안이 기능·정확성·지원성을 못 맞출 때만 그 부분에 쓴다. 경계·근거·제거 조건을 ADR에 남기고 hot path는 Rust로 둔다. 확률표집은 설계·오차 목표·실패 분모를 명시한다. Atomistic fallacy 방지를 위해 다층·다중소속·시간을 모델링한다. 가중치는 fast-mlsirm·TEPP 등 논문 근거 모형에서 추정한다. 휴리스틱을 금지하고 미확정 근거는 추론 엔진과 SOLID로 해결한다. Deprecation Warning은 근본 해결한다. 합성 data는 Unit test에만 쓴다. 불가피한 Python web server는 multithreading을 지원하고 GIL 문제는 Python 3.14 또는 Rust로 푼다.

## 7. Realistic verification, load, and container testing

> 현실성 있는 검증과 부하·컨테이너 테스트는 현실 사례와 제품별 정확성 기준을 포함한다. Psychometrics는 true parameter 대비 estimation RMSE·추정 재현성을, 음악 분석은 실제 음원의 기대 분석값을 검증한다. 웹은 비동기 처리·k6 E2E를 적용하고 모든 페이지 p95≤20ms를 요구한다. 초과하면 알고리즘·query·I/O·rendering을 profile하고 runtime·언어·framework가 원인이면 계약·정확성을 보존해 Rust 우선 기술·hot path·개발 언어를 바꾼다. 표본 축소·측정 제외·비현실적 cache warm-up을 금지한다. JavaScript bundle·heap·DOM·hydration·main thread·GC가 메모리·지연을 키우면 dependency·Frontend stack을 교체한다. close_connection도 점검한다. Docker는 Podman·colima로 대체 가능하다. 병목이면 shm_size·PostgreSQL을 hardware에 맞춰 튜닝한다. compose로 k8s 전환성을 지키고 프로젝트명은 test 격리 때만 override한다. MLX·CPU·CUDA·OpenCL 처리법을 ADR에 반영하고 Native Module은 필요시 독립 service로 분리한다.

## 8. LLM, orchestration, and embedding

> LLM·오케스트레이션·Embedding LLM 작업은 contextual-orchestrator 기반 Agent로 만든다. `orchestrator/free` 고정. BYTEZ_API_KEY·NVIDIA_NIM_API_KEY·NVIDIA_NIM_API_KEY_SUB·OPENROUTER_API_KEY·OPENAI_API_KEY로 auto discovery해 embedding·responses·completions·audio·video·image·omni-modal을 지원한다. 소스·adapter는 복사하지 않고 released API·client·schema로 연결한다. .github reusable workflow와 얇은 owner·consumer caller로 통합 CI를 구성한다. PR·release·consumer 변경마다 exact SHA로 build·contract·API/schema·E2E·fallback·streaming·structured output·timeout·security·SBOM·provenance를 검증한다. 결함은 owner에서 RED→fix→GREEN→release한 뒤 consumer version을 올린다. mutable sibling head·branch URL·cross-repo path·workflow 복제를 금지한다. 임시 bridge는 owner issue·만료·삭제 조건을 ADR·CI에 둔다. Provider group명은 하드코딩하지 않는다. 별칭일 뿐이며 modality·context·reasoning·tool·structured output·streaming·가격·지연·가용성·정확도 등 검증된 특성으로 선택·fallback한다. Model timeout은 공통 상한 없이 기본값을 무제한(null)로 둔다. 통신 장애는 upstream provider timeout·오류로 끝난다. 관리자 Web에서 모델별 조회·설정·해제·복원, 단위·우선순위·상속·검증·감사·API를 제공하고 설정된 모델만 제한한다. reasoning·streaming·tool call을 경과시간만으로 끊지 않으며 사용자 취소·provider 종료·관리자 timeout을 구분한다. Fugu·Conductor·TRINITY 근거로 단일·다중 Agent의 test-time compute를 단계·재귀·분해·접근·역할별 effort로 배분·ablation한다. 정확성을 우선하고 OpenCode·Strix·Noema의 모델당 2시간 이상을 수용한다. Chat은 completions·responses와 json_object·json_schema를 지원한다. Embedding은 의미 단위로 나누며 base64 이미지 인식·검색·삽입 위치·맥락을 보존한다.

**Note (2026-09-02, supersedes the 2026-08-30 note below):** this revision states the pool pin
directly in the quoted text ("`orchestrator/free` 고정"), removing the ambiguity the original wording
had. This matches the current implemented state: `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`'s
2026-08-30 amendment already moved Strix from `orchestrator/auto` to `orchestrator/free`, and all four
central workflows that route through `contextual-orchestrator` (`opencode-review-dispatch.yml`,
`noema-review.yml`, `strix.yml`, `pr-review-autofix.yml`) hardcode `orchestrator/free` with fail-closed
validation as of this revision (verified directly against the workflow files, 2026-09-02). No further
pool-routing change is required by this section; ADR-0003 remains the authoritative record for *why*.

**Note (2026-08-30, on the original wording, retained for history):** the original version of this
section described `contextual-orchestrator`'s general auto-discovery capability across all five
provider secrets as a product-level design principle, which — read in isolation — an agent could
mistake for license to loosen which pool a CI consumer routes through. That ambiguity no longer applies
now that this section states the pin explicitly, but the underlying rule stands: pool/credential-scope
routing for CI consumers is governed exclusively by ADR-0003, never loosened on the strength of this
section's general wording about the orchestrator's own capabilities.

## 9. Core foundation and development/consumption boundaries

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

**Verification (2026-09-02):** every repository named above was confirmed to exist under
`ContextualWisdomLab` with exact-matching case via a direct GitHub repository listing on the date of
this revision: `.github`, `enterprise-architecture-core`, `context-graph-contracts`, `ConceptWeave`,
`semantic-data-portal`, `contextual-orchestrator`, `noema`, `keyverse`, `EgressWeave`, `OriginWeave`,
`pingora-gateway`, `quarantine-sandbox-runtime`, `pg-llm-batch`, `EmbedRelay`, `fast-mlsirm`, `TEPP`,
`RankWeave`, `ThreadWeave`, `inkspan`, `DiagramWeave`, `mhtml-etl-gateway`, `appguardrail`, `wardnet`,
`naruon`, `LineageWeave`, `psychometrics-commons`, `disksage`, `PolicyWeave`, `CalendarWeave`,
`supply-chain-control-plane`. None needed a spelling or case correction.

**Open reconciliation item (2026-09-02, not yet resolved — do not silently pick one):**
`docs/CWL-MASTER-CONTEXT.md` §3 ("Ecosystem components") already documents roles for a subset of these
repos (`contextual-orchestrator`, `pg-llm-batch`, `fast-mlsirm`, `semantic-data-portal`, `noema`,
`appguardrail`, `inkspan`, `keyverse`, `wardnet`, among others) with narrower or differently-framed
descriptions than this section, and does not yet mention most of the repos newly named here
(`ConceptWeave`, `enterprise-architecture-core`, `context-graph-contracts`, `EgressWeave`,
`OriginWeave`, `pingora-gateway`, `quarantine-sandbox-runtime`, `EmbedRelay`, `DiagramWeave`,
`mhtml-etl-gateway`, `PolicyWeave`, `CalendarWeave`, `supply-chain-control-plane`,
`psychometrics-commons`, `LineageWeave`) at all. One specific tension worth flagging rather than
silently resolving: §3 currently describes `noema` as owning "the lightweight quarantine sandbox",
while this section groups `quarantine-sandbox-runtime` as its own dedicated repo alongside
`EgressWeave`/`OriginWeave`/`pingora-gateway` under "outbound·browser·edge·격리 core" — whether the
sandbox responsibility moved to a dedicated repo, or the two repos share it, has not been verified
against either repo's actual current content as of this revision. A future pass should read both
repos' READMEs/ARCHITECTURE docs and either update §3 to match this section, update this section if §3
is the one that's current, or record an ADR if the split is a genuinely new decision — not guess.

## How to point a `/goal` session at this directive

Because `/goal` truncates at 4000 characters, do not paste the sections above into it. Instead use a
short pointer, e.g. (Korean, ~260 chars, well under the cap):

```text
/goal ContextualWisdomLab/.github의 docs/product-goal-directive.md 전문을 지침으로 삼아 실행하라. 열린 PR마다 리뷰 확인→수정→Checks 재검증→병합→다음 개발을 중간 보고 없이 반복하고, PR·Issue 소진 후에도 Gap 기반 개발을 계속한다. 이 문서의 9개 절 전체(실행 루프, 동시작업/근본수정, 연구추적성, UX/UI/i18n, 아키텍처/온톨로지/DB, 언어/측정, 검증/부하, LLM/오케스트레이션, Core foundation과 개발/사용 경계)를 매 사이클 적용 대상으로 취급하고, 이 문서와 docs/CWL-MASTER-CONTEXT.md가 상충하면 상충을 해소하고 두 문서를 함께 갱신하라. 매시간 재예약하라.
```

When this directive itself changes (the user revises a section, or an agent finds it conflicts with
`docs/CWL-MASTER-CONTEXT.md` or a merged PR), edit this file in place and note the change in
`docs/doctoring/` per the repo's traceability convention — do not fork a second copy elsewhere.

## Revision history

- **2026-08-30** — original nine-section directive recorded verbatim. Two reconciliation notes added
  against `docs/CWL-MASTER-CONTEXT.md` (the wardnet naming-history conflict in §5, the
  `orchestrator/auto`-vs-`orchestrator/free` pool-routing ambiguity in §8); see
  `docs/doctoring/product-goal-directive.md` for the full PR #1429 review-finding trail.
- **2026-09-02** — the owner reissued the directive with all nine sections substantially expanded:
  §2 added an explicit "build the immature core, don't bypass it" policy (RED-test-driven development
  at the owner repo, ADR-gated exceptions only); §4 added detailed i18n requirements (8 supported
  languages, DB-backed versioned translation resources, no full-catalog client bundles) and clarified
  Keycloak's role (auth backend only, product-owned login/signup/recovery forms); §5 broadened the
  naming rule from DB objects to all code identifiers and added an ontology-ownership split across four
  named repos; §8 folded the `orchestrator/free` pin directly into the quoted text, resolving the prior
  ambiguity; §9 replaced the general reference-library list with a full named core-repo table and an
  explicit core-vs-domain-product classification. Recorded verbatim, superseding the 2026-08-30 text of
  every section; both the 2026-08-30 and 2026-09-02 reconciliation notes are kept inline above (each
  marked with its date) so neither the original context nor the correction is lost. See
  `docs/doctoring/product-goal-directive.md` for this revision's own reconciliation record, including
  the open §3-vs-§9 repo-role item noted under §9 above.
