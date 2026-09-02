# Product goal directive — autonomous PR/merge/development loop

**Status:** active standing directive · **Owner intent recorded:** 2026-08-30 · **Revised:** 2026-09-02
(sections 1-9 rewritten/expanded verbatim by the owner, twice the same day — see the revision note
after §9 for both passes) · **Scope:** the full ContextualWisdomLab ecosystem (every repo an agent can
reach from this org, leveraged in order of product responsibility / reuse boundary / docs /
implementation / consumption — not by name).

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
elsewhere; link to this file instead. **2026-09-02 revision (first pass):** the owner restated sections
1-9 in full (expanded scope: i18n, UI component reuse, DDD/ontology architecture, and a detailed
~25-repository core/consumer boundary list replace the earlier shorter versions). **2026-09-02 revision
(second pass, same day):** the owner restated sections 1-9 again — a tightening/condensation pass that
also carries genuine new content: an explicit "repair finding, not Close" PR-lifecycle policy in §2, a
resolved role split between `enterprise-architecture-core` and `context-graph-contracts` in §9 (the two
repos no longer share one undifferentiated claimed role), a regrouping of `EmbedRelay`/`appguardrail`/
`wardnet` into more specific individual responsibilities, and explicit consumer-boundary-protection
guidance (port/ACL/feature-flag/test-double; never read an owner repo's source/DB/temp branch directly)
appended to §9. The text below is that second-pass version; both earlier wordings are preserved in
`docs/doctoring/product-goal-directive.md` for history, not duplicated here.

## 1. Execution goal and continuous loop

> 실행 목표와 지속 Loop
> 열린 PR마다 리뷰→수정→Checks 재검증→병합→다음 개발을 반복하라. PRD로 Loop·Goal을 조정하되 PR 0개는 병합이나 검증된 successor의 유효 delta 완전 승계로만 만들고 단순 Close하지 않는다. 목표는 200억 달러 판매 품질과 고객 체감 Gap 해소다. ADR·현행 근거·PR에서 PRD·TRD·UML·Gap·조치를 도출해 docs/product-technical-gap-baseline.md를 갱신하라.
> 매시간 예약 메시지를 개선한다. PR·Issues 소진 뒤에도 Gap 개발·병합과 ContextualWisdomLab 저장소·Connector 연계를 계속하며 PRD와 명칭 대소문자를 지킨다. 리뷰·Checks 대기는 Blocker가 아니다. 실패를 즉시 고쳐 재실행하며 안전한 일을 계속한다. 저장소는 책임·재사용·구현·소비 경계로 고르고 ADR·Goal·Loop를 갱신한다.

**Note (2026-09-02 second-pass wording change):** this revision makes explicit *how* "PR 0개" (zero open
PRs) may be reached: only by merge, or by a verified successor's **complete** inheritance of the
predecessor's valid delta — never by a plain Close. This directly generalizes §2's new repair-finding
policy (below) up into the loop's top-level goal statement. The earlier "보고 없이" (without interim
reports) qualifier on the review→fix→...→develop loop is dropped in this pass; treat status comments
already required elsewhere in this directive (e.g. standing-down notes on CI/review findings) as still
governed by those specific rules, not reintroduced wholesale here.

## 2. Concurrent operation, PR handling, and root-cause fixes

> 동시 작업·PR 운영·근본 수정
> 동시 Commit·Push를 경합으로 단정하거나 Force Push하지 말고 취지를 잇는다. Commit 전 병합·삭제 근거를 남기고 목적을 마친 Self-modifying/Source-fix Workflow는 제거한다. PR을 Stack해 merge-ready로 만들고 유관 원인도 고친다. Stacked PR 리뷰가 빠지면 .github를 수리하고 Agent 대화·Spawn을 쓴다.
> single-writer·DDD 위반, 잘못된 base·충돌, ADR 번호 충돌, 성급한 Accepted, 미보호 dependency, 누락된 test·fixture·contract는 Close가 아닌 repair finding이다. Draft·Proposed로 낮추고 owner stack에 non-force restack·retarget해 수리한다. single-writer는 delta 폐기가 아닌 통합이다. 직접 못 고치면 successor가 delta를 완전 승계하고 predecessor를 잇는다. foundation 미착지 시 prerequisite를 완성하며 PR은 유지한다. 오폐쇄는 reopen·successor로 복구한다. Close는 사용자 명시, 유효 delta 없음, 악성 변경, 완전 승계에만 허용하며 표시는 종결이 아니다.
> 수동 해법은 코드·설정화하고 PYTHONPATH=.·Actions·runtime 오류는 로그 RCA로 없앤다. 내부 결함은 canonical owner·원시 공급자에서 고쳐 통합 CI와 release까지 잇는다. 경계나 공통 수요가 없을 때만 ADR로 제외한다.
> ponytail·superpowers를 쓰되 "무조건 질문"은 무시하고 code-review-graph·codegraph를 인덱싱한다. 한국어 문구·문서·번역에는 https://github.com/epoko77-ai/im-not-ai를 적용하되 의미·사실·수치·고유명사를 보존한다.

**New in this revision (2026-09-02 second pass) — repair-finding policy, not carried forward from
anywhere earlier:** a new paragraph explicitly classifies a defined list of PR defects — single-writer/
DDD violations, wrong base or merge conflicts, ADR-number collisions, prematurely-set `Accepted` status,
an unprotected dependency, or missing test/fixture/contract coverage — as **repair findings**, never
grounds for Close. The prescribed remedy: downgrade the PR to Draft/Proposed and non-force restack/
retarget it onto the owner's stack. "single-writer" here means *integrate* the delta, not discard it —
if the agent handling it cannot fix it directly, a successor PR must **fully** inherit the delta and
continue the predecessor's intent (this is the general rule the session's own `naruon#1502`→`#1503`
convergence and `#1502`→`#1531` extraction this session already followed as a specific case). If a
foundation/prerequisite hasn't landed yet, complete the prerequisite while keeping the dependent PR open
— do not close it to wait. A PR closed in error must be recovered via reopen or a successor, not left
closed. Close is valid **only** for: explicit user request, no valid delta remaining, a malicious change,
or confirmed complete inheritance by a successor — and even a legitimately closed PR's Close status is
not itself "완결" (a true end state) if it still carries a delta that must live on somewhere. This
generalizes and supersedes any prior looser reading of PR-closing in this directive; §1's "PR 0개"
language above is the top-level expression of this same rule.

**Relocated, not dropped:** the RED-test→fix→GREEN→versioned-release owner/consumer rule that appeared
inline in this section in the first-pass 2026-09-02 wording now appears at the end of §9 instead (with
added boundary-protection detail — port/ACL/feature-flag/test-double, never read an owner's source/DB/
temp branch directly). Read §9's closing paragraph as this section's rule, not as separate new scope.

## 3. Research, standards, and documentation traceability

> 연구·표준·문서 추적성
> 권위 표준·논문을 조사해 APA 7th로 인용하고 doctoring에 남긴다. Local Zotero API가 되면 자료·OA 논문을 보강한다. 근거는 exact-head·PR·모듈·API에 연결하고 모순을 고친다.
> AGENTS.md·CLAUDE.md·ARCHITECTURE.md·CHANGELOG.md·ADR와 ERD·UML·PRD·TRD·UX·security/test/operability를 갱신한다. 가능하면 버전·CHANGELOG를 올려 배포하고 GitHub.io를 언급하면 실제 출판한다.
> 의사결정은 처음 보는 사람도 문제·제약·대안·선택/기각 이유·근거·위험·효과·후속 조치를 재구성하게 구체적이고 자세히 기록한다. 결론·전제를 생략하지 말고 사용자·운영·장애 장면이 보이는 사례와 증거를 exact-head·로그·이슈·PR·ADR·실험에 연결해 다른 Agent가 검증·계속하게 한다.

**Note (2026-09-02 second-pass wording change):** condensation only — the explicit `user story·
storyboard·wireframe·Storybook` artifact list is now generalized to `UX`, and `GitHub.io는 실제
출판한다` (publish GitHub.io, unconditionally) gains a `언급하면` (if mentioned) qualifier. No change in
obligation: doctoring/APA-7th citation, exact-head evidence linking, and the documented-decision
traceability standard all carry forward unchanged.

## 4. UX/UI, i18n, and customer-facing expression

> UX·UI·i18n과 고객 표현
> Figma·Storybook·ui-ux-pro-max·Anti-Slop-UI를 쓴다. 모든 UI는 재사용 객체이며 페이지는 그 조합이다. token·Figma ID를 ADR에 남긴다. Storybook에서 정상·로딩·빈·오류·권한·반응형·상호작용 상태를 문서화하고 스크린샷·E2E로 ui-ux-pro-max 전 범주를 감사한다. shadcn/ui는 제품 소유 component source, Storybook은 검증 환경이다. Frontend stack은 보안·유지보수·표준·접근성·측정 성능으로 고른다.
> 내부 경계를 숨기고 다음 행동을 안내한다. Keyverse는 인증 backend로 유지하되(Direct Grant/ROPC 또는 Keycloak REST API), 로그인·가입·복구는 제품 자체 form으로 만든다. token CSS·Action Edge·Interaction UX를 검증한다.
> i18n은 한국어·영어·일본어·중국어·베트남어·스페인어·독일어·프랑스어를 지원한다. UI 크기·줄바꿈·CJK·텍스트 팽창·font fallback·locale을 고려하고 언어별 Storybook·E2E로 잘림·겹침을 막는다. 번역 원장은 파일·JS bundle이 아닌 DB versioned resource다. server/native는 화면 key만 조회·cache하며 전체 catalog·무거운 i18n JavaScript·SPA를 전제하지 않는다. 공통 관리 제품이 없으면 새 저장소에서 제품별 번역·검토·승인·배포·rollback API·관리 UI를 제공한다.

**Note (2026-09-02 second-pass wording change):** two small but real deltas. (1) The Storybook-audit
category list (accessibility, touch, performance, typography, color, forms, navigation, charts) is
replaced by a reference to `ui-ux-pro-max`'s own full category set — read that skill's category list as
authoritative going forward, not this directive's. (2) The shadcn/ui-vs-Storybook relationship is
restated more explicitly ("shadcn/ui는 제품 소유 component source, Storybook은 검증 환경이다" — shadcn/ui
is the **product-owned** component source, Storybook is the **verification environment**), and the
previously-named example stack (`React·Vite·shadcn/ui·jQuery 4`) is dropped in favor of criteria-only
guidance. Read this as: no specific frontend technology is pre-endorsed by name in this directive
version — evaluate any stack (including the previously-named ones) against the stated criteria
(security, maintainability, standards, accessibility, **measured** performance) rather than treating the
old example list as a standing allowlist.

## 5. Architecture, ontology, naming, and database conventions

> 아키텍처·온톨로지·명명·데이터베이스
> DDD의 Subdomain·Bounded Context·Context Map·Ubiquitous Language(UL)와 Aggregate·Entity·Value Object·Domain Service·Repository·Event·Invariant를 ADR·코드·API·DB·test에 맞춘다. Aggregate는 최소 transaction 경계, 외부·legacy는 ACL로 격리하고 Shared Kernel은 최소화한다. 비대한 Monolith는 책임별 저장소로 나누고 옛 이름을 고친다.
> 통합 온톨로지의 생성·publish, catalog·소비, 상호운용 계약, EA 결정은 owner를 분리한다. 제품의 domain truth·UL은 옮기지 않는다. release는 evidence·provenance·유효기간·confidence·status·locale label을 가진다. consumer는 released contract·ACL만 사용하며 파일 복사·cross-service SQL·미승인 publication을 금지한다. UI 번역과 ontology label 원장은 분리한다.
> 변수·상수·인자·필드·함수·메서드·클래스·타입·모듈·패키지·API·DB 객체·파일·디렉터리는 두 단어 이상 snake_case·camelCase·PascalCase로 명명하고 snake_case를 우선한다. 언어·framework·외부 계약 관례는 경계에서 변환하며 위반명은 치환한다. DB는 3NF·Hot Partition 대비·Lock·필요시 Read/Write 분리·항목별 UPSERT를 지킨다. placeholder Buyer는 실제 도메인명으로 바꾼다.
> CSAP·SOC 2를 고려한다. PII Masking이 업무를 마비시키면 준수형 비Masking 대안을 설계한다. 실데이터 인명·기관명은 익명화하고 PYPI API Key·Public 배포 전제를 반영한다.

**Note (2026-09-02 second-pass wording change):** three deltas worth tracking. (1) The per-repo
ontology-responsibility assignment (which repo owns generation/publish vs. catalog/consumption vs.
interop contracts vs. EA decisions) is no longer spelled out inline here — it's generalized to "owner를
분리한다" (separate the owner) and deferred to §9's bullet list, which still carries the same four-way
split (`ConceptWeave`/`semantic-data-portal`/`context-graph-contracts`/`enterprise-architecture-core`)
in the same order. This is de-duplication, not information loss. (2) The explicit ConceptWeave pipeline
— "observe→discover→propose→align→validate→review→publish" — is dropped and not restated anywhere else
in this directive; treat that specific 7-stage workflow as no longer directive-level prescribed (it may
still be correct as ConceptWeave's own internal process — verify against that repo's own docs rather than
assuming this directive still mandates it). (3) The release-metadata tag list drops `deprecation`
(evidence·provenance·validity·confidence·status·**deprecation**·locale → evidence·provenance·유효기간
(validity period)·confidence·status·locale) — releases are no longer explicitly required to carry a
deprecation tag by this directive's wording; a release process that already tracks deprecation should
keep doing so (nothing forbids it), but it is no longer a directive-mandated field.

**Reconciliation (carried forward from the pre-2026-09-02 wording; still applies):** "위반명은 치환한다"
("replace violating names"), read literally and applied to *existing, already-shipped* database
objects, would contradict the binding convention in `docs/CWL-MASTER-CONTEXT.md` §7: *"DB object
names = 2+ word snake_case (don't rename existing Camel/Pascal)."* That §7 rule still governs: 2+-word
snake_case is required for **new** DB objects; existing CamelCase/PascalCase objects already in
production are grandfathered and must not be force-renamed. Read this section's naming rule as applying
going forward and at genuinely violating (non-2+-word, non-case-consistent) names, not as license to
rename already-correct-shape legacy objects for style preference alone. The 2026-09-02 wording no
longer cites `wardnet` as an "old name" example (the prior wording did, which the 2026-08-30
reconciliation corrected — `waf-ids-ai-soc` → wardnet is an already-completed rename, wardnet is the
current canonical name), so that specific correction no longer applies to the current text but remains
in `docs/doctoring/product-goal-directive.md` for history.

## 6. Implementation language, computation, and measurement principles

> 구현 언어·연산·측정 원칙
> Docstring·Test·Edge Case Coverage는 각 100%다. 수리과학·Psychometrics·EDA·데이터과학 core와 성능·보안 runtime은 Rust로 만들며 Vector·Linear/Matrix Algebra·token size·GPU·CPU multithreading을 포함한다. Python은 비선호며 LLM 편의로 고르지 않는다. Python 전용 ML runtime에 실용적 Rust 대안이 없을 때만 그 부분에 쓰며 범위·근거·제거 조건을 ADR에 남기고 hot path는 Rust로 둔다.
> 확률표집은 설계·오차 목표·실패 분모를 명시하고 다층·다중소속·시간 모델로 Atomistic fallacy를 막는다. 가중치는 fast-mlsirm·TEPP 등 논문 근거로 추정하며 휴리스틱을 금지한다. 미확정 근거는 추론 엔진·SOLID로 해결한다. Deprecation Warning은 근본 해결하고 합성 data는 Unit test에만 쓴다. Python web server는 multithread이며 GIL 병목은 3.14나 Rust로 푼다.

**Note (2026-09-02 second-pass wording change):** two drops worth flagging explicitly rather than
silently losing. (1) "초보자도 이해하게 쓴다" (write docstrings/tests so a beginner can follow them) is
dropped from the 100%-coverage sentence — treat the 100% Docstring/Test/Edge-Case-Coverage gates
themselves as unchanged (still hard, still 100%), but this directive no longer separately mandates
beginner-readability as part of meeting them. (2) "안정성" (stability) is dropped from the list of
runtime properties that make Rust mandatory (성능·**안정성**·보안 runtime → 성능·보안 runtime) — read this as
condensation, not as stability no longer mattering; the repo's own `pyproject.toml`/CI coverage gates and
§7's correctness-verification requirements still bind regardless of this wording. (3) "불가피한" (only
when unavoidable) is dropped from "불가피한 Python web server는 multithreading을 지원하고..." — the sentence
now reads as a flat requirement on any Python web server rather than one framed as a last resort; this
does not relax the broader Rust-first/Python-disfavored policy stated earlier in the same paragraph, just
that one sentence's framing.

**Note (carried forward, 2026-08-30/09-02 first pass):** this revision sharpens the earlier "핵심 연산 레이어는 Rust로 작성한다"
into an explicit default-to-Rust-first policy with a named escape hatch: Python is permitted only where
a verified ML runtime is Python-only *and* no Rust alternative meets it on function, accuracy, and
support — and that boundary, its evidence, and its removal condition must be recorded in an ADR. Treat
existing Python code in scope for this section (math/science core, performance/safety/security-critical
runtime) as needing that ADR retroactively, not as pre-approved by having been written before this
wording existed.

## 7. Realistic verification, load, and container testing

> 현실성 있는 검증과 부하·컨테이너
> 테스트는 현실 사례와 제품별 정확성 기준을 쓴다. Psychometrics는 true parameter 대비 RMSE·재현성을, 음악은 실제 음원의 기대값을 검증한다.
> 웹은 비동기 처리·k6 E2E를 적용해 모든 페이지 p95≤20ms를 맞춘다. 초과하면 profile하고 runtime·언어·framework가 원인이면 계약·정확성을 보존해 Rust 우선 기술·hot path·언어로 바꾼다. 표본 축소·측정 제외·비현실적 cache warm-up은 금지한다. JavaScript bundle·heap·DOM·hydration·main thread·GC가 메모리·지연을 키우면 dependency·rendering·Frontend stack을 교체한다. close_connection도 점검한다.
> Docker는 Podman·colima로 대체 가능하다. 병목이면 shm_size·PostgreSQL을 장비에 맞춰 튜닝한다. compose로 k8s 전환성을 지키고 프로젝트명은 test 격리 때만 바꾼다. MLX·CPU·CUDA·OpenCL 처리법을 ADR에 남기고 Native Module은 필요시 독립 service로 분리한다.

**Note (carried forward, 2026-08-30/09-02 both passes — unchanged in the second pass):** the
p95≤20ms-per-page E2E bar is explicit and unconditional
("모든 페이지"), with sample-shrinking, exclusion, and unrealistic cache warm-up explicitly forbidden as
ways to pass it. Where a page's own runtime/language/framework is the root cause of a miss, the fix
direction is "change the runtime, hot path, or dev language toward Rust-first while preserving the
contract and correctness" — not relaxing the bar.

## 8. LLM, orchestration, and embedding

> LLM·오케스트레이션·Embedding
> LLM 작업은 contextual-orchestrator(CO) Agent로 만든다. BYTEZ_API_KEY·NVIDIA_NIM_API_KEY·NVIDIA_NIM_API_KEY_SUB·OPENROUTER_API_KEY·OPENAI_API_KEY로 auto discovery해 embedding·responses·completions·audio·video·image·omni-modal을 지원하고 released API·client·schema로 연결한다.
> 통합 CI는 .github reusable workflow와 thin caller로 구성한다. owner PR·release·consumer 변경마다 exact SHA로 build·API/schema contract·E2E·model behavior·security·SBOM·provenance를 검증한다. 결함은 owner에서 RED→fix→GREEN→release하고 consumer version을 올린다. mutable head·branch URL·cross-repo source·workflow 복제를 금지하며 bridge에는 owner issue·만료·삭제 조건을 둔다.
> GitHub Actions의 model-backed workflow는 `orchestrator/free`로 고정한다. 무료 후보 discovery·routing·fallback은 CO 내부에서만 한다. workflow는 provider·model·group명·유료 fallback을 지정하지 않고 gateway token만 쓴다. capability가 없으면 유료 우회 없이 fail closed해 free pool·contract·CI를 보완한다.
> Provider group명은 하드코딩하지 않는다. group은 별칭이며 modality·context·reasoning·tool·structured output·streaming·가격·지연·가용성·정확도 등 검증된 특성으로 선택·fallback한다.
> Model timeout은 application·Agent·Gateway 공통 상한 없이 기본 null이다. 통신 장애는 upstream provider가 끝낸다. 관리자 Web은 모델별 조회·설정·해제·복원, 단위·우선순위·상속·검증·감사·API를 제공하고 설정된 모델만 제한한다. reasoning·streaming·tool call은 시간만으로 끊지 않으며 사용자 취소·provider 종료·관리자 timeout을 구분한다.
> Fugu·Conductor·TRINITY 근거로 단일·다중 Agent의 test-time compute를 단계·재귀·분해·접근·역할별 effort로 배분·ablation한다. 정확성을 우선하고 OpenCode·Strix·Noema의 모델당 2시간 이상을 수용한다. Chat은 completions·responses와 json_object·json_schema를 지원한다. Embedding은 의미 단위로 나누고 base64 이미지의 인식·검색·삽입 위치·맥락을 보존한다.

**New in this revision (2026-09-02 second pass) — the `orchestrator/free` pin now lives directly in §8,
not only in §10:** the first-pass wording only had a bare "`orchestrator/free` 고정" clause at this
section's opening; this pass moves it into its own paragraph, explicitly scopes it to "GitHub Actions의
model-backed workflow" (matching §10's own scope-refinement, so §10 is no longer the only place this
scoping is stated), and adds three concrete sub-rules that were not spelled out at this granularity
before: (1) free-candidate discovery/routing/fallback happens **only inside CO itself** — never in a
calling workflow; (2) a workflow must not specify provider, model, group name, or a paid fallback — it
may only carry a gateway token; (3) on missing capability, the workflow must fail closed **without** a
paid bypass, complementing the free pool/contract/CI rather than routing around it. This directly
matches and reinforces `scripts/ci/contextual_orchestrator_review_sidecar.sh`'s existing fail-closed
`case "$orchestrator_pool" in free) ... *) fail "must be free"` narrowing (recorded in
`docs/product-technical-gap-baseline.md`'s 2026-09-02 `orchestrator/free` entry) — that code-level fix
is now also an explicit directive-level rule, not just a defensive implementation choice.

**Reading (carried forward — still applies):** taken together with
`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` and `AGENTS.md`'s confirmation that
OpenCode, Noema, and Strix all already route through `orchestrator/free`, this section's pin
**reaffirms that existing pin** — it is not a request to add a fourth pool or diversify providers, and
it explicitly forbids hardcoding provider *group names* anywhere in code/config/tests/routing (they are
display aliases only; selection and fallback must run on auto-discovered, verified model
characteristics). §10 below records this pin's scope refinement and the observed capacity symptoms
under it in more detail; nothing in this revision changes that record. The `docs/adr/0003-...`
2026-08-31 correction (no owner reviewed or accepted the Strix pool-pin switch or its risk) still stands
and is not superseded by this section's wording.

**Ownership rule for consumer↔core defects (carried forward; fuller wording now lives in §9's closing
paragraph):** a `contextual-orchestrator` consumer must never copy, bypass, or exclude a source/adapter
to work around a core defect or gap; instead develop a RED test, contract, feature, docs, and release in
the owner repo, get integrated CI green, then bump the consumer's pinned version. Exclusion via ADR is
only valid when the boundary itself is wrong or there's no genuine shared demand — not as a shortcut
around unfinished core work. This generalizes past `contextual-orchestrator` to every core/consumer pair
named in §9; §9's own closing paragraph (2026-09-02 second pass) adds concrete boundary-protection
mechanics (port/ACL/feature-flag/test-double) that this note did not previously spell out.

## 9. Core foundation and development/consumption boundary

> Core foundation의 의미와 개발·사용 경계
> @Superpowers·@GitHub·@Figma·@Visualize·@Context7·@Product Design·@Consensus를 쓴다. Core foundation은 전 제품의 공통 설치물이 아니다. 여러 제품에서 반복되는 책임을 한 저장소가 canonical owner로서 독립 배포·versioned contract를 제공하는 선택형 control plane·service·library다. 보호 브랜치의 문서·API/schema·release evidence로 역할·성숙도를 확인하며 open PR은 Proposed 상태다.
>    * 조직·계약 — .github: 공통 CI·review·security·release; enterprise-architecture-core: 전사 Context Map·architecture decision; context-graph-contracts: assertion·event·schema·fixture·conformance. domain truth는 제품에 남긴다.
>    * 의미·데이터 — ConceptWeave: ontology·semantic-layer 생성·검증·release. semantic-data-portal: catalog·governance·검색·제공. EmbedRelay: embedding identity·migration. mhtml-etl-gateway: MHTML 검사·schema proposal·load lineage.
>    * AI·운영 — CO: provider discovery·model capability·routing/delegation/verification/admin. noema: GitHub Actions OIDC 단기 repository capability·exact-revision evidence. pg-llm-batch: DB token count·batch 처리.
>    * Identity·보안·runtime — keyverse: identity·federation·token. EgressWeave: 안전한 outbound HTTP. OriginWeave: governed browser. pingora-gateway: Rust edge. quarantine-sandbox-runtime: 격리. appguardrail: scan·SARIF·remediation. wardnet: gateway·WAF·IDS·SOC.
>    * 재사용 기능 — fast-mlsirm: IRT·MLSIRM. TEPP: 다국어·시간·event·relation 측정. RankWeave: retrieval fusion·evaluation·통계 비교·tuning·TREC. ThreadWeave: JWZ/RFC 5256 threading. inkspan: editor·serialization·문서 변환. DiagramWeave: diagram patch·render·CLI·LSP.
>
> owner가 미성숙하거나 API가 없어도 consumer가 복제·우회하지 않는다. owner에서 RED test→기능·문서·release를 개발해 CI GREEN과 immutable version을 낸 뒤 채택한다. 그 전에는 port·ACL·feature flag·test double로 경계를 지키고 owner의 source·DB·임시 branch를 직접 읽지 않는다.

**Reading (2026-09-02 second pass — regrouped from the first pass's flat bullet-per-pair list into five
named functional groups: 조직·계약/의미·데이터/AI·운영/Identity·보안·runtime/재사용 기능):** this restructuring
carries three genuine reclassifications, not just relabeling:

1. **`enterprise-architecture-core` and `context-graph-contracts` finally have distinct roles.** The
   first-pass wording gave both repos the *identical* claimed-role string ("전사 결정·versioned context
   계약 원장") with no stated division of labor — this session's own 28-repo survey (recorded in
   `docs/product-technical-gap-baseline.md`'s 2026-09-02 §9 inventory entry) flagged this exact overlap
   as needing owner clarification, since both repos are doc-stub-only and neither's README explains the
   split. This second pass resolves it directly: `enterprise-architecture-core` = "전사 Context Map·
   architecture decision" (enterprise Context Map + architecture decisions), `context-graph-contracts` =
   "assertion·event·schema·fixture·conformance" (interop assertions/events/schemas/fixtures/conformance
   testing). Treat this as the answer to that survey's open question — the gap-baseline entry should be
   updated to record this resolution.
2. **`EmbedRelay` moves out of the `pg-llm-batch` pairing into the 의미·데이터 (semantics/data) group**,
   now grouped with `ConceptWeave`/`semantic-data-portal`/`mhtml-etl-gateway` instead, with role narrowed
   to "embedding identity·migration" (the first pass's "vector migration" wording is now just
   "migration"). `pg-llm-batch` moves to the AI·운영 group instead, described as "DB token count·batch
   처리" — the two repos are no longer presented as a paired unit the way the first pass implied.
3. **`appguardrail` and `wardnet` are no longer a joint bullet** — each gets an individually scoped role:
   `appguardrail` = "scan·SARIF·remediation" (this pass adds **remediation** as an explicit
   responsibility beyond passive scanning — relevant to the survey's `appguardrail` "scope tension"
   finding: some of what looked like scope creep in that repo's own PRD, e.g. remediation tooling, is
   now directive-authorized, though the buyer-report/dashboard/paid-services portions of that PRD remain
   outside any of these five groups' stated scope), `wardnet` = "gateway·WAF·IDS·SOC" (more specific than
   the first pass's vague "Rust gateway/SOC baseline").

**Carried forward, not restated in this pass — verify before assuming a reversal:** the first-pass
wording's explicit **domain product/composition consumer** list — `naruon`, `LineageWeave`,
`psychometrics-commons`, `disksage`, `PolicyWeave`, `CalendarWeave`, `supply-chain-control-plane`,
classified as consumers "완성도가 아니라" (not by maturity) — does not appear anywhere in this second-pass
restatement. Nothing in the new text contradicts or reverses that classification, and this session's
28-repo survey (which ran between the two passes) explicitly used and confirmed that exact list, so
treat it as still in force per this directive's own doctoring convention rather than silently dropped;
if a future revision explicitly changes it, update this note. Which bucket any repo is in is still
decided by *repeat demand / authority / reuse boundary*, never by name and never by how finished it
currently is — an unfinished core repo stays core and gets completed in place, never worked around from
a consumer. Cross-reference against `docs/CWL-MASTER-CONTEXT.md`'s own ecosystem UML/Context Map when
the two disagree on a repo's role, and resolve + update both per this file's top-level conflict policy —
do not silently pick one.

**Verification status (updated 2026-09-02, after the first-pass wording's disclaimer below was written):**
a Workflow-orchestrated survey this session cloned and read all 28 repos named across the first-pass
§9 wording (the 21 core-owner repos above plus the 7 consumer repos in the paragraph above) — full
findings and per-repo detail are in `docs/product-technical-gap-baseline.md`'s 2026-09-02 "§9
core/consumer 저장소 존재·역할 재확인" entry. All 28 exist and were readable; 16 have real docs
confirming their claimed role, 12 show gaps (stub repos, undocumented boundaries, or scope tension) —
see that entry for which. That pass used anonymous git-read only, not the GitHub API, so open-PR/issue
state and several repos' unmerged branches were explicitly **not** verified — re-verify with
authenticated access before any merge/governance action against those repos. The original disclaimer
below (this section states *ownership and boundary intent*, not a verified inventory) is now superseded
for the 16 confirmed repos and still accurate for the other 12.

Several of these repos (`enterprise-architecture-core`, `context-graph-contracts`, `ConceptWeave`,
`semantic-data-portal`, `noema`, `EgressWeave`, `OriginWeave`, `pingora-gateway`,
`quarantine-sandbox-runtime`, `pg-llm-batch`, `EmbedRelay`, `inkspan`, `DiagramWeave`,
`mhtml-etl-gateway`, `appguardrail`, `PolicyWeave`, `CalendarWeave`, `supply-chain-control-plane`,
`psychometrics-commons`) were named in this directive for the first time in the first pass; an agent
acting on this section must confirm each repo's actual existence, current README/PRD, and accessibility
before assuming any specific claim about its current state beyond what the verification-status note
above already covers.

## 10. Provider pool pinning (added 2026-09-02; refined same day)

> Contextual-Orchestrator의 모델은 GitHub Actions Workflow 이용에 관해 orchestrator/free 로 고정.

(Original wording, same session: "orchestrator/free 로 고정." The refinement scopes the pin explicitly
to `contextual-orchestrator`'s GitHub Actions Workflow usage — i.e. the CI-triggered `OpenCode`/`Noema`/`Strix`
review consumers this file and `AGENTS.md` already describe — rather than every conceivable
`contextual-orchestrator` consumer. It does not narrow or loosen anything already pinned; it only makes
explicit which surface the pin governs. A future non-CI consumer (an admin web UI, an interactive
agent session, etc.) is not automatically covered by this line and would need its own explicit
decision if and when it exists.)

**Reading**: taken together with `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`'s
2026-08-30 amendment (Strix moved from `orchestrator/auto` to the zero-cost `orchestrator/free`
pool) and `AGENTS.md`'s confirmation that OpenCode, Noema, and Strix all already route through
`orchestrator/free`, this line **reaffirms that pin** — it is not a request to add a fourth pool or
diversify providers. Read alongside the 2026-09-02 "중앙 리뷰 게이트(`orchestrator/free`) 용량 병목" entry
in [`docs/product-technical-gap-baseline.md`](product-technical-gap-baseline.md): that entry documents
concrete, directly-observed capacity symptoms of this exact pin (`noema-review` queuing 6+ hours and
hitting a token-TTL race, `strix` cancelled repeatedly on one PR head across two different failure
signatures, `opencode-review` timing out its full 5.5h poll budget on a one-file docs PR, and
`opencode-review` on a Postgres CI PR sitting queued for 12+ hours before its `coverage-evidence`
dependency finally completed) under concurrent multi-PR load. This section confirms the owner's
decision to keep the pin as-is despite that evidence — the mitigation direction is operational
(queue/backlog management, the `LLM_TIMEOUT=0` fix in `ContextualWisdomLab/.github#1658`, not retrying
into an already-overloaded pool) rather than moving off `orchestrator/free`. Do not read either
document as authorizing a pool change; if the capacity bottleneck needs a structural fix beyond what
the gap baseline's "아직 미결" (still-open) items describe, raise it as a proposal for a new ADR
amendment, not a unilateral pool switch. `docs/adr/0003-...`'s 2026-08-31 correction (no owner reviewed
or accepted the Strix pool-pin switch itself) is a separate, still-open question from this §10's own
scope-refinement instruction and is not resolved by it.

## How to point a `/goal` session at this directive

Because `/goal` truncates at 4000 characters, do not paste the sections above into it. Instead use a
short pointer, e.g. (Korean, ~260 chars, well under the cap):

```text
/goal ContextualWisdomLab/.github의 docs/product-goal-directive.md 전문을 지침으로 삼아 실행하라. 열린 PR마다 리뷰 확인→수정→Checks 재검증→병합→다음 개발을 반복하고, PR 0개는 병합이나 successor의 완전한 delta 승계로만 만들며 단순 Close하지 않는다. PR·Issue 소진 후에도 Gap 기반 개발을 계속한다. 이 문서의 10개 절 전체(실행 루프, 동시작업/근본수정/repair-finding 정책, 연구추적성, UX/UI/i18n, 아키텍처/온톨로지/DB, 언어/측정, 검증/부하, LLM/오케스트레이션, Core 경계, provider pool pinning)를 매 사이클 적용 대상으로 취급하고, 이 문서와 docs/CWL-MASTER-CONTEXT.md §7이 상충하면 상충을 해소하고 두 문서를 함께 갱신하라. 한 시간 간격으로 재예약하라.
```

When this directive itself changes (the user revises a section, or an agent finds it conflicts with
`docs/CWL-MASTER-CONTEXT.md` or a merged PR), edit this file in place and note the change in
`docs/doctoring/` per the repo's traceability convention — do not fork a second copy elsewhere.
