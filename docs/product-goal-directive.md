# Product goal directive — autonomous PR/merge/development loop

**Status:** active standing directive · **Owner intent recorded:** 2026-08-30 · **Revised:**
2026-09-02 (nine-section text replaced in full with the owner's updated directive; see
`docs/doctoring/product-goal-directive.md` for what changed) · **Scope:** the full
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

> 실행 목표와 지속 Loop 열린 PR마다 리뷰→수정→Checks 재검증→병합→다음 개발을 반복하라. PRD로 Loop·Goal을 조정하되 PR 0개는 병합이나 검증된 successor의 유효 delta 완전 승계로만 만들고 단순 Close하지 않는다. 목표는 200억 달러 판매 품질과 고객 체감 Gap 해소다. ADR·현행 근거·PR에서 PRD·TRD·UML·Gap·조치를 도출해 docs/product-technical-gap-baseline.md를 갱신하라. 매시간 예약 메시지를 개선한다. PR·Issues 소진 뒤에도 Gap 개발·병합과 ContextualWisdomLab 저장소·Connector 연계를 계속하며 PRD와 명칭 대소문자를 지킨다. 리뷰·Checks 대기는 Blocker가 아니다. 실패를 즉시 고쳐 재실행하며 안전한 일을 계속한다. 저장소는 책임·재사용·구현·소비 경계로 고르고 ADR·Goal·Loop를 갱신한다.

## 2. Concurrent operation, PR repair (not close), and root-cause fixes

> 동시 작업·PR 운영·근본 수정 동시 Commit·Push를 경합으로 단정하거나 Force Push하지 말고 취지를 잇는다. Commit 전 병합·삭제 근거를 남기고 목적을 마친 Self-modifying/Source-fix Workflow는 제거한다. PR을 Stack해 merge-ready로 만들고 유관 원인도 고친다. Stacked PR 리뷰가 빠지면 .github를 수리하고 Agent 대화·Spawn을 쓴다. single-writer·DDD 위반, 잘못된 base·충돌, ADR 번호 충돌, 성급한 Accepted, 미보호 dependency, 누락된 test·fixture·contract는 Close가 아닌 repair finding이다. Draft·Proposed로 낮추고 owner stack에 non-force restack·retarget해 수리한다. single-writer는 delta 폐기가 아닌 통합이다. 직접 못 고치면 successor가 delta를 완전 승계하고 predecessor를 잇는다. foundation 미착지 시 prerequisite를 완성하며 PR은 유지한다. 오폐쇄는 reopen·successor로 복구한다. Close는 사용자 명시, 유효 delta 없음, 악성 변경, 완전 승계에만 허용하며 표시는 종결이 아니다. 수동 해법은 코드·설정화하고 PYTHONPATH=.·Actions·runtime 오류는 로그 RCA로 없앤다. 내부 결함은 canonical owner·원시 공급자에서 고쳐 통합 CI와 release까지 잇는다. 경계나 공통 수요가 없을 때만 ADR로 제외한다. ponytail·superpowers를 쓰되 "무조건 질문"은 무시하고 code-review-graph·codegraph를 인덱싱한다. 한국어 문구·문서·번역에는 https://github.com/epoko77-ai/im-not-ai 를 적용하되 의미·사실·수치·고유명사를 보존한다.

## 3. Research, standards, and documentation traceability

> 연구·표준·문서 추적성 권위 표준·논문을 조사해 APA 7th로 인용하고 doctoring에 남긴다. Local Zotero API가 되면 자료·OA 논문을 보강한다. 근거는 exact-head·PR·모듈·API에 연결하고 모순을 고친다. AGENTS.md·CLAUDE.md·ARCHITECTURE.md·CHANGELOG.md·ADR와 ERD·UML·PRD·TRD·UX·security/test/operability를 갱신한다. 가능하면 버전·CHANGELOG를 올려 배포하고 GitHub.io를 언급하면 실제 출판한다. 의사결정은 처음 보는 사람도 문제·제약·대안·선택/기각 이유·근거·위험·효과·후속 조치를 재구성하게 구체적이고 자세히 기록한다. 결론·전제를 생략하지 말고 사용자·운영·장애 장면이 보이는 사례와 증거를 exact-head·로그·이슈·PR·ADR·실험에 연결해 다른 Agent가 검증·계속하게 한다.

## 4. UX/UI, i18n, and customer-facing expression

> UX·UI·i18n과 고객 표현 Figma·Storybook·ui-ux-pro-max·Anti-Slop-UI를 쓴다. 모든 UI는 재사용 객체이며 페이지는 그 조합이다. token·Figma ID를 ADR에 남긴다. Storybook에서 정상·로딩·빈·오류·권한·반응형·상호작용 상태를 문서화하고 스크린샷·E2E로 ui-ux-pro-max 전 범주를 감사한다. shadcn/ui는 제품 소유 component source, Storybook은 검증 환경이다. Frontend stack은 보안·유지보수·표준·접근성·측정 성능으로 고른다. 내부 경계를 숨기고 다음 행동을 안내한다. Keyverse는 인증 backend로 유지하되(Direct Grant/ROPC 또는 Keycloak REST API), 로그인·가입·복구는 제품 자체 form으로 만든다. token CSS·Action Edge·Interaction UX를 검증한다. i18n은 한국어·영어·일본어·중국어·베트남어·스페인어·독일어·프랑스어를 지원한다. UI 크기·줄바꿈·CJK·텍스트 팽창·font fallback·locale을 고려하고 언어별 Storybook·E2E로 잘림·겹침을 막는다. 번역 원장은 파일·JS bundle이 아닌 DB versioned resource다. server/native는 화면 key만 조회·cache하며 전체 catalog·무거운 i18n JavaScript·SPA를 전제하지 않는다. 공통 관리 제품이 없으면 새 저장소에서 제품별 번역·검토·승인·배포·rollback API·관리 UI를 제공한다.

## 5. Architecture, ontology, naming, and database conventions

> 아키텍처·온톨로지·명명·데이터베이스 DDD의 Subdomain·Bounded Context·Context Map·Ubiquitous Language(UL)와 Aggregate·Entity·Value Object·Domain Service·Repository·Event·Invariant를 ADR·코드·API·DB·test에 맞춘다. Aggregate는 최소 transaction 경계, 외부·legacy는 ACL로 격리하고 Shared Kernel은 최소화한다. 비대한 Monolith는 책임별 저장소로 나누고 옛 이름을 고친다. 통합 온톨로지의 생성·publish, catalog·소비, 상호운용 계약, EA 결정은 owner를 분리한다. 제품의 domain truth·UL은 옮기지 않는다. release는 evidence·provenance·유효기간·confidence·status·locale label을 가진다. consumer는 released contract·ACL만 사용하며 파일 복사·cross-service SQL·미승인 publication을 금지한다. UI 번역과 ontology label 원장은 분리한다. 변수·상수·인자·필드·함수·메서드·클래스·타입·모듈·패키지·API·DB 객체·파일·디렉터리는 두 단어 이상 snake_case·camelCase·PascalCase로 명명하고 snake_case를 우선한다. 언어·framework·외부 계약 관례는 경계에서 변환하며 위반명은 치환한다. DB는 3NF·Hot Partition 대비·Lock·필요시 Read/Write 분리·항목별 UPSERT를 지킨다. placeholder Buyer는 실제 도메인명으로 바꾼다. CSAP·SOC 2를 고려한다. PII Masking이 업무를 마비시키면 준수형 비Masking 대안을 설계한다. 실데이터 인명·기관명은 익명화하고 PYPI API Key·Public 배포 전제를 반영한다.

**Reconciliation (carried forward from the 2026-08-30 review; re-checked against this 2026-09-02
revision):** this section's earlier wording named "wardnet" as an example of an "old name" to rename
away from, which contradicted `docs/CWL-MASTER-CONTEXT.md` §3/§10 (`waf-ids-ai-soc` → **wardnet** is
an already-completed rename). The 2026-09-02 text above no longer names wardnet or any other product
by name in that sentence, so that specific conflict is resolved. The remaining point still worth
flagging: "위반명은 치환한다" now explicitly permits snake_case, camelCase, *or* PascalCase (snake_case
preferred) for identifiers generally, which is looser than the old "snake_case only" reading — but for
**database objects specifically**, `docs/CWL-MASTER-CONTEXT.md` §7's grandfather clause still governs:
2+-word snake_case is required for **new** DB objects; existing CamelCase/PascalCase DB objects are
grandfathered and must not be force-renamed on the strength of this section's general wording alone.

## 6. Implementation language, computation, and measurement principles

> 구현 언어·연산·측정 원칙 Docstring·Test·Edge Case Coverage는 각 100%다. 수리과학·Psychometrics·EDA·데이터과학 core와 성능·보안 runtime은 Rust로 만들며 Vector·Linear/Matrix Algebra·token size·GPU·CPU multithreading을 포함한다. Python은 비선호며 LLM 편의로 고르지 않는다. Python 전용 ML runtime에 실용적 Rust 대안이 없을 때만 그 부분에 쓰며 범위·근거·제거 조건을 ADR에 남기고 hot path는 Rust로 둔다. 확률표집은 설계·오차 목표·실패 분모를 명시하고 다층·다중소속·시간 모델로 Atomistic fallacy를 막는다. 가중치는 fast-mlsirm·TEPP 등 논문 근거로 추정하며 휴리스틱을 금지한다. 미확정 근거는 추론 엔진·SOLID로 해결한다. Deprecation Warning은 근본 해결하고 합성 data는 Unit test에만 쓴다. Python web server는 multithread이며 GIL 병목은 3.14나 Rust로 푼다.

## 7. Realistic verification, load, and container testing

> 현실성 있는 검증과 부하·컨테이너 테스트는 현실 사례와 제품별 정확성 기준을 쓴다. Psychometrics는 true parameter 대비 RMSE·재현성을, 음악은 실제 음원의 기대값을 검증한다. 웹은 비동기 처리·k6 E2E를 적용해 모든 페이지 p95≤20ms를 맞춘다. 초과하면 profile하고 runtime·언어·framework가 원인이면 계약·정확성을 보존해 Rust 우선 기술·hot path·언어로 바꾼다. 표본 축소·측정 제외·비현실적 cache warm-up은 금지한다. JavaScript bundle·heap·DOM·hydration·main thread·GC가 메모리·지연을 키우면 dependency·rendering·Frontend stack을 교체한다. close_connection도 점검한다. Docker는 Podman·colima로 대체 가능하다. 병목이면 shm_size·PostgreSQL을 장비에 맞춰 튜닝한다. compose로 k8s 전환성을 지키고 프로젝트명은 test 격리 때만 바꾼다. MLX·CPU·CUDA·OpenCL 처리법을 ADR에 남기고 Native Module은 필요시 독립 service로 분리한다.

## 8. LLM, orchestration, and embedding

> LLM·오케스트레이션·Embedding LLM 작업은 contextual-orchestrator(CO) Agent로 만든다. BYTEZ_API_KEY·NVIDIA_NIM_API_KEY·NVIDIA_NIM_API_KEY_SUB·OPENROUTER_API_KEY·OPENAI_API_KEY로 auto discovery해 embedding·responses·completions·audio·video·image·omni-modal을 지원하고 released API·client·schema로 연결한다. 통합 CI는 .github reusable workflow와 thin caller로 구성한다. owner PR·release·consumer 변경마다 exact SHA로 build·API/schema contract·E2E·model behavior·security·SBOM·provenance를 검증한다. 결함은 owner에서 RED→fix→GREEN→release하고 consumer version을 올린다. mutable head·branch URL·cross-repo source·workflow 복제를 금지하며 bridge에는 owner issue·만료·삭제 조건을 둔다. GitHub Actions의 model-backed workflow는 `orchestrator/free`로 고정한다. 무료 후보 discovery·routing·fallback은 CO 내부에서만 한다. workflow는 provider·model·group명·유료 fallback을 지정하지 않고 gateway token만 쓴다. capability가 없으면 유료 우회 없이 fail closed해 free pool·contract·CI를 보완한다. Provider group명은 하드코딩하지 않는다. group은 별칭이며 modality·context·reasoning·tool·structured output·streaming·가격·지연·가용성·정확도 등 검증된 특성으로 선택·fallback한다. Model timeout은 application·Agent·Gateway 공통 상한 없이 기본 null이다. 통신 장애는 upstream provider가 끝낸다. 관리자 Web은 모델별 조회·설정·해제·복원, 단위·우선순위·상속·검증·감사·API를 제공하고 설정된 모델만 제한한다. reasoning·streaming·tool call은 시간만으로 끊지 않으며 사용자 취소·provider 종료·관리자 timeout을 구분한다. Fugu·Conductor·TRINITY 근거로 단일·다중 Agent의 test-time compute를 단계·재귀·분해·접근·역할별 effort로 배분·ablation한다. 정확성을 우선하고 OpenCode·Strix·Noema의 모델당 2시간 이상을 수용한다. Chat은 completions·responses와 json_object·json_schema를 지원한다. Embedding은 의미 단위로 나누고 base64 이미지의 인식·검색·삽입 위치·맥락을 보존한다.

**Status update (2026-09-02, supersedes the 2026-08-30 note below):** the section above now states
directly that every GitHub Actions model-backed workflow pins to `orchestrator/free` — and this is now
the actual, owner-reviewed state, not just this section's aspiration. Per
`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`'s 2026-08-30/2026-09-02 amendments, the
owner explicitly confirmed on 2026-09-02 (in the `/loop` input for the contextual-orchestrator
integration work: *"Contextual-Orchestrator의 모델은 GitHub Actions Workflow 이용에 관해
`orchestrator/free`로 고정"*) that **both** OpenCode Review and Strix are pinned to `orchestrator/free`
— resolving the ADR-0003-flagged "Strix switched without owner review" risk the 2026-08-30 note below
was tracking. Treat the free-pin for both consumers as settled; do not re-flag it as an unreviewed risk.

**Note (2026-08-30, historical — the risk it flagged is now resolved per the update above):** section
8's quoted text describes `contextual-orchestrator`'s general product capability — broad
model/modality support and all-five-secret auto model discovery as a design principle for the
orchestrator itself. It did not specify, and should not have been read as overriding, which pool each
CI consumer routed through on its own — that distinction lived in
`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`. Private/internal review targets still
require an attested ZDR-only catalog and never fall back to a non-ZDR provider; that part is unchanged.

## 9. What "core foundation" means, and its development/use boundary

> Core foundation의 의미와 개발·사용 경계 @Superpowers·@GitHub·@Figma·@Visualize·@Context7·@Product Design·@Consensus를 쓴다. Core foundation은 전 제품의 공통 설치물이 아니다. 여러 제품에서 반복되는 책임을 한 저장소가 canonical owner로서 독립 배포·versioned contract를 제공하는 선택형 control plane·service·library다. 보호 브랜치의 문서·API/schema·release evidence로 역할·성숙도를 확인하며 open PR은 Proposed 상태다. 조직·계약 — .github: 공통 CI·review·security·release; enterprise-architecture-core: 전사 Context Map·architecture decision; context-graph-contracts: assertion·event·schema·fixture·conformance. domain truth는 제품에 남긴다. 의미·데이터 — ConceptWeave: ontology·semantic-layer 생성·검증·release. semantic-data-portal: catalog·governance·검색·제공. EmbedRelay: embedding identity·migration. mhtml-etl-gateway: MHTML 검사·schema proposal·load lineage. AI·운영 — CO: provider discovery·model capability·routing/delegation/verification/admin. noema: GitHub Actions OIDC 단기 repository capability·exact-revision evidence. pg-llm-batch: DB token count·batch 처리. Identity·보안·runtime — keyverse: identity·federation·token. EgressWeave: 안전한 outbound HTTP. OriginWeave: governed browser. pingora-gateway: Rust edge. quarantine-sandbox-runtime: 격리. appguardrail: scan·SARIF·remediation. wardnet: gateway·WAF·IDS·SOC. 재사용 기능 — fast-mlsirm: IRT·MLSIRM. TEPP: 다국어·시간·event·relation 측정. RankWeave: retrieval fusion·evaluation·통계 비교·tuning·TREC. ThreadWeave: JWZ/RFC 5256 threading. inkspan: editor·serialization·문서 변환. DiagramWeave: diagram patch·render·CLI·LSP. owner가 미성숙하거나 API가 없어도 consumer가 복제·우회하지 않는다. owner에서 RED test→기능·문서·release를 개발해 CI GREEN과 immutable version을 낸 뒤 채택한다. 그 전에는 port·ACL·feature flag·test double로 경계를 지키고 owner의 source·DB·임시 branch를 직접 읽지 않는다.

## How to point a `/goal` session at this directive

Because `/goal` truncates at 4000 characters, do not paste the sections above into it. Instead use a
short pointer, e.g. (Korean, ~260 chars, well under the cap):

```text
/goal ContextualWisdomLab/.github의 docs/product-goal-directive.md 전문을 지침으로 삼아 실행하라. 열린 PR마다 리뷰 확인→수정→Checks 재검증→병합→다음 개발을 중간 보고 없이 반복하고, PR·Issue 소진 후에도 Gap 기반 개발을 계속한다. 이 문서의 9개 절 전체(실행 루프, 동시작업/PR 수리/근본수정, 연구추적성, UX/UI/i18n, 아키텍처/온톨로지/DB, 언어/측정, 검증/부하, LLM/오케스트레이션, core foundation 경계)를 매 사이클 적용 대상으로 취급하고, 이 문서와 docs/CWL-MASTER-CONTEXT.md §7이 상충하면 상충을 해소하고 두 문서를 함께 갱신하라. PR은 유효 delta의 successor 완전 승계 없이 단순 Close하지 말라. 한 시간 간격으로 재예약하라.
```

When this directive itself changes (the user revises a section, or an agent finds it conflicts with
`docs/CWL-MASTER-CONTEXT.md` or a merged PR), edit this file in place and note the change in
`docs/doctoring/` per the repo's traceability convention — do not fork a second copy elsewhere.
