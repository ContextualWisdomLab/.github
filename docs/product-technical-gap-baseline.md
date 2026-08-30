# Product and Technical Gap Baseline

작성 기준일: **2026-08-26 10:35 KST**
대상: **ContextualWisdomLab/.github** 중앙 거버넌스·자동화 레포지터리와 이를 소비하는 naruon 생태계
현재 보호된 `main`: `826b92394c63deb6981c3a8d16a724d71f85a0d7`
현재 열린 PR 수: **107** (아래 표에 이 스냅샷의 전체 목록 포함; live API 재수집)

이 문서는 제품·기술·운영 Gap을 현재 문서와 현재 GitHub 상태에 묶어 두는 기준선이다. 새 작업은 먼저 이 문서의 Gap ID를 PR 설명과 테스트 증거에 연결하고, PR의 정확한 exact HEAD·Checks·리뷰를 다시 수집한 뒤 구현한다. 표의 상태는 작성 시점의 관측값이므로, 병합 판단에는 재사용하지 않는다. 이 인벤토리는 스냅샷이며 merge authorization이 아니다.

## 1. 근거와 범위

### 1.1 우선순위가 높은 근거

1. [CWL Master Context](CWL-MASTER-CONTEXT.md): naruon의 이메일 우선 플랫폼 경계, DIKW, no-ask 자동 해결, 다층·다중소속·시간·프라이버시 원칙.
2. [naruon #974](https://github.com/ContextualWisdomLab/naruon/pull/974): `docs/planning/naruon-platform-plan.md`를 추가한 병합된 제품/IA/User Story/Use Case/Architecture 기준. 이슈 트래커의 Phase 항목은 ContextualWisdomLab/naruon#975–#980.
3. [GitHub Project #1](https://github.com/orgs/ContextualWisdomLab/projects/1): 로드맵의 live source of truth. 이 문서는 live project board의 상태를 반영하며, 세부 항목 수는 project에서 직접 확인한다.
4. 중앙 ADR·doctoring·계약 문서: [ADR-0002](adr/0002-product-technical-gap-baseline.md), [hourly NVIDIA NIM autofix](doctoring/hourly-nvidia-nim-autofix.md), [Strix cryptography override](../requirements-strix-ci-overrides.txt), [trusted uv lock materialization](doctoring/trusted-uv-lock-materialization.md), [product-technical gap doctoring](doctoring/product-technical-gap-baseline.md).

### 1.2 제품 경계

구매자가 사는 핵심 결과는 “흩어진 enterprise context를 판단 가능한 구조로 만들고, 사람이 다음 행동을 승인할 수 있게 하는 것”이다. naruon은 이메일 호스트나 전자결재 시스템이 아니라 고객 소유 데이터에 연결되는 이메일 workspace/platform이다. 중앙 `.github`은 제품 기능을 대신 소유하지 않고, 정확한 HEAD·리뷰·Checks·증거·변경권한을 보장하는 control plane이다.

핵심 구매 여정은 다음과 같다.

1. 여러 계정·언어의 이메일에서 한 사건의 thread와 sender 의미를 찾는다.
2. 변경된 일정의 최신 truth, 변경 이력, commitment status와 충돌을 계산한다.
3. work/personal/project/band 등 겹치는 norm group을 선택하고, 관계·권한·유효기간을 고려한다.
4. 다른 context에는 필요한 결과(예: unavailable)만 consent·audit 기반으로 공개한다.
5. 사람은 근거·confidence·다음 행동을 보고 예외만 수정하며, 외부 writeback은 승인한다.

### 1.3 Same-session open/close delta

스냅샷은 작성 시점의 open/close delta만 기록한다. 병합 판단에는 재사용하지 않는다.

## 2. PRD / TRD / UML 기준

### 2.1 PRD acceptance

| ID | 구매자가 확인할 결과 | 수용 증거 |
|---|---|---|
| PRD-01 | “이 메일/보낸 사람이 왜 중요한가”를 찾는다 | hybrid retrieval, sender ontology, source segment provenance |
| PRD-02 | 일정 이동과 RSVP/commitment 충돌을 놓치지 않는다 | temporal event history, confirmed > tentative > desired weighting, conflict test |
| PRD-03 | 같은 사람이 여러 조직·팀·밴드에 소속되어도 권한을 뒤섞지 않는다 | reified relationship, multi-membership/norm-group resolution, ecological-fallacy test |
| PRD-04 | private reason을 노출하지 않고 필요한 consequence만 공유한다 | consented minimal-disclosure bridge, audit trail, revocation test |
| PRD-05 | 사용자가 모델 선택을 관리하지 않아도 품질을 우선해 자동 라우팅한다 | contextual-orchestrator `auto`, capability-before-cost, unpriced-is-not-free evidence |
| PRD-06 | 결과를 독립 제품 또는 naruon plugin으로 동일하게 쓴다 | versioned manifest/API, connector contract, standalone/submodule integration test |

### 2.2 TRD target

- **Platform plane:** naruon web/API, customer-VPC connector, Postgres/pgvector document KG, plugin registry, versioned extension points.
- **Evidence/control plane:** central `.github`, OpenCode/Noema/Strix, exact-source and exact-head binding, bounded hourly loops, no credential fallback, protected merge.
- **AI plane:** contextual-orchestrator adaptive routing; role별 reasoning effort, workflow depth, recursion, decomposition, verifier/synthesis를 quality evidence에 따라 배분. Fugu, Conductor, TRINITY를 근거로 단일 모델 라우팅과 심층 다중 에이전트 오케스트레이션 사이에서 계산량을 배분한다. 속도는 최적화 목표가 아니다.
- **Compute plane:** 수리과학·psychometrics의 계산 레이어와 속도·안정성·보안이 핵심인 hot path는 Rust 경계를 우선 검토하며, GPU/CPU multithreading과 낮은 context switching을 benchmark로 입증한다. Python/JS는 orchestration/API adapter로 제한한다.
- **Data plane:** 모든 영속 객체는 두 단어 이상 `snake_case`를 기본으로 하고 3NF를 지키며, 관계·evidence·confidence·validity·disclosure를 별도 정규화한다. Hot partition 대비를 스키마에 둔다.
- **UX plane:** UI 제품만 Figma/Storybook/design token을 사용한다. 중앙 `.github`는 UI 없는 인프라 레포지터리이므로 Figma File ID는 **N/A (UI scope 없음)**이며, UI PR은 별도 ADR에 실제 File ID를 기록한다. UI-owning 저장소는 Storybook scene/edge-case event, Accessibility, Touch & Interaction, Performance, Style Selection, Layout & Responsive, Typography & Color, Animation, Forms & Feedback, Navigation Patterns, Charts & Data를 정의·검토·반영·적용·감사한다.

### 2.3 UML-level dependency

```mermaid
flowchart LR
  User[Human judgment] --> Naruon[naruon email workspace]
  Naruon --> Connector[Customer-VPC connector]
  Naruon --> DocKG[Document KG / Postgres + pgvector]
  Naruon --> Plugins[Versioned plugin boundary]
  Plugins --> Verticals[BandScope / Wardnet / Inkspan / ScopeWeave]
  Naruon --> Orch[contextual-orchestrator auto]
  Orch --> Models[Embedding / response / audio / image / multimodal]
  Orch --> Batch[pg-llm-batch]
  Control[central .github] --> Review[OpenCode / Noema / Strix]
  Control --> Checks[Checks + SBOM + provenance]
  Review --> Merge[Protected exact-head merge]
  Merge --> Control
```

## 3. Gap register

우선순위는 구매자 체감, 보안/증거 위험, 선행 의존성 순서다.

| Gap ID | 현재 관측 | 구매자 영향 | 우선 구현/검증 |
|---|---|---|---|
| G-01 | 열린 PR은 107개다. metadata 상태는 BLOCKED=17, BEHIND=16, DIRTY=74, draft 13개다. 상태는 independent exact-head approval과 terminal required Checks를 자동으로 의미하지 않는다 | 안전하게 출시할 변경과 대기 중인 변경을 구별할 수 없다 | PR마다 current head, reviews, threads, required Checks, merge-result tree를 재수집하고 보호 조건 미충족이면 merge하지 않는다 |
| G-02 | protected `main`은 `826b92394c63deb6981c3a8d16a724d71f85a0d7`이며, BEHIND/stacked PR의 predecessor evidence를 current-head approval로 승격할 수 없다 | 리뷰가 호출돼도 승인 증거가 생성되지 않아 자동화가 멈춘다 | current-head quality와 OpenCode/Noema/Strix를 재실행하고, exact SHA·run ID·review commit SHA를 한 receipt에 묶는다 |
| G-03 | #1297은 Strix per-repository serialization과 scoped close cleanup을, #1345/#1347은 normalizer/web-E2E 안전성을 다룬다. 각 PR의 provider failure와 source/control-plane failure를 구분해야 한다 | 취약점 0건이어도 CI 인프라 결함이 보안 결과처럼 보이고 큐가 막힌다 | D3 교착 증거를 별도 수집하고, vulnerability marker는 절대 neutralize하지 않으며, 정상 gate 복구 후 exact-head hosted evidence를 재생성한다 |
| G-04 | 107개 live PR 중 16개가 BEHIND, 74개가 DIRTY이고 caller/Strix PR이 제품 기능보다 앞서 쌓였다 | 제품 개발 속도가 queue hygiene에 소모되고 stacking 순서가 불명확하다 | product/ownership boundary별로 stack을 재정렬하고, 오래된 PR은 current main으로 normal restack 후 변경 범위를 검증한다 |
| G-05 | ecosystem contract/catalog PR은 존재하지만 naruon의 실제 plugin 소비·standalone 실행·connector round-trip 증거가 제한적이다 | 구매자는 “연결 가능” 문서와 실제 설치 가능한 제품을 구별할 수 없다 | manifest/version compatibility, command/event envelope, consumer smoke, rollback/upgrade contract를 조직 유관 레포에서 증명한다 |
| G-06 | ContextualWisdomLab/naruon#974와 Project #1은 제품 목표를 정의하지만 E1/E2/E3의 live implementation evidence가 이 중앙 레포에 없다 | 이메일 검색·일정 충돌이라는 killer workflow가 문서에만 머문다 | naruon에서 thread/sender ontology → temporal commitment/conflict → human correction slice를 독립 PR로 delivery한다. 소유 저장소는 naruon이다 |
| G-07 | multi-level/multi-membership/temporal 관계 원칙은 master context에 있으나 모든 소비 저장소의 schema/API가 동일한 reified relationship contract를 보장하는지는 미확인이다 | 개인 단위로 집계하거나 전역 권한을 적용하는 atomistic/ecological fallacy 위험이 남는다 | relationship, membership, norm_group, validity window, evidence, confidence, disclosure를 정규화하고 cross-context golden tests를 만든다 |
| G-08 | embedding·DOM·sender/receiver 의미 단위 chunking과 base64 image의 OCR/object/tag/position-index 설계가 ecosystem contract에 부분적으로만 반영됐다 | 검색은 되지만 실제 그림 위치와 의미를 회수하지 못해 편집·문서·메일 업무가 끊긴다 | semantic unit chunk schema와 image asset/region/ocr/tag embeddings를 별도 entity로 설계하고 source offset/DOM path를 보존한다 |
| G-09 | 100% coverage/docstring은 중앙 PR별로 증거가 있으나 조직 소비 레포의 frontend interaction/i18n/design-token/real-data accuracy 증거가 동일한지 미확인이다 | “green CI”가 실제 고객 시나리오 정확성을 보장하지 않는다 | domain-specific RMSE/reproducibility/audio/visual/browser acceptance와 edge matrix를 required evidence로 만든다 |
| G-10 | math/psychometrics의 Rust+GPU/CPU path와 시간·다층·다중소속 모델은 fast-mlsirm/psychometrics-commons 등 제품 레포의 책임이다 | 계산 정확도·성능·모델 해석 가능성을 Python glue만으로 보장할 수 없다 | Rust core, GPU/CPU benchmark, temporal/multilevel/multiple-membership fixtures, RMSE/recovery/ablation을 제품 PR에 묶는다 |
| G-11 | UI가 있는 제품의 Figma/Storybook inventory와 token/interaction/i18n 테스트는 중앙 control plane에서 소유할 수 없다. Figma File ID는 이 저장소 ADR에서 N/A다 | 제품 간 UI가 달라지고 운영자 onboarding이 일관되지 않는다 | 각 UI repo가 실제 Figma File ID ADR, Storybook inventory, shared token package, keyboard/edge/i18n tests를 소유한다 |
| G-12 | CSAP/SOC 2 통제 목표와 PII masking 대안은 doctoring에 흩어져 있으며 evidence-to-control mapping의 live completeness가 미확인이다 | PII를 마스킹하면 업무가 멈추고, 원문 접근을 허용하면 감사·유출 위험이 커진다 | consent/purpose/access lease, field-level encryption/tokenization, redaction-at-egress, audit/revocation와 CSAP/SOC 2 evidence map을 구현한다 |
| G-13 | hourly scheduler는 존재하지만 no-op/credential unavailable/queued Checks의 customer next action을 모든 caller가 동일한 receipt로 내는지 미확인이다 | 자동화가 실패해도 운영자가 무엇을 고쳐야 하는지 알 수 없다 | `skipped_credential_unavailable` receipt와 다음 행동 문구를 exact-head Checks로 검증하고, bounded receipt schema, retry floor, single-flight, no secret fallback을 모든 caller contract test로 고정한다 |
| G-14 | release/changelog/version 증거가 각 PR에 분산되고 현재 central repo 보호 main의 release candidate가 명확하지 않다 | 운영자는 어떤 기능이 supportable release인지 확인할 수 없다 | merge 후 release readiness ledger, CHANGELOG, semantic version/tag, rollback/operability evidence를 함께 갱신한다 |
| G-15 | 첨부파일 처리 경계가 제품별로 다르고, 1MB 상한은 업무 데이터와 맞지 않으며 미지원 MIME/컨테이너가 parser registry에서 명시적으로 pending/quarantine 되는지 확인되지 않았다. 현재 20MB 초과 파일 가능성과 PDF/HWP/HWPX·이미지·압축파일의 parse/sidecar 흐름을 하나의 exact contract로 묶지 못했다 | 큰 업무 첨부를 거부하거나 파싱 실패를 조용히 잃으면 고객의 메일·문서 업무가 중단된다 | naruon/newsdom-api 소유 PR에서 streaming upload, configurable bounded limit above 20MB, MIME sniffing, parser capability registry, quarantine/retry, source-position provenance, and ADR를 추가하고 size/unsupported-type/zip-bomb tests를 required evidence로 만든다 |

## 4. 열린 PR live inventory

아래는 GitHub API가 2026-08-26 10:35 KST에 반환한 107개 열린 PR의 number/title/exact head/base/metadata/review 상태다. 이 표는 관측 스냅샷이며 merge authorization이 아니다. 모든 병합 판단은 각 PR의 exact head에서 required Checks, unresolved thread, 독립 승인과 merge-result tree를 다시 확인한다.

스냅샷 요약: total 107; BLOCKED=17, BEHIND=16, DIRTY=74; draft=13

| PR | title | exact head SHA | base | metadata | review | mode |
|---|---|---|---|---|---|---|
| #1347 | fix(security): isolate web E2E commands and readiness probes | `c50e26be529f473e6cdbce6dd9a7540cb750e7a0` | `main` | BLOCKED | REVIEW_REQUIRED | ready |
| #1345 | perf(normalize): scan verification labels once | `db50914fc274dc78e33e7882ca81c18ede6be2eb` | `main` | BLOCKED | REVIEW_REQUIRED | ready |
| #1343 | ci: add semantic-data-portal hourly review-repair caller | `b296a00aad13f6da7c1e25ac1083e732f8c8e1c2` | `main` | BLOCKED | REVIEW_REQUIRED | ready |
| #1341 | feat(inkspan): add protected hourly review-repair caller at minute 56 | `7d4440ca6c2e83fbb502b891125093a60385ce91` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1338 | ci: add psychometrics-commons hourly review repair dispatch | `d1091841f67855bda40f093126b08e218c7b44e1` | `main` | BLOCKED | REVIEW_REQUIRED | ready |
| #1336 | fix(coverage): trust validated head-mutated pnpm locks via manifest record | `20c744fd96659896ee099dd1cec674e49643d415` | `main` | BLOCKED | REVIEW_REQUIRED | ready |
| #1326 | feat(hourly): onboard appguardrail + macos_utility_packs review-repair callers | `dfa980c3f019fe4ff8295fe509a27a08d571f519` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1314 | fix(e2e): restrict readiness polling to loopback destinations | `0f0adf88d3675991d14f25b2c594a4a30d9b4679` | `main` | BLOCKED | CHANGES_REQUESTED | ready |
| #1310 | chore(deps): bump google/osv-scanner-action/.github/workflows/osv-scanner-reusable-pr.yml from 3a7550f43ba5b58905a821ce3a0ed24c4858b3f4 to ffa0a5f39214d80778c9b494822d94d0d9668458 | `da66ab78463702020c721f4b90955ca456370c60` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1309 | chore(deps): bump google/osv-scanner-action/osv-reporter-action from 8dc09193bb540e09b23da07ad7e30bd33bf87018 to ffa0a5f39214d80778c9b494822d94d0d9668458 | `12bdd489c3d4160f5aa66be72e57724ad7e99b79` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1308 | chore(deps): bump actions/download-artifact from 7.0.0 to 8.0.1 | `a09db618298ada330ff504707ce7f29d88c3a6d5` | `main` | BLOCKED | REVIEW_REQUIRED | ready |
| #1307 | chore(deps): bump github/codeql-action/upload-sarif from 4.37.4 to 4.37.8 | `f86dbd7d7ac7e609c4161c1779fb1d1cda85a2b3` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1306 | chore(deps): bump github/codeql-action/analyze from 4.37.0 to 4.37.8 | `5f3140f8ba61fb69bcc2160d7b015332b870cdb4` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1304 | chore(deps): bump google-cloud-storage from 3.12.1 to 3.13.1 | `2a1882bd2b3d89df4c8758fcd0f2db4313af2a8d` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1303 | chore(deps): bump coverage from 7.14.3 to 7.15.4 | `500f264dcdca835aba1cf1ae7b84728953e7a120` | `main` | BLOCKED | CHANGES_REQUESTED | ready |
| #1298 | fix(strix): normalize direct fallback and redaction pass | `72fbf8a628533bcb8f6bf6eb0e7c9d98364f5a57` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1297 | fix(strix): serialize scans per repository to stop shared-key rate-limit storms | `3d92db82540871c7bb5f5b4d9e26be8ad42e0f96` | `main` | BLOCKED | CHANGES_REQUESTED | ready |
| #1294 | docs: refresh live product-technical-gap-baseline | `efb3ad3d7dd1202f95849bcc23bf8027baeb3cd1` | `main` | BLOCKED | REVIEW_REQUIRED | ready |
| #1288 | ci: add LineageWeave hourly review-repair scheduler | `5cd507f8ffdfca13718e5dd44aaa02f4dcb3d6a4` | `main` | BLOCKED | CHANGES_REQUESTED | ready |
| #1280 | feat(ci): add a bounded subprocess primitive | `70ad61fd3e1f8aac64497bc6776f6a736de11ca6` | `main` | BEHIND | CHANGES_REQUESTED | ready |
| #1279 | fix(noema): fail closed at the credential egress boundary | `721a36f24616343029a291f02db32610f470a884` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1276 | chore(security): unify OSV Action v2.5.1 | `26187df510898277f8bf6f0e98b7d5e53c41abd1` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1275 | chore(security): unify Scorecard Action v2.4.4 | `dd545212c105b285ba7be548e0199828a8085782` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1274 | chore(security): unify CodeQL Action v4.37.7 | `1da2fce5a10c5036cb4c305b60b63594b0a446fd` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1273 | fix(opencode): retain adversarial fallback scope | `3ab55c3da0e9b05c6cc9e80fc3d5fe89a6f53b84` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1272 | security(deploy-pages): enforce explicit caller contract | `b544d9c4433603a022df925809f3128ecefd5651` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1271 | fix(scheduler): fail after summarized action errors | `8cb926fc31ca27e47192b37c968ea699fd9ecf2c` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1270 | fix(scheduler): require independent exact-head approval | `ad01b4e69eae8a149560bc39e60bb693ab9028eb` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1267 | feat(automation): repair Inkspan reviews hourly | `34efa03ecec7d815d8e6a4f7354767208fb1ce4a` | `main` | BEHIND | CHANGES_REQUESTED | ready |
| #1264 | perf(redaction): skip invalid key rescans without masking diagnostics | `a32e394af3effca5c93a759912ad9f112a50a079` | `main` | BEHIND | CHANGES_REQUESTED | ready |
| #1263 | fix(strix): make Azure and cross-provider fallbacks executable | `ab3d764547082e1b55b6257cc1cd9aa5d951fa30` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1257 | fix(osv): keep base scan results across fork checkout | `20d72bc838d7f91b74ce01bb4de16d07144fa270` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1246 | fix(opencode-review): accept int-typed run_id/run_attempt in control JSON | `f88499b708a90edb6a538aeb2c397e14304681ad` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1245 | fix(scheduler): retry and gracefully defer shared installation rate limits | `7046ba98c2d8b243713aaec9b0bf9bd98d6c97b6` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1242 | fix(security): preserve exact CI evidence while redacting provider secrets | `9bdfcbdaf4d079de3b346e1584dd505c5043afd3` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1238 | fix(scheduler): stop repository_dispatch defaulting review/merge/branch flags off | `21b4c58577d54aed299cf0d2dc30a0ee80ff0902` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1233 | fix(automation): restore hourly fleet coordination | `54ab5bb799bfa148ca1a8b0b760b7e4365597aaf` | `main` | BEHIND | CHANGES_REQUESTED | ready |
| #1231 | fix(scheduler): isolate central Actions inventory quota | `7b16617af04431a43f8f7528b8ac7db345e404a7` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1227 | fix(opencode): use same-repo status credential | `5974bee1dbc2f28b33f69f1aab08066bdedaab70` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1215 | fix(security): redact agent-mention credential diagnostics | `785401dc911e0a53ef301d1900c1825147f9524a` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1198 | fix(security): repair pip audit and schedule orchestrator review | `27a8bd5f8bd60c9f3f70ec43ce2f2f62f7dc71ae` | `main` | BLOCKED | CHANGES_REQUESTED | ready |
| #1188 | fix: grant hourly callers reusable workflow OIDC scope | `1a0cc1f875db29492861006747ded2b6d9e93d09` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1187 | fix(coverage): scope Rust evidence to changed packages | `0a88e24d9a1c92420f412d241f850aab8e72106e` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1176 | fix(governance): preserve proposal branch create transition | `437ea84d1c4f7af7b02b001e9d20d9749d96df54` | `main` | BLOCKED | CHANGES_REQUESTED | ready |
| #1172 | fix(autofix): resolve live NVIDIA NIM models instead of a retired pin | `edab578feca63c223368aef17c175bb52ce22e5a` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1170 | feat: route OpenCode reviews through contextual gateway | `199e655c242decd9bbbc6d28d3945dcc7af24804` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1166 | fix(ci): recognize replacement tests in existing files | `7986334aacb2bc8e5d794d581202f47c91e4875e` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1162 | fix: use review credentials for agent dispatch | `4a7031d7adbba759742605deb1c78d10aef16e7d` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1161 | fix: make hourly coordinator credential absence auditable | `49bc5e4a59cd30550f87070b48b61e966ac480e1` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1158 | fix(osv): preserve immutable direct-source provenance | `5addc9250488cbbb039e3f73f0fa58d7eafc0c61` | `main` | BEHIND | CHANGES_REQUESTED | ready |
| #1150 | feat: add read-only Actions queue health evidence | `efa7788bd14e3513221577566a768fc36f03ccff` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1147 | feat(integration): add ecosystem capability catalogue | `113de5eb71ff9e06c00f4c272266662dcbd97392` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1146 | fix(figma): retain style references and component sets | `8ffdf4d8150091957a79b5fc63c984e927d323b3` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1143 | ci: schedule naruon hourly review repair | `9c2842ab1d49bb1ed74683bc52c0e213eb5d5bc7` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1123 | feat(edge): standardize organization runtimes on Cloudflare Pingora | `251b16836164cfcfc0914a568d514cc7b6a9dd6d` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1120 | Wire Noema to a same-job contextual-orchestrator sidecar | `101e6906cc3568beb99c19c28eaffb526bac335b` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1114 | fix(strix): retry transient visibility API failures | `02f6e4fdb1990369574dfa99afdb5c086a97e70d` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1112 | fix(storage): reject embedded IPv4 rebinding hosts | `dc7e39cf7dff80c2e2ed8d348090394ddc643142` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1108 | feat(automation): run free-router hourly NVIDIA NIM review repair | `df5ae0b1fff42205627b4af556c7e95e87138b7a` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1104 | chore(deps): bump charset-normalizer from 3.4.7 to 3.5.1 | `d90c8320bcce63269f1ab6368f1073841c157363` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1103 | chore(deps): bump google-cloud-resource-manager from 1.17.0 to 1.18.0 | `6c8118cb46cbac9c974c9b7ffff53cbbc9ac3b19` | `main` | BEHIND | REVIEW_REQUIRED | ready |
| #1101 | feat(automation): run EmbedRelay hourly NVIDIA NIM review repair | `77557a9e35d6467a9b8fcbc25e7e73f90683383c` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1100 | feat(automation): run RankWeave hourly NVIDIA NIM review repair | `e9ccfd21f1efd13da03e72664d0585dffc1dac00` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1097 | feat(automation): run html4tree hourly NVIDIA NIM review repair | `627b7ade1a4875addb7e38c0726bd6fd82f01511` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1095 | feat(automation): run mhtml-etl-gateway hourly NVIDIA NIM review repair | `715935b45cf2688235e40be6b44c595af45d27e1` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1094 | feat(automation): run DiagramWeave hourly NVIDIA NIM review repair | `455f2e76f15c5d0e7040777fc22ea4994d850925` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1092 | feat(automation): run psychometrics-commons hourly NVIDIA NIM review repair | `6c330dbfbede45acb41972f1d384ef586b83c2b8` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1088 | feat(automation): run mightyETL hourly NVIDIA NIM review repair | `d955cb949329f3bc3726c440542f549fe2978209` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1087 | feat(automation): run life-os hourly NVIDIA NIM review repair | `37377d0a19dfae9739ae2e0a845b8270303b38be` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1085 | feat(automation): run kaefa hourly NVIDIA NIM review repair | `3e6c94603a6332b066e0be962aab23991987e094` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1083 | feat(automation): run pg-llm-batch hourly NVIDIA NIM review repair | `584141341346b7882fded053b459a7d4c16477a2` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1082 | feat(automation): run semantic-data-portal hourly NVIDIA NIM review repair | `dbfdbbf3547b4c84bb5c2a1760ecfda080751546` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1080 | feat(automation): run newsdom-api hourly NVIDIA NIM review repair | `54f53fcad5a241de28aa272d5775e98bf0b9ca00` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1079 | feat(automation): run Appguardrail hourly NVIDIA NIM review repair | `d13ff905cd0d4d814cc2e5f2b5e54dd3d1522f0c` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1078 | feat(automation): run Scopeweave hourly NVIDIA NIM review repair | `26b684bc231bff24c19b71ddc8302e551f843ebf` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1077 | feat(automation): run noema hourly NVIDIA NIM review repair | `a91c94f1c9d92430241e2cf1302286a83310fe37` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1076 | feat(automation): run pg-erd-cloud hourly NVIDIA NIM review repair | `e280e2402e9d4fcd7a17e951e944c85bacd5bd61` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1075 | feat(automation): run codec-carver hourly NVIDIA NIM review repair | `618813098dfd8e8186bc7e3277004d76e9ae5d56` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1074 | feat(automation): run Keyverse hourly NVIDIA NIM review repair | `c70ff9369f9b49b3e961fe1f63d0204e713400f5` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1070 | feat(automation): run Wardnet hourly NVIDIA NIM review repair | `9c752db19fa91b320a74da6c8bd0fbe6d03bce1e` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1065 | fix(scheduler): fall back to REST when auto-rebase GraphQL transport fails | `ff661f115ae0c6f41e7a2fab304ace3e648b3988` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1062 | fix(strix): map official modes without branch-selected dispatch | `74079e5bddd69bf7eac6d3b2492f25d598517905` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1061 | fix(scheduler): ignore manual Strix dispatch as merge evidence | `03c087804eec7f4b520ffc3f61b49edba2dc8378` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1060 | fix(opencode): prove asyncio coverage plugin without colliding #896 | `a27ae0ac907c04c300ed978e35538e26c094a682` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1058 | fix(operability): reject impossible control-plane SLI counts | `0fd148a8fa2b7acc098eb9741b8d8cea92058ef1` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1053 | fix(redaction): skip gh run view job/step prefixes | `15fa991d8a99743a640a26665d278bc159653065` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1052 | fix(opencode): split review surfaces, give NIM two hours, and remove GitHub Models | `abf47ce275fd8c1efa8306d30f1d6afbadd989ab` | `main` | DIRTY | REVIEW_REQUIRED | ready |
| #1051 | fix(pip-audit): keep index-url locks hashed and reject symlink parents | `82629751751b82bee88d000ded32b6f141125849` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1050 | fix(security): reject dot path components before dependency-review compare | `ee5c15711f0b0a346bb19a634288a49fcd981fab` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1046 | fix(opencode): pass trusted visibility into the private free-model hook | `f053ba84ff7dc92c5dbdef2ca1597cd04372dd6b` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1036 | fix(ci): bind stub-scan evidence and cap hourly fleet work at 12 | `d8205b139f8396c0452ecd4cc9b95caa45a56f42` | `main` | BEHIND | REVIEW_REQUIRED | draft |
| #1035 | docs(automation): retarget closed-unmerged #840 and #906 lineage | `cb5e2ee03b9f75857e2ce31690fc76de76ad9cc1` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1027 | fix(automation): stop mention sweep on already-exceeded rate limits | `d046637834d6d9720852423c3cdb5ef79faa1fe3` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #1026 | feat(actions): inventory orphaned workflow identities | `1be76989887ab772e3ce0d2e0c7f22d3ca98dd94` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #1015 | fix(coverage): defer interpreter-specific wheel gaps | `ce28ffba511cb7e2a5135e6f862164834c0f874b` | `main` | BEHIND | CHANGES_REQUESTED | ready |
| #1009 | fix(strix): bind evidence to exact workflow artifacts | `99fee8b1b4ff4fc2219b98561cc4fea851c2f03a` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #991 | fix(automation): reuse review node_id for mention eyes | `b6303e081756b9598316cdf07f84c038924f0427` | `main` | DIRTY | REVIEW_REQUIRED | draft |
| #949 | fix(opencode-review): discover multi-line run: blocks in safe_pytest_command | `75c6dbdfde34ac7e729e83f44aa0261e76f475d4` | `main` | BEHIND | CHANGES_REQUESTED | ready |
| #941 | fix(semgrep): make the pinned image digest authoritative | `ce95934f7bbdd6d5022065f6ec01e3de46895618` | `main` | BEHIND | CHANGES_REQUESTED | ready |
| #939 | fix: keep cross-repo OpenCode evidence healthy | `2d267d48ab78b0cf8621604ff49839b6f795e610` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #933 | fix: retry Strix provider tool protocol failures | `b260fd3e17a0c6363d2584110314e44eaf1dfd11` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #932 | fix(sbom): preserve Markdown report integrity | `f8b94d0dfb02c64761df07ebdf658eb4e1d8abc5` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #897 | fix(security): fail closed on unavailable dependency review | `47fe3ddbaa46bcc50b090b5fd4bbe84830d6387c` | `main` | BLOCKED | CHANGES_REQUESTED | ready |
| #834 | fix(noema): validate stable OIDC exchange envelope | `1a202f9745e90280e3b1bbdead4f78320ba413fc` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #821 | fix(opencode): reap fatal provider process groups | `e1eb67926d9143730054c1fc9f1ef82dc5ef4a0c` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #790 | fix(coverage): retry transient trusted uv downloads | `463ddbad84ee40f56f2196af2aa41f1dd4100907` | `main` | DIRTY | CHANGES_REQUESTED | ready |
| #789 | feat(coverage): add bounded PyO3 peer-evidence gate | `3ffde3c5d3c98f0c840abcba151af08cf0255b46` | `main` | DIRTY | CHANGES_REQUESTED | ready

## 2026-08-25 central Strix fallback contract recheck

- `main` at `a724582a0768129d481385070bf8f05b2620dd2c` changed the direct-OpenAI
  fallback to `gpt-5.4`, but the required-workflow smoke script still required
  the retired `gpt-5.6-luna` string. The privileged OpenCode model pool also
  retained the retired candidate while its contract tests expected `gpt-5.4`.
- This exact mismatch caused consumer Strix checks to fail before scanning the
  target repository; it was observed on ContextualWisdomLab/disksage#247 at
  exact head `a9c868a6e9c8d68a9c6ea6de381e188740b8f5db`. The focused repair keeps
  provider errors and vulnerability findings fail-closed and only aligns the
  executable model and its assertions.

## 2026-08-27 contextual-orchestrator vendored sidecar (ZDR-first free pool)

- **Gap G-ORCH-027 (closed by this increment):** central review pinned direct
  provider endpoints and hard-coded model ids; no path used the org's five-key
  auto model discovery, the `orchestrator/free` fail-closed zero-cost pool, or
  ZDR-first selection. The 2026-08-18 org decision
  (`ContextualWisdomLab/contextual-orchestrator` AGENTS.md) migrated
  OpenCode/Noema/Strix to the gateway; this snapshot lands the org-repo half.
- `pr-review-autofix.yml` now provisions
  `scripts/ci/contextual_orchestrator_review_sidecar.sh` (snapshot pinned SHA
  `8d5924f8…`, same-process KV registration of `BYTEZ_API_KEY`,
  `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`,
  `OPENAI_API_KEY`, live auto model discovery, ZDR-prioritized free catalog),
  and the writer runs `--model contextual-orchestrator/orchestrator/free`.
  `opencode.jsonc` default route changes identically. Companions:
  `zdr_policy.py`, `contextual_orchestrator_review_policy.py`,
  `contextual_orchestrator_review_launcher.py`; records
  `docs/adr/0003-…`, `docs/doctoring/contextual-orchestrator-vendored-sidecar.md`.
- At the time of this 2026-08-27 snapshot, the remaining follow-up was the
  read-only dispatch pool, `noema-review.yml`, and `strix.yml` migration. This
  historical observation is superseded by the current-main evidence below.

## 2026-08-28 current-main routing and runtime recheck

- Current protected main is `8f84b661e468de451ba5c076dc938f342bf52d70`,
  the merge commit for #1373 (following #1370 at
  `24ee38b097dbfc1a895e1199ade48cff36431d05`). #1364 is merged at
  `f8823a544c3c4c046977f8511f683e85f83eb496`; #1360 is merged at
  `17052a7ca3c16db90932a4d6036b43165ddee418`.
- The current Required OpenCode dispatch, `noema-review.yml`, `strix.yml`,
  and write-capable `pr-review-autofix.yml` all provision the pinned
  `contextual-orchestrator` sidecar. Their model route is the
  `contextual-orchestrator/orchestrator/free` gateway, with the five provider
  secrets entering the sidecar KV and model discovery performed there. No
  `COPILOT_GITHUB_TOKEN` route is present.
- #1364 was merged by `seonghobae` while its terminal review decision remained
  `CHANGES_REQUESTED`; this is an observed merge event, not protected-main
  governance evidence. The required branch checks still include
  `noema-review` and `opencode-review`.
- Post-merge Strix run `33139957477` exposed a real sidecar runtime defect:
  `contextual_orchestrator.orchestrator.load_agents()` requires an
  `{"agents": [...]}` catalog envelope, while the launcher wrote a bare list.
  Follow-up #1370 fixes the launcher and the standalone policy catalog writer.
  Its exact head `0f40d415b112ca0055f5db5b2f434788b08f01f1` merged as
  `24ee38b097dbfc1a895e1199ade48cff36431d05`.
- #1370's earlier PR-target Noema run `33140830199` executed the pre-fix trusted
  base launcher and is retained only as bootstrap reproduction evidence. A
  fresh protected-main canary must start the corrected sidecar and reach the
  scanner before the runtime gap is closed; queued or cancelled jobs do not
  satisfy that acceptance boundary.
- Protected-main Strix run `33141468804` crossed the corrected catalog and
  sidecar boundary, then LiteLLM rejected the unqualified scanner child model
  `orchestrator/free` because the provider was not explicit. The follow-up maps
  only that child to `openai/orchestrator/free` when the API base is the pinned
  loopback gateway; the public gateway model remains
  `contextual-orchestrator/orchestrator/free`, and absent, empty, or non-pinned
  bases fail closed. This is reproduction evidence, not operational acceptance.
- #1370 merged with no `APPROVED` review; all recorded Reviews API verdicts are
  `COMMENTED`. That governance contradiction is tracked in #1340 and is not
  retrospective approval evidence for this runtime correction.
- #1373 merged the model qualification as `8f84b661…` but retained the raw
  bearer in `GITHUB_ENV`, so its log-exposure claim is contradicted by source.
  #1369 preserves the merged model behavior while moving cross-step credential
  transport to a validated mode-0600 file. Fresh protected-main Strix and Noema
  evidence is still required after that stronger boundary integrates.

## 2026-08-28 post-#1373 request-envelope recheck

- #1373 was merged by `seonghobae` at `8f84b661e468de451ba5c076dc938f342bf52d70`
  to exercise the post-merge runtime path. Main Strix run `33143805461`
  reached the contextual-orchestrator sidecar and sent the qualified
  `openai/orchestrator/free` request, then failed closed with HTTP 413
  `request_too_large` from the pinned gateway. This proves the earlier model
  qualification defect was repaired, but the review request envelope was
  still smaller than the Strix/Noema tool-and-source context.
- The fix is scoped to the review launcher: use an explicit bounded 8 MiB
  `SecurityConfig.max_body_bytes` for the sidecar while preserving the
  contextual-orchestrator library's generic 64 KiB default. Noema run
  `33143860315` was a successful `workflow_run` event handler but skipped
  because the push event had no associated pull request; it is not an LLM
  verdict.

## 2026-08-28 #1374 trusted-base runtime boundary

- Follow-up PR #1374 merged at head
  `3d7cf123ea7459b7f0082bb354280288866256db` with merge commit
  `7c55295ff2dd863d983822d991e67ba037e8f186`; its launcher sets the bounded
  8 MiB review envelope, and its sidecar boot check validates that keyword
  against the exact pinned orchestrator SHA before discovery. Its terminal
  review decision was not an independent `APPROVED`, so this remains an
  observed merge event rather than protected-main governance proof.
- PR-target Strix run `33145070402` used trusted workflow source SHA
  `8f84b661e468de451ba5c076dc938f342bf52d70`, not the PR launcher. It reached
  the pinned sidecar and then failed three bounded attempts with HTTP 413
  `request_too_large`; this is evidence of the pre-merge trusted-base path,
  not evidence that #1374's launcher setting failed.
- PR-target Noema run `33145070347` also reached the pinned sidecar and set
  `orchestrator/free`, then skipped before the LLM call because the current
  head had no primary OpenCode approval. Required OpenCode run `33145070315`
  failed closed for the same missing current-head verdict. Therefore the
  PR-target result was not an LLM verdict.
- Post-merge Strix run `33145807836` used trusted workflow source SHA
  `7c55295ff2dd863d983822d991e67ba037e8f186`, reached
  `openai/orchestrator/free`, and produced no HTTP 413 or
  `request_too_large`. It failed closed after three bounded attempts because
  the Strix Caido target was unavailable at `127.0.0.1:48080`, reported as
  `STRIX_PROVIDER_UNAVAILABLE`; this proves the request-envelope fix on main,
  but not a successful end-to-end vulnerability scan.

## 2026-08-28 OpenAI request-envelope specification check

- OpenAI's official API reference models a function-tool `description` as an
  optional string and does not publish a universal 1024-character field limit.
  The official OpenAPI document also contains no `413` or
  `request_too_large` response definition for the inference operations. The
  `413 Content Too Large` observed above is therefore the vendored gateway's
  HTTP framing response, not evidence of an OpenAI tool-description rule.
- OpenAI's current images-and-vision guide specifies up to 512 MB total payload
  for an image-input request and accepts an image URL, Base64 data URL, or file
  ID in ordinary model-input JSON. The Files API separately permits 512 MB per
  uploaded file, and Batch separately permits 200 MB JSONL files. These are not
  one universal limit for every JSON endpoint. The sidecar's 8 MiB limit is an
  explicitly local, bounded policy for text/tool review envelopes and is not
  claimed to provide general multimodal compatibility: a large inline Base64
  image can fail locally even though a URL or file ID keeps the JSON small. A
  future general multimodal proxy needs a separately governed streaming/spooling
  and provider-capability contract; `/files` alone does not cover inline image
  data URLs. The pinned-SHA probe accepts a body of 65,609 bytes and preserves
  1,025-, 1,026-, and 2,000-character tool descriptions byte-for-byte;
  provider/model context failures remain separate runtime evidence.
- PR #1379 exact head `4a25c46dc2fe046368f304a589885ebffb757dfc`
  reached the pinned sidecar in Strix run `33150437853`; sidecar provisioning
  and the request-envelope preflight passed, but all three scanner attempts
  received HTTP 500 `internal_error` (request IDs
  `7ef2a6bfd7494f80adbf9109b2f5dea2`,
  `193276c218884651a3940dd9a30bcf97`, and
  `ff529b84b101458eae03287d3e8df52d`). No 413 or vulnerability report was
  emitted, so this is an incomplete provider/backend result rather than proof
  of either request-size rejection or scan success. The pinned server currently
  collapses otherwise-unhandled provider exceptions into that generic 500.
  Contextual-orchestrator PR #904 is the separately governed candidate that
  classifies upstream request-size rejection, retries eligible members of the
  virtual `orchestrator/free` pool, and returns `request_too_large` only after
  eligible-provider exhaustion. The sidecar pin must remain on protected main
  until that change is merged and then be reverified by a fresh exact-head
  Strix run.

## 2026-08-29 512 MiB review-envelope bootstrap

- Contextual-orchestrator PR #904 head `6cd7d57c177d945f67ba3b86b699949584bc6b7e`
  passed its full unit/contract suite, Required bootstrap, Noema, fuzz, and
  security checks with zero unresolved review threads. Its Required Strix ran
  the pre-change `.github` main sidecar pin and failed three times with generic
  HTTP 500 responses and no vulnerability report; Required OpenCode failed
  closed because no current-head formal verdict existed. The bootstrap cycle
  was resolved by an explicitly authorized admin merge to protected-main commit
  `b21645116b352967e50fc497b87eb745b9cc8c61`; this is an observed bootstrap
  merge, not ordinary protected-governance proof.
- `.github` PR #1379 then pinned that protected-main orchestrator commit and
  changed only the loopback, bearer-authenticated, per-job review sidecar from
  the prior 8 MiB local envelope to the OpenAI image-input ceiling of 512 MiB.
  The generic orchestrator default remains 64 KiB; Files retains its separate
  512 MB per-file and 200 MB Batch JSONL contracts. The branch passed 216
  Required/Noema/Strix/OpenCode/autofix contract tests plus the Strix shell
  smoke. Because pull-request-target loaded the old trusted base pin
  `889b24f8547d059d1bf2b2f9a043aff15c9ea59d`, branch Noema success was not
  runtime proof of the new pin. The same explicitly authorized bootstrap merge
  produced `.github` main `e1b03eebc6dc5c85aed393e5928927c96376cf46`.
- Acceptance remains open until a fresh post-merge PR run proves that Required
  Noema and Strix provision `b2164511…`, route only through
  `contextual-orchestrator/orchestrator/free`, and produce an actual LLM verdict
  or typed provider result. A green event handler that skips the LLM call is not
  acceptance evidence.

## 2026-08-30 hourly loop recheck: bootstrap/sidecar-pin cycle still open, one independent fix landed

**Superseded by the entries below.** This section was drafted before #1413
(Strix `orchestrator/auto` route) and #1422 (stale sidecar-pin refresh)
merged into `main`; its premise that they "have not merged" no longer holds.
Kept here, unedited, only as a record of the queue's state at that earlier
point in the loop — see "2026-08-30 post-#1413/#1422 backlog refresh cycle"
below for the accurate current-cycle account. (This same annotation was lost
from an earlier resolution of this PR's own merge conflict against `main`,
which also silently dropped the "2026-08-30 sidecar pin staleness
recurrence" section below out of the file entirely; both are restored here.)

- Reconfirmed at the start of this hourly pass: protected `main` is
  `6c8ee24046d743b3981c566c6e29f99f09137f6a` (this has moved on from the
  2026-08-26 107-open-PR snapshot's `826b92394c63deb6981c3a8d16a724d71f85a0d7`
  through ordinary merges since; it is not the same commit). #1413 (Strix
  `orchestrator/auto` route), #1422 (stale contextual-orchestrator sidecar
  pin refresh), and #1414 (bootstrap `if:` guard removal) have not merged
  into this current `main`; no human admin bootstrap merge landed this
  cycle.
- Sampled the newest open PRs (#1394, #1398, #1411, #1416, #1417, #1418,
  #1419, #1420) against current-head job logs. All of #1411, #1416, #1418,
  #1419, and #1420's `strix`/`noema-review`/`opencode-review` failures
  reproduce one of the three already-diagnosed systemic causes rather than a
  new defect: the Strix `orchestrator/auto` LiteLLM/HTTPS-base rejection
  (#1413's fix), the redundant bootstrap `if:` guard tripping
  `exact-head-path-policy` (#1414's fix — seen verbatim on #1411 and #1420:
  `FAIL: opencode required workflow bootstrap must not depend on
  required-workflow event payload fields`), and the stale
  `contextual-orchestrator` sidecar pin `b21645116b352967e50fc497b87eb745b9cc8c61`
  failing gateway preflight with `request_failed status=413
  code=request_too_large` / `sidecar exited before healthz` (#1422's fix —
  seen verbatim on #1418). These are three independent fixes, not
  interchangeable: the Strix `orchestrator/auto` failure clears only once
  #1413 merges; the sidecar-pin failure clears only once #1422 merges; the
  bootstrap `if:` guard failure clears once any of #1413, #1414, or #1422
  merges (all three carry that fix). A PR failing on more than one signature
  needs each corresponding fix on `main`, not just one merge. None of these
  failures were reclassified or worked around.
- One independent, non-systemic defect was found and fixed this pass: #1417
  ("Bolt: label_section 탐색 로직 최적화") added a `ThreadPoolExecutor`-based
  `probe_agent` nested closure to
  `scripts/ci/contextual_orchestrator_review_launcher.py` without a
  docstring, dropping the pinned `interrogate --fail-under 100` gate to
  98.8% (`_preflight_review_agents.probe_agent (L174) MISSED`) and failing
  #1417's `Hourly cadence, immutable source, NIM credential, and conflict
  scope` check independently of the three systemic blockers above. Fixed by
  adding a one-line docstring and pushed to #1417's existing head branch
  `bolt-opt-label-section-2431233332957705980` (commit `190e505`). Verified
  locally: `interrogate` now reports 100.0% over the five pinned files, the
  full suite (`1873 passed, 1 skipped, 17 subtests`) and the focused
  `opencode_review_normalize_output`/`contextual_orchestrator_review_*`
  suites are unaffected, and `compileall`/`git diff --check` pass.
- #1394 (Sentinel SSRF fix touching `sandboxed_web_e2e.py`) and #1418
  (Sentinel SSRF/path-traversal regex fix touching
  `agent_mention_sweep.py`/`organization_commercial_readiness_loop.py`) were
  checked against each other and confirmed **not** duplicates — disjoint
  files, disjoint vulnerabilities. #1394 also carries a stale `base` (its
  branch predates several recent `main` merges) and needs an ordinary
  merge-base-into-head before its checks are meaningful; not attempted this
  pass given the time budget.
- No open PR had a qualifying independent `APPROVED` review this pass
  (`is:pr is:open review:approved` returned zero results repo-wide), so
  priority 4 (merge) had no eligible candidate.
- Next hourly pass: re-check whether #1413/#1414/#1422 merged; if still
  open, keep sampling the backlog for independent (non-systemic) defects the
  way this pass found #1417's, and consider merging `main` into #1394's head
  to get it off its stale base.

## 2026-08-30 orchestrator/free pool exhausted by upstream ZDR hardening

- **Root cause (verified by live, end-to-end local reproduction, not log
  inference).** After #1422 bumped `ORCHESTRATOR_PIN_SHA` to
  `5f2753ace756ddd81049a5221d55e8977572a416`, the first hosted `noema-review`
  run on the new pin (`.github` PR #1423, head
  `954d57b46fd8896ba0fb572a4fc662aa6a684c0a`) failed with `sidecar exited
  before healthz (status 1); stderr: omitted_unstructured_lines=1` — a new
  failure signature, distinct from the stale-pin HTTP 502/413 class the
  2026-08-30 entry above describes. Between the old pin
  (`b21645116b352967e50fc497b87eb745b9cc8c61`) and the new one, upstream
  `contextual-orchestrator` commit `952996ec` ("fix(discovery): keep
  OpenRouter catalog evidence-only") deliberately set
  `ProviderModelSource(provider_name="openrouter", ...).evidence_only=True`
  (previously `False`) — an intentional, ZDR-privacy-motivated hardening
  (OpenRouter routes to many third-party backends with varying retention
  policies, so it may no longer be used as a *serving* agent, only as a
  source of per-model ZDR evidence for other providers' matching canonical
  ids). This is a correct fix on the orchestrator side and must not be
  reverted or weakened.
- The org's sidecar (`scripts/ci/contextual_orchestrator_review_launcher.py`)
  builds the `orchestrator/free` pool only from `is_free=True` routes among
  the five credentialed providers (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`,
  `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`).
  `openrouter` was, and had always been, the *only* one of those five whose
  discovery response carries genuine per-model pricing (`contextual_orchestrator/model_discovery.py`'s `_parse_openai_compatible` reads `row["pricing"]`, present only in OpenRouter's `/v1/models`
  response shape). NVIDIA NIM, OpenAI, and Bytez publish no pricing via their
  list-models endpoints at all — confirmed by an unauthenticated live probe
  of `https://integrate.api.nvidia.com/v1/models` in this session, which
  returns only `{id, object, created, owned_by}` per model, and by
  `contextual_orchestrator`'s own `_parse_bytez` docstring ("Bytez prices by
  GPU-second ... leaving per-1k pricing unset is more honest than a
  misleading estimate"). `.github`'s own
  `tests/test_contextual_orchestrator_review_live_discovery_contract.py`
  already encoded this as `cost_evidence == "unknown"` for openai/nvidia_nim/
  nvidia_nim_sub/bytez in its live-shape fixture — this was a known,
  pre-existing structural dependency on OpenRouter for the free pool, not a
  new assumption. With `openrouter` now `evidence_only`, the launcher's
  `_routable_discovered_models()` filter drops all 540 OpenRouter rows before
  the free-pool selection ever runs, so `selected_models` is empty and
  `main()` raises `SystemExit("review sidecar discovered no eligible models;
  orchestrator/free would fail closed")` — exit 1, before `serve()`, hence
  before `/healthz`.
- **Live reproduction** (this session, real network calls, fake-but-present
  values for the five secrets, pinned commit `5f2753ac…` installed from its
  own `requirements.lock`): `discover_all_models()` returned 682 models —
  `openrouter`: 540 total, 60 genuinely free, but 540/540 `evidence_only`;
  `nvidia_nim` and `nvidia_nim_sub`: 71 each, 0 free; `openai`/`bytez`:
  `http_status_401` (fake key, but note neither provider's list endpoint
  carries pricing regardless of auth outcome). Routable (non-evidence-only)
  free models: **0**. Running
  `scripts/ci/contextual_orchestrator_review_launcher.py` directly end-to-end
  reproduced the exact hosted signature: raw stderr
  `review sidecar discovered no eligible models; orchestrator/free would
  fail closed`, exit 1. This is deterministic and structural, not a
  transient provider/network fluke — every future `noema-review` run with
  this exact five-secret credential set will fail identically until the free
  pool gets a real, non-OpenRouter zero-cost source, so this blocks PR review
  org-wide, not just PR #1423.
- **Independent bug found and fixed in this pass (safe, no policy
  tradeoff):** `scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py`'s
  `_PREFIX_SUMMARIES` allowlist still matched the launcher's *old* wording
  ("no zero-cost models"), not the current "no eligible models" text, and had
  no entry at all for the launcher's missing-auth-token or
  missing-provider-credential `SystemExit` messages. All three fell through
  to `omitted_unstructured_lines=N`, which is exactly why PR #1423's hosted
  log showed only `omitted_unstructured_lines=1` instead of the actionable
  cause above — the redaction was hiding a real, non-secret diagnostic, not
  protecting a secret. Fixed the three prefixes/summaries and the matching
  pinned assertions in
  `tests/test_contextual_orchestrator_review_runtime_preflight.py`; full
  `.github` suite (1875 passed, 1 skipped, 25 subtests), `coverage report`
  (the changed file itself is 100%; the pre-existing repo-wide 99% is the
  already-tracked `scripts/ci/pingora_edge_policy.py:274` gap owned by
  #1398, not introduced here), and `interrogate` (100.0%) all pass on this
  change alone.
- **What is intentionally NOT fixed by this pass, and needs a product/human
  decision, not a unilateral code change:** restoring a non-empty
  `orchestrator/free` pool. Two candidate paths, neither exercised or
  authorized here: (a) accept real provider spend by pointing
  `CONTEXTUAL_ORCHESTRATOR_POOL` at `auto` (already fully implemented in the
  launcher as a priced fallback) — this trades away the "fail-closed
  zero-cost" guarantee `docs/CWL-MASTER-CONTEXT.md`/`CLAUDE.md` describe for
  every PR review org-wide, a budget-owner call; or (b) wire in a genuine
  zero-cost provider — `contextual_orchestrator`'s `opencode_zen` source
  already cross-references real Models.dev pricing (not a self-reported
  flag) to compute `is_free` honestly, and its credential
  (`OPENCODE_ZEN_API_KEY`) already exists as an org secret (used today only
  by `opencode-review.yml`'s separate OpenCode Zen GitHub Models config, not
  passed to this sidecar) — but wiring it in also needs a new
  `scripts/ci/zdr_policy.py` `PROVIDER_ZDR_SCOPE["opencode_zen"]` attestation
  entry (that table currently `KeyError`s on an unknown provider name by
  design, so skipping this would crash every ZDR-required — i.e.
  private/internal-repo — review instead of just noema-review's current
  public-repo failure) and live verification, with a real key, that
  opencode.ai/zen's discovered free models are actually
  general-chat/tool-call-capable and pass the sidecar's runtime preflight —
  none of which this pass could validate without provisioning real
  credentials. Neither option is a small, obviously-safe patch, so it is
  left open here rather than forced.
## 2026-08-30 sidecar pin staleness recurrence

- Same class of defect as the 2026-08-29 entry above recurred within one day:
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`'s
  `ORCHESTRATOR_PIN_SHA` default (`b21645116b352967e50fc497b87eb745b9cc8c61`)
  was already 103 commits behind `contextual-orchestrator` `main`. Observed
  directly in hosted `noema-review` job logs (`.github` PR #1421,
  `ContextualWisdomLab/contextual-orchestrator#857` and others): the
  vendored sidecar's own preflight against the stale pin fails closed with
  `gateway preflight returned HTTP 502` (and, on a differently-shaped request,
  `request_failed status=413 code=request_too_large`) before the model pool
  can run, so `opencode-agent`/Noema never post a verdict and the required
  `opencode-review`/`noema-review` checks fail on unrelated PRs across both
  repos. Confirmed via `contextual-orchestrator` main history that
  `5f2753ace756ddd81049a5221d55e8977572a416` is the current `main` HEAD and
  passes its own Tests/Security/Fuzz gates.
- This PR bumps the pin to `5f2753ace756ddd81049a5221d55e8977572a416` in the
  three places the contract tests pin it: the sidecar script default,
  `tests/test_contextual_orchestrator_review_sidecar_contract.py`'s
  `ORCH_PIN_SHA`, and `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`'s
  "today" reference. `requirements.lock` needs no separate sync — the sidecar
  installs it fresh from the freshly-checked-out pinned commit, not from a
  copy embedded in this repo.
- Acceptance remains open the same way the 2026-08-29 entry describes: this
  fixes the reproduced local preflight failure and all static contract tests
  pass, but only a fresh post-merge hosted `noema-review`/`opencode-review`
  run against the new pin is proof the live gateway path actually completes
  and posts a verdict. Given this is the second staleness incident in as many
  days, the underlying gap is process, not just this one value: nothing
  currently keeps this pin near `contextual-orchestrator` `main` on an
  ongoing basis. A scheduled or CI-triggered pin-freshness check (e.g., fail
  a nightly job once the pin falls more than N commits or M days behind a
  green `contextual-orchestrator` main) would close that gap; not implemented
  in this PR, left for a follow-up.

## 2026-08-30 post-#1413/#1422 backlog refresh cycle

- Confirmed at the start of this pass: protected `main` is
  `c48859ac3919f1e7d2f24e744e5c551b94e66ac2`, which includes both #1413
  (Strix `orchestrator/auto` route recognition) and #1422 (sidecar pin bump
  to `5f2753ace756ddd81049a5221d55e8977572a416`) merged. Both root-cause
  fixes are live on `main` as of this pass, alongside the pre-existing
  bootstrap `if:` guard fix.
- Since `strix`/`opencode-review`/`noema-review` are `pull_request_target`
  required checks, an already-open PR does not get a fresh run merely
  because `main` moved; each needs a new push event on its own branch. This
  pass merged current `main` into as many otherwise-viable open PR branches
  as could be validated in the time available, always as an ordinary
  non-force-push merge commit (never a rebase), and only after a local
  test-merge confirmed either a clean merge or a genuinely trivial conflict.
- **15 PRs refreshed against the new `main`** (all pushed as plain merge
  commits):
  - Clean merges, no conflicts (6 via `update_pull_request_branch`, GitHub's
    native "merge base into head" API): #1416, #1417, #1418, #1419, plus
    #1276 and #1275 (dependency/security-action version bumps).
  - Trivial conflicts resolved by hand, all confined to the additive
    `## [Unreleased]` list in `CHANGELOG.md` (both sides had independently
    appended unrelated bullets to the same list; resolution kept both):
    #1411, #1398, #1397, #1348, #790, #821, #1391.
    - #1348 additionally collided on Gap ID: its own draft `G-15` entry
      (queue-hygiene live-ref race, `ContextualWisdomLab/LineageWeave#667`) numerically collided
      with `main`'s already-merged, unrelated `G-15` (attachment-processing
      boundary). Renumbered the branch's entry to **G-16**; confirmed no
      test or cross-reference in that PR's diff pins the literal string
      `G-15`, so the rename is safe.
    - #1391 additionally conflicted in
      `tests/test_pr_review_autofix_nvidia_nim_contract.py`'s
      `REVIEW_DISPATCH_BLOB_SHA` pinned-blob-hash constant, because #1391's
      own change (a Cargo-prefetch step) edits
      `.github/workflows/opencode-review-dispatch.yml` inside the same
      region `main` had independently changed, so neither side's pre-merge
      constant was correct post-merge. Resolved by computing
      `git hash-object` on the actually-merged file
      (`50752bfef4c8db87bf971c5e9c2a98da72fc281c`) rather than guessing;
      verified with `pytest tests/test_pr_review_autofix_nvidia_nim_contract.py`
      (23 passed).
  - Already on current `main`, no merge needed, just stuck: #1233 and #1176
    both showed `base.sha` already equal to current `main` yet
    `mergeable_state: blocked` (no conflict, just no fresh check run).
    Pushed an empty retrigger commit to each to generate the required new
    event.
- **8 PRs left untouched this pass due to real (non-trivial) conflicts**,
  each confirmed by an actual local `git merge --no-commit --no-ff origin/main`
  rather than by SHA-staleness alone: #1394 and #1347 (both edit
  `scripts/ci/sandboxed_web_e2e.py`, which `main` has independently changed
  for its own SSRF hardening — same file, overlapping logic, not attempted);
  #1415 (edits `scripts/ci/contextual_orchestrator_review_launcher.py`,
  colliding with #1422's own sidecar changes); #1382 (nine conflicting files
  spanning `strix.yml`, the ZDR policy module, and the sidecar script —
  large surface, not attempted); #1009 (eleven conflicting files across
  agent-mention routing, the merge scheduler, and Strix); #834 (conflicts in
  `scripts/ci/contextual_orchestrator_review_policy.py`); #789 (six
  conflicting files including `AGENTS.md` and the sidecar token loader);
  #1114 (`strix.yml` — `main` has already independently grown equivalent
  retry-with-backoff visibility-lookup logic to what #1114 itself proposed,
  so this PR may now be moot rather than merely stale; flagging for owner
  review rather than guessing). None of these were pushed; none were force
  anything.
- **Independent, non-systemic defect found on #1420** (whose branch was
  already exactly on current `main` — no refresh needed): its fresh
  `noema-review` run *did* vendor the corrected sidecar pin
  (`5f2753ace756…`, confirmed in job logs) but then failed with
  `request_failed status=413 code=request_too_large` during model
  discovery, fell back to the OpenRouter ZDR feed, and the sidecar process
  exited before its own healthz check with a non-zero status. Its
  `opencode-review` gate failed separately and for an unrelated reason: at
  the moment it ran, no `opencode-agent` review existed yet at the exact
  current head (the verdict-lookup gate and the actual model dispatch that
  posts the verdict appear to run on different, only loosely synchronized
  schedules). Neither failure traces to the three already-diagnosed root
  causes (Strix model recognition, the bootstrap guard, or the stale pin
  value) — this is new evidence of a still-open sidecar/gateway runtime
  defect and a possible review-dispatch timing gap, not yet root-caused or
  fixed. Left for a follow-up pass; not in scope to fix blind this cycle.
- **This PR's own earlier section above was corrected in place rather than
  left to stand**, per the "search existing PRs for the same root cause
  first" instruction: its content predated #1413/#1422 landing and was
  simply wrong about the current backlog state, so amending this PR (which
  already exists, unmerged, solely to record an hourly-loop dated entry) was
  preferred over opening a duplicate doc-update PR for the same purpose. An
  earlier attempt at this same correction, pushed concurrently by another
  process to this same branch, resolved its `main`-merge conflict by
  dropping the "2026-08-30 sidecar pin staleness recurrence" section above
  out of the file entirely; that section is restored verbatim above as part
  of this correction.
- **No PR was merged this pass.** Every refreshed PR's required
  `opencode-review`/`noema-review` verdict depends on an asynchronous model
  dispatch (observed taking on the order of minutes just for sidecar
  bootstrap and model discovery before any verdict posts) that had not
  completed for any of the 15 refreshed PRs by the time this pass ended;
  none had a qualifying current-head `APPROVED` review yet. This is expected
  for one pass in an hourly loop, not a defect: the next pass should re-read
  each of the 15 PRs' current-head checks and reviews, and merge whichever
  come back green and approved with `--match-head-commit` per §5.

## 2026-08-30 discovery-error visibility gap in the review sidecar launcher

- While investigating the "2026-08-30 orchestrator/free pool exhausted by
  upstream ZDR hardening" entry above, the repo owner asked why a local
  reproduction of that incident showed only 3 of the 5 configured providers
  (`openrouter`, `nvidia_nim`, `nvidia_nim_sub`) and never `bytez`/`openai`,
  despite all 5 credentials being registered.
- Traced to a real, separate bug in this repo (not `contextual-orchestrator`):
  `scripts/ci/contextual_orchestrator_review_launcher.py`'s `main()` called
  `discovered, _ = discover_all_models()`, discarding the second tuple
  element entirely. `discover_all_models()` itself correctly isolates and
  returns each provider's failure as a `ProviderDiscoveryError` (bounded,
  secret-free: a `provider_name` plus a stable `error_code` classification
  such as `http_status_401`/`timeout`/`transport_error`/`invalid_response`,
  confirmed by reading `_provider_discovery_error_code` and
  `ProviderDiscoveryError.__init__` directly) — the launcher simply never
  looked at them. An operator reading CI logs could not tell "this provider
  legitimately has zero free models" from "this provider's credential or
  discovery request is silently broken", which is exactly the ambiguity that
  made the earlier ad hoc reproduction inconclusive about bytez/openai.
- Fixed by adding `_log_discovery_errors()` to the launcher, called
  immediately after `discover_all_models()`, printing one
  `provider_discovery_failed provider=<name> code=<code>` line per error to
  stderr (non-fatal, matching `discover_all_models()`'s own "one provider's
  failure never blocks the others" contract). Extended
  `scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py` with a
  matching bounded regex (mirroring the existing `request_failed` pattern)
  so this new diagnostic is allowlisted through to CI evidence instead of
  falling into `omitted_unstructured_lines=N` — the same class of redaction
  gap the "2026-08-30 sidecar-diagnostics gap baseline" fix (#1425) closed
  for the fail-closed exit message.
- This does not by itself restore `orchestrator/free`; it only makes any
  future bytez/openai discovery failure (credential expiry, API changes,
  etc.) visible instead of silently indistinguishable from "no free models
  today". Root cause and fix for the free-pool exhaustion itself remain
  tracked in the entry above.
- Validation: `PYTHONPATH=. python3 -m coverage run -m pytest tests -q` —
  1878 passed, 1 skipped, 25 subtests; `interrogate` 100.0%; `git diff
  --check` clean. `scripts/ci/contextual_orchestrator_review_launcher.py`
  remains outside the coverage gate per this repo's pre-existing, documented
  `pyproject.toml` `[tool.coverage.run]` omission (it imports the vendored
  orchestrator library, installed only inside the sidecar's own runtime);
  the new `_log_discovery_errors` helper is still covered by two new
  regression tests exercising it directly via `runpy.run_path`, consistent
  with this file's existing test pattern for the same module's other
  runtime-only helpers.

## 2026-08-30 orchestrator/free root-cause fix landed; sidecar pin bumped

- Root cause of the "orchestrator/free pool exhausted by upstream ZDR
  hardening" entry above is now fixed upstream:
  `ContextualWisdomLab/contextual-orchestrator#919` generalized the
  ADR-0032 Models.dev cost cross-reference from `opencode_zen`-only to also
  cover `nvidia_nim`/`nvidia_nim_sub`/`openai`, and — the actual blocker
  found during that PR's own review — fixed `_fetch_json` sending no
  `User-Agent` header, which caused `models.dev` (Cloudflare-fronted) to
  reject every discovery request with HTTP 403 error 1010. That 403 had been
  silently breaking the Models.dev join for **all** providers, including the
  pre-existing `opencode_zen` path, since before this incident was first
  observed; without it, no provider could ever populate `orchestrator/free`
  regardless of the OpenRouter `evidence_only` hardening this baseline
  previously identified as the proximate cause.
- Merged into `contextual-orchestrator` `main` as squash commit
  `30c6d71680e659f25a0a433d4726ad0d437f9757`, with owner-authorized admin
  bypass past `opencode-review`/`noema-review`/`strix` — those three required
  checks run this org's central review pipeline against `.github`'s
  *current* `main` pin, which (before this PR bump) still pointed at the
  broken pre-fix commit, so they failed on the exact chicken-and-egg this fix
  resolves: the PR that restores `orchestrator/free` cannot itself pass a
  required review that depends on `orchestrator/free`. All 5 review threads
  (Devin, CodeRabbit) were independently resolved before merge; local suite
  was 2676 passed.
- This PR bumps `ORCHESTRATOR_PIN_SHA` from
  `5f2753ace756ddd81049a5221d55e8977572a416` (the #1422 pin) to
  `30c6d71680e659f25a0a433d4726ad0d437f9757` in the same three places #1422
  established as the contract: the sidecar script default
  (`scripts/ci/contextual_orchestrator_review_sidecar.sh`), the contract
  test's `ORCH_PIN_SHA`
  (`tests/test_contextual_orchestrator_review_sidecar_contract.py`), and
  `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`'s "today"
  reference. `requirements.lock` needs no separate sync for the same reason
  #1422 recorded — the sidecar installs it fresh from the freshly
  checked-out pinned commit.
- Acceptance is open the same way #1422's entry describes: this closes the
  reproduced root cause (live-verified against the real `models.dev/api.json`
  endpoint both before the fix, HTTP 403, and after, HTTP 200) and all
  static contract tests pass, but only a fresh post-merge hosted
  `noema-review`/`opencode-review` run against this new pin is proof the live
  gateway path actually discovers a free model and posts a verdict.
  Following up on that hosted-run confirmation is the concrete next check for
  this entry, not a new code change.

## 2026-08-30 hosted-run confirmation of #1430 fails at a new stage: live preflight, not discovery

- This is exactly the follow-up hosted-run confirmation the entry above asked
  for, and it does **not** come back clean. Three independent fresh
  `noema-review` runs were forced against current `main`
  (`755fe8e1`/`30c6d716`, i.e. with #1430's fix already in effect, since
  `pull_request_target` always executes the *base* branch's copy of
  `scripts/ci/contextual_orchestrator_review_sidecar.sh` regardless of the
  PR's own content): #1432 twice (`61de349f`, jobs `33303869223` then
  `33304289755` after a second forced re-run) and #1418 once (`7b4161fd`,
  job containing check id `99238526905`). All three reproduce the identical
  new failure, verbatim: `vendoring contextual-orchestrator @
  30c6d71680e659f25a0a433d4726ad0d437f9757` → discovery completes with
  **zero** `provider_discovery_failed` lines (the sentinel
  `discovery_diagnostics_complete` is reached cleanly, so `orchestrator/free`
  is genuinely populated this time, unlike the pre-#1430 empty-pool
  signature) → `review sidecar preflight failed` (the launcher's
  `_preflight_review_agents` in `scripts/ci/contextual_orchestrator_review_launcher.py`
  raises `ReviewPreflightError("no provider route passed the Strix
  plain-chat preflight", report)`) → `sidecar exited before healthz (status
  1)`. Every run also logs `omitted_unstructured_lines=4`: the redacting
  stream sanitizer (`scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py`)
  is, by design, dropping the four lines that would explain *which* routes
  were rejected and why (provider response bodies/exception text are
  intentionally never allowlisted into CI logs) — so the exact per-route
  `error_type`/`http_status` only exists in the `preflight_report` JSON
  (`$STRIX_EVIDENCE_DIR/contextual-orchestrator-preflight.json`), which only
  `strix.yml` uploads as an artifact; `noema-review.yml` and
  `opencode-review-dispatch.yml` run the identical sidecar script but do not
  upload it, so this pass could not retrieve the artifact (a same-cycle
  `strix` run on unrelated PR #1176 was still queued behind the
  per-repository concurrency group after 15+ minutes and was not waited
  out).
- This is a **different** defect from the one #1430 fixed, not a recurrence
  of it: the pool is not empty and discovery is not failing. Something
  downstream — plausibly (not yet confirmed) shared-provider-key rate/burst
  pressure from the large number of PRs' `noema-review`/`opencode-review`/
  `strix` jobs re-triggered by #1430 landing, or a genuine defect newly
  exposed by #919's provider-family generalization (`nvidia_nim`/
  `nvidia_nim_sub`/`openai` routes that previously never reached live
  discovery) — is rejecting every one of the (up to 12) selected zero-cost
  candidates at `ModelClient.proxy_send_once`. Two observations argue
  against pure rate-limiting: the failure is 3-for-3 reproducible with no
  intervening success, and the two #1432 runs were ~9 minutes apart (well
  outside a typical burst window) yet failed identically. This needs a
  `preflight_report` artifact (or direct provider-side log access this
  session does not have) to root-cause conclusively — not assumed to be one
  cause or the other here.
- **Scope of impact**: essentially every non-draft open PR's
  `noema-review`/`opencode-review`/`strix` required checks are currently
  blocked on this, independent of anything in the PR's own diff or how
  stale its branch is — confirmed by sampling ~45 open PRs' latest check
  runs and finding the `noema-review`/`opencode-review`/`strix` failures
  either stale (pre-dating one of today's earlier fixes: #1413, #1414,
  #1422, or #1430) or, on the three forced fresh re-runs above, this new
  signature. No PR sampled this pass showed a `noema-review` failure
  distinct from this signature or from the three already-diagnosed
  pre-#1430 systemic causes recorded in the 2026-08-30 hourly-recheck entry
  above.
- **Not bypassed.** The owner's standing bypass authorization for this repo
  covers two verified structural signatures only: a PR whose own diff edits
  `.github/workflows/`/`scripts/ci/` review-pipeline files (the
  `pull_request_target` trust-boundary case #1430 itself hit) or the
  pre-#1430 empty-pool chicken-and-egg. Neither applies here: discovery is
  not empty, and none of the PRs sampled this pass (including #1176, which
  edits `.github/workflows/audit-central-ruleset.yml` and
  `scripts/ci/audit_central_required_workflows.py` — real workflow/CI files,
  but not the review-pipeline ones, and not the cause of its own
  `noema-review` failure) edit the review-pipeline files themselves. Per the
  owner's explicit conservative instruction, an unclear or newly-surfaced
  failure reason is not bypass-eligible, so nothing was bypass-merged this
  pass.
- Given the above, this pass deliberately did **not** mass-retry
  `update_pull_request_branch`/re-runs across the ~45 affected open PRs:
  three independent forced reproductions already established the failure is
  systemic and deterministic, not per-PR or transient, so repeating the same
  forced re-run dozens more times would only burn shared runner/provider
  quota for the same evidence already in hand.
- Next concrete step (not attempted this pass, given the time budget): get
  one `strix` run's `contextual-orchestrator-preflight.json` artifact on a
  current-`main`-based head (wait out or avoid the concurrency queue) to
  read the real per-route `error_type`/`http_status`, then decide whether
  the fix belongs in `contextual_orchestrator_review_launcher.py` (e.g.
  lower `REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES`/serialize discovery to avoid a
  self-inflicted burst) or in `contextual-orchestrator` itself (e.g. a
  credential-resolution or request-shape regression for the newly-widened
  `nvidia_nim`/`nvidia_nim_sub`/`openai` routes from #919).

## 2026-08-30 sidecar-preflight outage: consolidated evidence and why it is not one deterministic bug

**Supersedes the framing (not the evidence) of the entry above** — same incident,
now with the actual per-route rejection data and a third independent run
sequence, from three converging sources this pass: this session's own three
forced reproductions on `.github` (#1432 x2, #1418 x1, all `SystemExit`
before `healthz`), the `contextual-orchestrator-preflight.json`/
`contextual-orchestrator-discovery.json` artifact recovered from PR #1176's
`strix` run (queued behind #1418's, completed ~09:45), and a fourth
independently-reported run on PR #1433's `noema-review` (`healthz` reached,
then a 502 on the actual gateway request).

- **PR #1176's `strix` artifact is the first look at the real per-route
  reasons**, previously invisible because the sanitizer intentionally
  redacts them from job logs. That run used `orchestrator/auto` (pre-dating
  this pass's now-reverted Strix free/auto edit — see below), so it exercised
  both stages `_preflight_with_fallback` runs:
  - **Primary (free) stage, 4/4 candidates rejected, zero ready**: two
    `nvidia_nim` `deepseek-ai/deepseek-v4-*` candidates timed out
    (`TimeoutError`); two `nvidia_nim` `google/gemma-3-*b-it` candidates got
    `HTTPError` **404** — i.e. NVIDIA has retired those hosted model ids
    (the exact failure class `scripts/ci/select_nvidia_nim_model.py`'s own
    docstring already describes for a *different*, currently-unwired
    caller: "NVIDIA retires hosted models on published end-of-life dates,
    and the endpoint then answers every request with HTTP 410/404"). The
    discovery report shows 46 free-priced rows existed, all `nvidia_nim`/
    `nvidia_nim_sub` duplicates of the same ~23 model ids — so this was not
    a bad selection out of a large pool; it is the **entire** free-tier
    catalog for this run, and 2 of ~23 distinct ids are already dead.
  - **Fallback (priced/auto) stage, 2/8 ready**: `nvidia_nim` and
    `nvidia_nim_sub` `nvidia/nemotron-3-super-120b-a12b` both succeeded;
    `nemotron-3-ultra-550b-a55b` timed out on both keys; all four `openai`
    candidates (`gpt-3.5-turbo`, `gpt-4`, `gpt-4-turbo`, `gpt-4.1`) were
    rejected with **HTTPError 429** (rate-limited) on every single attempt.
    The run only survived because `auto`'s fallback tier existed at all.
- **PR #1433's `noema-review` (pool is always `free` there, no fallback tier)
  reached `healthz` successfully after 23s** — its own internal
  `_preflight_review_agents` found a viable route this time — but the
  shell script's separate, subsequent real `/v1/chat/completions` gateway
  smoke request against the now-serving `orchestrator/free` virtual model
  came back **HTTP 502**. This is a different code path than the launcher's
  own preflight (`ModelClient.proxy_send_once` against explicit candidate
  agents) — it is the running server's own virtual-model routing under a
  real request — so a route that passed the launcher's own preflight
  moments earlier still failed when the server tried to actually serve it.
  A `provider_discovery_failed provider=bytez code=http_status_500` warning
  in the same run is flagged non-fatal by the sidecar itself; not confirmed
  either way as related.
- **Reading all four data points together**, this is not one deterministic
  code defect to patch: it is a **mix of (a) a stale/retired-model gap in
  the free-tier catalog** (the 404s — a real, fixable bug: nothing in
  `contextual_orchestrator_review_launcher.py`'s selection path
  cross-checks a discovered "free" model id against the provider's live
  `/v1/models` catalog before adding it as a preflight candidate, unlike
  `select_nvidia_nim_model.py`'s already-solved pattern for its own,
  currently-unwired caller) **and (b) load-sensitive provider instability**
  (timeouts, the 429s across every OpenAI candidate in one run, the 502 on
  an already-healthy server in another) most consistent with the shared
  five org provider keys being hit by concurrent review-check volume across
  many simultaneously re-triggered PRs org-wide, though this pass could not
  instrument request volume to confirm that mechanism directly. Two runs on
  the same PR #1432 nine minutes apart failing identically (both times
  `omitted_unstructured_lines=4`, same overall shape) argues the *retired-
  model* component is deterministic and load-independent; PR #1176/#1433's
  more varied outcomes (partial success, a different failure stage
  entirely) argue the *timeout/429/502* component is not.
- **Not root-caused to a specific code fix this pass**, and not attempted
  blind: this session has read access to the vendored
  `contextual-orchestrator` source (`/home/user/contextual-orchestrator`)
  but not the five live provider credentials the sidecar registers into its
  KV at runtime, so the 502/timeout/429 half of this cannot be locally
  reproduced from here. The 404-retired-model half has an evidenced,
  scoped fix direction (validate free-catalog candidates against the live
  provider model-list before admitting them to preflight, or drop a
  candidate on its first 404 rather than retrying it every run) but was not
  implemented this pass given the size of the remaining PR backlog and that
  it addresses only part of the outage.
- **Strix `orchestrator/auto` vs `orchestrator/free` — investigated, reverted,
  not changed.** Acting on this session's separate architecture-goal
  instruction ("Strix must route through `orchestrator/free`, not the
  paid-inclusive `auto` pool"), this pass drafted and then **reverted**
  a change switching `strix.yml`'s `STRIX_MODEL`/`CONTEXTUAL_ORCHESTRATOR_POOL`
  from `orchestrator/auto` to `orchestrator/free` (and the matching allowlist
  in the two model-selection steps), before pushing it anywhere. The revert
  is deliberate: `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`
  §Decision and `scripts/ci/strix_required_workflow_smoke.sh` (lines ~183-189,
  which explicitly assert `STRIX_MODEL: contextual-orchestrator/orchestrator/auto`
  **and** assert the workflow does **not** contain
  `STRIX_MODEL: contextual-orchestrator/orchestrator/free`) record a specific,
  evidence-based prior decision: "the 2026-08-29 exact-head DiskSage scan
  proved that four discovered free routes all shared the OpenRouter outage
  domain, which the gateway correctly collapsed to one provider attempt.
  Strix therefore uses the provider-diverse pool supplied by all five
  configured credentials... Strix has no external fallback." That is the
  exact failure mode this pass's own PR #1176 artifact reproduces today
  (the free-only primary stage rejected 4/4 candidates; only `auto`'s
  priced-fallback tier kept that run alive). Switching Strix to `free`-only
  right now would remove the one thing keeping Strix off completely-dark
  during the current outage, not fix anything — it would reproduce, by
  design, the exact incident ADR-0003 was written to prevent. **This is a
  real conflict between the owner's fresh verbal directive and a documented,
  evidenced architectural decision the owner may not have had in view when
  giving it**, not a call this pass should resolve unilaterally in either
  direction; flagged back to the owner rather than merged. If the owner
  still wants `free`-only for Strix after seeing this ADR and today's
  artifact, the mechanical change is small (3 paired edits in `strix.yml`
  plus updating the 5 test files and the smoke script that pin the current
  `auto` strings — scoped, not attempted blind) — but it should happen only
  once the free-catalog's retired-model and provider-diversity gaps above
  are actually closed, or Strix will simply go dark instead of being slow.

## 2026-08-30 ZDR/NIM-routing architecture review (owner-directed)

Investigated the owner's stated goal that Noema/OpenCode/Strix review route
through `contextual-orchestrator`'s `orchestrator/free` specifically, and that
direct-NVIDIA-NIM communication is a removal target.

- **Repo visibility, checked directly rather than assumed**: `.github`,
  `noema`, `contextual-orchestrator`, `naruon`, `fast-mlsirm`, `TEPP`,
  `scopeweave`, `pg-llm-batch`, and `keyverse` are all confirmed **public**
  (this session's git proxy serves them as anonymous public reads with no
  attachment needed). `gyeot` required a genuine authenticated attachment
  (the proxy's "added"/`push`-capable response, not the "already public"
  response the others got) — strong evidence it is **private**, making it
  (or any other private sibling repo not checked here) the concrete case
  where `CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR` actually evaluates `true` and
  the free+ZDR intersection below matters. For `.github`/`noema`/
  `contextual-orchestrator` themselves, confirmed directly in job env
  (`CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR: false` in every log pulled this
  pass) that ZDR is not gating their own reviews — the sidecar-preflight
  outage above is a separate, ZDR-independent problem for those three.
- **`scripts/ci/zdr_policy.py`'s conservative `nvidia_nim`/`nvidia_nim_sub`
  = not-ZDR classification is correct, and now has a direct primary-source
  citation rather than an indirect one.** Fetched NVIDIA's own current
  *NVIDIA API Trial Terms of Service* (the terms actually governing this
  org's free/trial `integrate.api.nvidia.com` key; PDF, v. September 19,
  2025, confirmed still the live document as of 2026-08-30) directly from
  `assets.ngc.nvidia.com` rather than relying on third-party summaries.
  Section 3.3(iv) states NVIDIA collects "User Content and Generated
  Content to improve NVIDIA products and services, including AI models" —
  i.e., prompts/completions from this API **are** used for training; this
  is not merely "unattested," it is affirmative evidence against ZDR.
  Updated both `PROVIDER_ZDR_SCOPE` entries' `source`/`note`/`as_of` fields
  to cite this document and quote the operative clause (code change only,
  `zero_data_retention` stays `False` as it already was); `scripts/ci/`
  interrogate coverage stays 100% and `tests/test_zdr_policy.py`/
  `tests/test_contextual_orchestrator_review_policy.py` (67 tests) still
  pass unchanged, since neither pins the old source URL. **Did not
  reclassify `opencode_zen`** (present in
  `contextual_orchestrator/model_discovery.py`'s five... six provider
  sources but absent from `PROVIDER_ZDR_SCOPE`'s five entries — a real,
  pre-existing gap: `provider_zdr_scope()` would `KeyError` on it if it
  were ever ZDR-checked) because this org's CI sidecar never registers an
  `opencode_zen` credential (only the five `BYTEZ_/NVIDIA_NIM_/
  NVIDIA_NIM_SUB_/OPENROUTER_/OPENAI_API_KEY` secrets exist), so the
  dormant `KeyError` risk is not live here; flagged rather than silently
  left, since it would surface the moment any caller registers that
  credential and requires ZDR.
- **The "free + ZDR is structurally near-empty for private targets" premise
  is confirmed, and is not fixable by reclassifying NVIDIA** — the Section
  3.3(iv) evidence above forecloses that specific path. The only
  theoretical non-empty free+ZDR route left is an OpenRouter model that is
  simultaneously free-priced and present in the live
  `/api/v1/endpoints/zdr` feed; not verified live this pass (would need a
  fresh discovery run against real credentials, which circles back to the
  same access gap as the sidecar-outage investigation above). This remains
  a real, unresolved architecture question for private-repo reviews
  specifically (public repos are unaffected, per the visibility check
  above) and is a policy/product decision, not a code bug this pass can
  close.
- **Direct-NIM-communication audit — narrower than the initial description,
  most of it already resolved or dormant, nothing changed this pass:**
  - `scripts/ci/select_nvidia_nim_model.py` (the "ask NVIDIA's live
    `/v1/models` catalog which model is actually still served" resolver,
    written specifically to survive NVIDIA's own model end-of-life
    rotations) has **zero callers** anywhere in `.github/workflows/` or
    `scripts/`; only its own test (`tests/test_select_nvidia_nim_model.py`)
    exercises it. It is not wired into `pr_review_fix_scheduler.py` or any
    hourly-repair workflow despite its docstring's framing ("the scheduled
    autofix worker"). Dead code today, not a live direct-NIM path — and,
    notably, it already implements the exact live-catalog cross-check that
    would fix this entry's 404-retired-model finding above, just for a
    different, currently-unwired caller.
  - `scripts/ci/run_opencode_review_model_pool.sh`'s `is_nvidia_nim_candidate`/
    `NVIDIA_API_KEY` handling is real, wired code, but its candidate list
    comes entirely from `OPENCODE_MODEL_CANDIDATES`, which
    `.github/workflows/opencode-review-dispatch.yml` (contract-pinned by
    `tests/test_opencode_agent_contract.py`) currently sets to the single
    value `"contextual-orchestrator/orchestrator/free"` — already
    gateway-only, no direct-NIM entries active. `docs/nvidia-nim-opencode-hotfix.md`
    documents that a six-model NIM-prefix hotfix existed for exactly this
    script during a past GitHub-Models outage and was already rolled back
    per its own "Rollback" section; that doc is now stale (describes a
    reverted state as current) and its own instructions say to delete it
    once catalog reliability is restored — worth a follow-up doc cleanup,
    not attempted this pass. The dormant `nvidia-nim` provider block still
    present in root `opencode.jsonc` (lines ~289-294) is inert for the CI
    dispatch path (which generates its own `enabled_providers:
    ["contextual-orchestrator"]` config) but was left as-is since it may
    still serve local/interactive OpenCode use outside CI, which is outside
    the owner's stated CI-routing goal.
  - `scripts/ci/strix_quick_gate.sh`'s `is_contextual_orchestrator_model`
    (still accepts both `orchestrator/free` and `orchestrator/auto`) was
    read but **not narrowed** this pass, for the same ADR-0003 reason the
    Strix `auto`→`free` edit above was reverted — narrowing gate acceptance
    to free-only is the wrong sequencing while `auto`'s fallback tier is
    the only thing keeping Strix off completely-dark right now.
- **Net effect on the owner's goal**: the OpenCode review-dispatch path is
  already fully gateway-only (`orchestrator/free`, no direct-NIM). The
  Strix path is deliberately still `orchestrator/auto` for a documented,
  currently-reproducing resilience reason — changing that needs either the
  free-catalog gaps fixed first or an explicit owner decision to accept
  Strix going dark during outages in exchange for never touching a paid
  route. The private-repo free+ZDR gap is real, unresolved, and not a code
  bug. No dead NIM-direct code was removed this pass because none of the
  three flagged call sites turned out to be a live, unconditional
  direct-NIM path that could be safely deleted without either doing nothing
  (already dead) or removing the one resilience mechanism keeping a
  required check alive during a live outage.

## 2026-08-30 pingora_edge_policy.py binary-evidence gap: two competing open fixes

A live failure on `contextual-orchestrator` PR #906's `required-workflow-bootstrap`
job (`GitHub content evidence for docs/papers/helm-holistic-evaluation-2211.09110.pdf
is not a regular base64 file`) traces to `scripts/ci/pingora_edge_policy.py`'s
`_load_file_content`: GitHub's Contents API stops returning inline
`encoding: "base64"` once a file crosses roughly 1 MB (returning
`encoding: "none"` + a `download_url` instead), and this policy scanner's
`_needs_content_scan` has no exemption for genuinely binary evidence files in
general — any added/modified file without a `patch` (i.e. any binary file,
regardless of size) reaches `_load_file_content`, which always fails once it
tries `raw.decode("utf-8")`. Two **already-open, independent, partially
conflicting** PRs address pieces of this:

- **#1420** adds real, structural validation (`_is_recognized_documentation_image`:
  PNG magic header, chunk order, CRC, zlib-stream, dimension, and scanline
  checks) so an image *suffix* alone cannot exempt a file — consistent with
  this policy's own stated principle. Covers `.png` only; does not touch
  `.pdf`, so it would not by itself fix #906.
- **#1427** adds a flat `NON_RUNTIME_BINARY_SUFFIXES` allowlist (`.avif`,
  `.gif`, `.ico`, `.jpeg`, `.jpg`, `.pdf`, `.png`, `.webp`) that skips
  content-scanning by **extension alone**, no byte-level verification. This
  does fix #906, but for every suffix in that list (not just `.pdf`) it
  reintroduces the exact "extension alone is not an exception" gap #1420
  exists to close for PNG — a shell/config file renamed to `evidence.pdf`
  (or `.png`, `.jpg`, ...) would now bypass the Nginx-runtime-artifact scan
  entirely.
- Left substantive comments on both PRs (this pass) recommending #1420's
  structural-validation pattern be extended to `.pdf` (a bounded magic-
  header/`%%EOF`-trailer check, short of full parsing) rather than merging
  #1427's blanket suffix-trust list, and that the two PRs coordinate so the
  org does not land two divergent implementations of the same policy
  surface. Not resolved in code this pass — both PRs are themselves
  currently blocked by the sidecar-preflight outage above, so neither could
  be re-reviewed to a genuine pass yet regardless of which approach wins.

## 5. 실행 루프와 고객의 다음 행동

각 hourly pass는 아래 순서를 유지한다.

1. 조직·repo 책임 경계를 확인하고, current default branch SHA와 PR head SHA를 새로 읽는다.
2. 열린 PR 하나를 선택해 review threads, formal review commit SHA, required Checks와 failure logs를 확인한다.
3. 실패가 코드 결함이면 root cause를 해당 PR의 최소 범위에서 수정하고, 원격 agent의 concurrent commit은 normal forward history로 보존한다. Force-push하지 않는다.
4. 현실적인 domain test, edge test, docstring/branch coverage, security/SBOM, actionlint/browser evidence를 실행한다.
5. 새 head에서 Checks를 재실행하고 independent current-head approval을 다시 요청한다. OpenCode/Strix/Noema 지연은 blocker가 아니다. 기다리는 동안 다음 PR 또는 Gap을 진행한다.
6. protected ruleset의 approval·resolved thread·terminal Checks·exact head를 모두 충족할 때만 `--match-head-commit` normal merge한다. 조건이 안 되면 merge하지 않고 다음 PR로 진행한다.
7. PR이 소진되면 Project #1과 소비 repo에서 가장 큰 운영자/제품 Gap을 선택해 새 PR을 만들고, 이 문서의 Gap ID를 연결한다. 다음 제품 increment의 소유 저장소는 naruon(G-06/G-15)이다.

운영자는 receipt의 `next_action`만 실행하면 된다. `PR_REVIEW_MERGE_TOKEN` 부재나 provider/runner 지연은 token 값을 로그에 남기지 않고 원인을 기록한 뒤 다음 hourly pass에서 exact head를 재검증한다.

`COPILOT_GITHUB_TOKEN`은 사용하지 않는다. 기존 리뷰용 Agent 키 체계는 유지한다.

### 5.1 이번 루프의 다음 개발 increment

1. ContextualWisdomLab/.github#1297 — current-head Strix serialization과 scoped close cleanup의 hosted Checks·독립 승인을 재확인한 뒤 보호된 auto-merge를 기다린다.
2. ContextualWisdomLab/.github#1345/#1347 — 각각 normalizer 선형 스캔과 web-E2E isolation/SSRF 수정의 terminal Checks·Strix·Noema 증거를 같은 HEAD에서 재확인한다.
3. ContextualWisdomLab/.github#1326 — Appguardrail/macOS hourly caller를 current CodeRabbit finding 및 APA citation evidence와 함께 재검토한다.
4. G-01/G-02는 중앙 control-plane merge evidence의 current-head 품질 문제, G-05/G-06는 naruon ecosystem 소비 증거, G-15는 대용량·미지원 첨부파일 parser registry의 소유 저장소 PR로 연결한다.

## 6. Compliance and data boundary

- PII 원문을 무조건 masking하여 업무를 끊지 않는다. 대신 purpose-bound access lease, field-level encryption/tokenization, consented minimal-disclosure consequence, audited access, revocation/deletion을 사용한다. `COPILOT_GITHUB_TOKEN`은 사용하지 않는다.
- 모델·리뷰·sandbox·Checks·merge·release는 서로 다른 authority다. 하나의 PASS를 approval이나 release로 승격하지 않는다.
- 모든 untrusted input, repository patch, image/base64 payload, model output은 data로 취급하고 command/credential로 해석하지 않는다.
- demo/synthetic fixture는 unit test에만 두며 production seed/fixture에는 포함하지 않는다.
- CSAP and SOC 2 evidence maps belong with consent/lease/tokenization, not blanket PII masking.

## 7. APA 7th references

American Institute of Certified Public Accountants. (2017). *2017 trust services criteria for security, availability, processing integrity, confidentiality, and privacy*. AICPA.

International Organization for Standardization. (2022). *ISO/IEC 27001:2022 information security, cybersecurity and privacy protection—Information security management systems—Requirements*. ISO.

International Organization for Standardization. (2023). *ISO/IEC 42001:2023 information technology—Artificial intelligence—Management system*. ISO.

National Institute of Standards and Technology. (2023). *Artificial intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1). U.S. Department of Commerce. https://doi.org/10.6028/NIST.AI.100-1

World Wide Web Consortium. (2023). *Web Content Accessibility Guidelines (WCAG) 2.2*. https://www.w3.org/TR/WCAG22/

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W.-t., Rocktäschel, T., Riedel, S., & Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *Advances in Neural Information Processing Systems, 33*, 9459–9474.

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H., Tymchenko, I., Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., & Clanuwat, T. (2026). *Sakana Fugu technical report* [Technical report]. arXiv. https://doi.org/10.48550/arXiv.2606.21228

Zhang, S., Yu, Y., Li, Y., Zhao, W., Yang, Y., Zhang, Y., & Liu, T. (2025). *Conductor: Learning to route multi-agent workflows* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026). *TRINITY: An evolved LLM coordinator* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04695

Higgins, S. S., Crepalde, N., & Fernandes, L. (2021). Segmented multiplexity: A research agenda for multiplexity beyond the average. *PLOS ONE, 16*(9), e0257527. https://doi.org/10.1371/journal.pone.0257527
