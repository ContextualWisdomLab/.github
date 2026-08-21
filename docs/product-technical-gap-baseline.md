# Product and Technical Gap Baseline

검토 기준일: **2026-08-21 (Asia/Seoul)**
대상: **ContextualWisdomLab/.github** 중앙 거버넌스·자동화 레포지터리와 이를 소비하는 naruon 생태계
현재 보호된 `main`: `731af58e954901c4f1cc853231c592abb1eaf617`
현재 열린 PR 수: **106** (아래 표에 이 스냅샷의 전체 목록 포함)

이 문서는 제품·기술·운영 Gap을 현재 문서와 현재 GitHub 상태에 묶어 두는 기준선이다. 새 작업은 먼저 이 문서의 Gap ID를 PR 설명과 테스트 증거에 연결하고, PR의 정확한 exact HEAD·Checks·리뷰를 다시 수집한 뒤 구현한다. 표의 상태는 작성 시점의 관측값이므로, 병합 판단에는 재사용하지 않는다.

## 1. 근거와 범위

### 1.1 우선순위가 높은 근거

1. [CWL Master Context](CWL-MASTER-CONTEXT.md): naruon의 이메일 우선 플랫폼 경계, DIKW, no-ask 자동 해결, 다층·다중소속·시간·프라이버시 원칙.
2. [naruon #974](https://github.com/ContextualWisdomLab/naruon/issues/974): `docs/planning/naruon-platform-plan.md`를 추가한 병합된 제품/IA/User Story/Use Case/Architecture 기준.
3. [GitHub Project #1](https://github.com/orgs/ContextualWisdomLab/projects/1): 로드맵의 live source of truth. 이 스냅샷에서 확인한 조회 한도 내 항목은 Done 68, In Progress 3, Todo 29, 총 100개이며 P0 19, P1 2, P2 14, P3 5, P4 2, P5 31, Ops 25, Decision 2개다.
4. 중앙 ADR·doctoring·계약 문서: 보호된 main에 존재하는 [organization readiness doctoring](doctoring/organization-commercial-readiness-loop.md)와 현재 열린 [adaptive orchestration PR #1145](https://github.com/ContextualWisdomLab/.github/pull/1145), [Figma 경계 PR #1146](https://github.com/ContextualWisdomLab/.github/pull/1146), [ecosystem catalogue PR #1147](https://github.com/ContextualWisdomLab/.github/pull/1147). PR에만 있는 파일은 병합된 근거로 취급하지 않는다.

### 1.2 제품 경계

구매자가 사는 핵심 결과는 “흩어진 enterprise context를 판단 가능한 구조로 만들고, 사람이 다음 행동을 승인할 수 있게 하는 것”이다. naruon은 이메일 호스트나 전자결재 시스템이 아니라 고객 소유 데이터에 연결되는 이메일 workspace/platform이다. 중앙 `.github`은 제품 기능을 대신 소유하지 않고, 정확한 HEAD·리뷰·Checks·증거·변경권한을 보장하는 control plane이다.

핵심 구매 여정은 다음과 같다.

1. 여러 계정·언어의 이메일에서 한 사건의 thread와 sender 의미를 찾는다.
2. 변경된 일정의 최신 truth, 변경 이력, commitment status와 충돌을 계산한다.
3. work/personal/project/band 등 겹치는 norm group을 선택하고, 관계·권한·유효기간을 고려한다.
4. 다른 context에는 필요한 결과(예: unavailable)만 consent·audit 기반으로 공개한다.
5. 사람은 근거·confidence·다음 행동을 보고 예외만 수정하며, 외부 writeback은 승인한다.

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
- **AI plane:** contextual-orchestrator adaptive routing; role별 reasoning effort, workflow depth, recursion, decomposition, verifier/synthesis를 quality evidence에 따라 배분.
- **Compute plane:** 수리과학·psychometrics의 계산 레이어와 속도·안정성·보안이 핵심인 hot path는 Rust 경계를 우선 검토하며, GPU/CPU multithreading과 낮은 context switching을 benchmark로 입증한다. Python/JS는 orchestration/API adapter로 제한한다.
- **Data plane:** 모든 영속 객체는 두 단어 이상 `snake_case`를 기본으로 하고 3NF를 지키며, 관계·evidence·confidence·validity·disclosure를 별도 정규화한다.
- **UX plane:** UI 제품만 Figma/Storybook/design token을 사용한다. 중앙 `.github`는 UI 없는 인프라 레포지터리이므로 Figma File ID는 **N/A (UI scope 없음)**이며, UI PR은 별도 ADR에 실제 File ID를 기록한다.

### 2.3 UML-level dependency

```mermaid
flowchart LR
  User[Buyer / human judgment] --> Naruon[naruon email workspace]
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
| G-01 | 열린 PR은 106개이고 metadata상 mergeable인 PR도 independent exact-head approval과 terminal required Checks를 자동으로 의미하지 않는다 | 안전하게 출시할 변경과 대기 중인 변경을 구별할 수 없다 | PR마다 current head, reviews, threads, required Checks를 재수집하고 보호 조건 미충족이면 merge하지 않는다 |
| G-02 | #1162는 review credential route를 고치지만 current Checks가 queued/cancelled로 반복되며 router의 403 경로가 선행 main에 남아 있다 | 리뷰가 호출돼도 승인 증거가 생성되지 않아 자동화가 멈춘다 | #1162 current-head quality와 OpenCode/Noema/Strix를 재실행하고, 병합 뒤 router comment/dispatch의 403을 실제 PR에서 검증한다 |
| G-03 | #1153의 Strix run은 `loginAsGuest`/Caido `127.0.0.1:48080` bootstrap 실패를 provider signal로 분류하지 않았다 | 취약점 0건이더라도 CI 인프라 결함이 보안 결과처럼 보이고 큐가 막힌다 | exact runtime signature를 불완전 evidence로 fail-closed 분류하고, vulnerability marker가 있으면 절대 neutralize하지 않는 regression을 유지한다 |
| G-04 | 106개 live PR 중 많은 항목이 BEHIND 또는 CHANGES_REQUESTED이며, 자동 caller PR이 제품 기능보다 앞서 쌓였다 | 제품 개발 속도가 queue hygiene에 소모되고, stacking 순서가 불명확하다 | product/ownership boundary별로 stack을 재정렬하고, 오래된 PR은 current main으로 normal merge/rebase 후 변경 범위를 검증한다 |
| G-05 | ecosystem contract/catalog PR은 존재하지만 naruon의 실제 plugin 소비·standalone 실행·connector round-trip 증거가 제한적이다 | 구매자는 “연결 가능” 문서와 실제 설치 가능한 제품을 구별할 수 없다 | manifest/version compatibility, command/event envelope, consumer smoke, rollback/upgrade contract를 조직 유관 레포에서 증명한다 |
| G-06 | naruon #974와 Project #1은 제품 목표를 정의하지만 E1/E2/E3의 live implementation evidence가 이 중앙 레포에 없다 | 이메일 검색·일정 충돌이라는 killer workflow가 문서에만 머문다 | naruon에서 thread/sender ontology → temporal commitment/conflict → human correction slice를 독립 PR로 delivery한다 |
| G-07 | multi-level/multi-membership/temporal 관계 원칙은 master context에 있으나 모든 소비 저장소의 schema/API가 동일한 reified relationship contract를 보장하는지는 미확인이다 | 개인 단위로 집계하거나 전역 권한을 적용하는 atomistic/ecological fallacy 위험이 남는다 | relationship, membership, norm_group, validity window, evidence, confidence, disclosure를 정규화하고 cross-context golden tests를 만든다 |
| G-08 | embedding·DOM·sender/receiver 의미 단위 chunking과 base64 image의 OCR/object/tag/position-index 설계가 ecosystem contract에 부분적으로만 반영됐다 | 검색은 되지만 실제 그림 위치와 의미를 회수하지 못해 편집·문서·메일 업무가 끊긴다 | semantic unit chunk schema와 image asset/region/ocr/tag embeddings를 별도 entity로 설계하고 source offset/DOM path를 보존한다 |
| G-09 | 100% coverage/docstring은 중앙 PR별로 증거가 있으나 조직 소비 레포의 frontend interaction/i18n/design-token/real-data accuracy 증거가 동일한지 미확인이다 | “green CI”가 실제 고객 시나리오 정확성을 보장하지 않는다 | domain-specific RMSE/reproducibility/audio/visual/browser acceptance와 edge matrix를 required evidence로 만든다 |
| G-10 | math/psychometrics의 Rust+GPU/CPU path와 시간·다층·다중소속 모델은 fast-mlsirm/psychometrics-commons 등 제품 레포의 책임이다 | 계산 정확도·성능·모델 해석 가능성을 Python glue만으로 보장할 수 없다 | Rust core, GPU/CPU benchmark, temporal/multilevel/multiple-membership fixtures, RMSE/recovery/ablation을 제품 PR에 묶는다 |
| G-11 | UI가 있는 제품의 Figma/Storybook inventory와 token/interaction/i18n 테스트는 중앙 control plane에서 소유할 수 없다 | 제품 간 UI가 달라지고 buyer onboarding이 일관되지 않는다 | 각 UI repo가 실제 Figma File ID ADR, Storybook inventory, shared token package, keyboard/edge/i18n tests를 소유한다 |
| G-12 | CSAP/SOC 2 통제 목표와 PII masking 대안은 doctoring에 흩어져 있으며 evidence-to-control mapping의 live completeness가 미확인이다 | PII를 마스킹하면 업무가 멈추고, 원문 접근을 허용하면 감사·유출 위험이 커진다 | consent/purpose/access lease, field-level encryption/tokenization, redaction-at-egress, audit/revocation와 CSAP/SOC 2 evidence map을 구현한다 |
| G-13 | hourly scheduler는 존재하지만 no-op/credential unavailable/queued Checks의 customer next action을 모든 caller가 동일한 receipt로 내는지 미확인이다. Main run `32359911521`은 `PR_REVIEW_MERGE_TOKEN` 미설정 시 즉시 실패하고 receipt artifact도 만들지 못했다 | 자동화가 실패해도 운영자가 무엇을 고쳐야 하는지 알 수 없다 | #1161의 `skipped_credential_unavailable` receipt와 다음 행동 문구를 exact-head Checks로 검증한 뒤 병합하고, bounded receipt schema, retry floor, single-flight, no secret fallback을 모든 caller contract test로 고정한다 |
| G-14 | release/changelog/version 증거가 각 PR에 분산되고 현재 central repo 보호 main의 release candidate가 명확하지 않다 | 구매자는 어떤 기능이 supportable release인지 확인할 수 없다 | merge 후 release readiness ledger, CHANGELOG, semantic version/tag, rollback/operability evidence를 함께 갱신한다 |

## 4. 열린 PR live inventory

아래는 GitHub REST API가 2026-08-21 live 조회에서 반환한 106개 열린 PR의 number/title/head/base 및 merge-state metadata다. `base`는 각 PR이 당시 대상으로 삼은 실제 base branch이며, stacked PR은 `main`이 아닌 feature branch를 가질 수 있다. `BLOCKED`, `BEHIND`, `DIRTY`, `UNSTABLE`은 GitHub merge-state metadata이며 protected merge 승인이나 required Checks PASS를 뜻하지 않는다. 다음 루프에서 모든 행의 live review, thread, Checks를 다시 확인한다.

| PR | title | head SHA | base | metadata | mode |
|---|---|---|---|---|---|
| #1190 | fix(coverage): bind Rust materializer to exact base SHA | `1a330c9e6e176a1f3ab57bda67e780673cc4ec7b` | cursor/opencode-review-surfaces-1bda | UNSTABLE | draft |
| #1189 | docs: complete coordinator client docstring | `a62550510c14de5db29cad6b3b60a6c493fd2fc1` | main | BLOCKED | ready |
| #1188 | fix: grant hourly callers reusable workflow OIDC scope | `3ab34b57a7ab04eb14b5fca7994dd047df676748` | main | BLOCKED | ready |
| #1187 | fix(coverage): scope Rust evidence to changed packages | `2a5ab45719781687b6ad9931072df10a1c04d738` | main | BLOCKED | ready |
| #1179 | ⚡ Bolt: [성능 개선] 레이블 스캔 시 O(N) 서브스트링 검증 선행 | `5a4cb11219cdf7faf575aab744939ab027db44e8` | main | BLOCKED | ready |
| #1178 | chore: schedule contextual-orchestrator hourly review repair | `bdec3132d8a6febca26f1553e6c91b79d0c2bccf` | main | BLOCKED | ready |
| #1177 | fix(strix): retry exact model-quality warnings | `07fa2a69c2820d7eff348fcacc017154e85748f6` | main | BLOCKED | ready |
| #1176 | fix(governance): require central reviews for stacked PRs | `33b85a8cf48d5b6e0880d5071b360ffa46f83457` | main | DIRTY | ready |
| #1175 | 🛡️ [보안 강화] sandboxed_web_e2e.py 내 subprocess 호출 시 명시적 shell=False 추가 | `cfe66b8dfdcc5cfb37d893dbe40eaa9dd2e2860f` | main | BLOCKED | ready |
| #1174 | fix(router): preserve dispatch when acknowledgement fails | `183cb6e77fa5de56e4270ce5e702656a5da7c408` | main | BLOCKED | ready |
| #1172 | fix(autofix): resolve live NVIDIA NIM models instead of a retired pin | `1a887a7e8f28fcda3b20913060d1e4fdb20037d0` | main | BEHIND | ready |
| #1170 | feat: route OpenCode reviews through contextual gateway | `1f2b93ead7205b33712de1865d84c004d93be7ed` | main | DIRTY | ready |
| #1168 | feat: route autofix through contextual orchestrator | `01643acdc70de78077fd4db8ddc6342bdb6bb24e` | main | BLOCKED | ready |
| #1166 | fix(ci): recognize replacement tests in existing files | `65f082e34097e818e8b8b5347e525ff41f0925c2` | main | BLOCKED | ready |
| #1165 | fix(automation): yield completed mention repositories fairly | `e6838a033a91e7c1a2a22287d5f9922df5a30977` | main | BEHIND | ready |
| #1163 | docs: establish live product and technical gap baseline | `d6bfaca75592039e0521fa71d66aa72c3d631fc6` | main | BLOCKED | ready |
| #1162 | fix: use review credentials for agent dispatch | `0f765781fcf36554647579be44be1deb3ecbc0a9` | main | BLOCKED | ready |
| #1161 | fix: make hourly coordinator credential absence auditable | `1ff3169375884ee812260e4d58a88a6df592fa51` | main | BEHIND | ready |
| #1159 | fix(coverage): classify Storybook development evidence | `7fbee6f482ec745b117f0d916a8de8dbb998e9e1` | main | BEHIND | ready |
| #1158 | fix(osv): preserve immutable direct-source provenance | `a0fbba88239e5c4b4d066a43e9ea908f0a939605` | main | BLOCKED | ready |
| #1157 | fix(coverage): discover hash-pinned requirements lock files | `afe42767562feff69e488a1034c9b5631541426d` | main | BEHIND | ready |
| #1155 | Fix duplicate repository dispatch scheduler runs | `4b9a933d77a1d68459bf2c51abfbdba9e2d03d8b` | main | BEHIND | ready |
| #1154 | ⚡ Bolt: 민감한 데이터 스크러버(Redaction) 루프 O(N) 성능 최적화 | `cf89d56c01309d6ba6b9bfb1205294b28d0d4765` | main | BLOCKED | ready |
| #1153 | fix(strix): fail closed on incomplete provider scans | `144df9fbadc3b2f846134c26ac0372694d68fb59` | main | BLOCKED | ready |
| #1152 | fix(opencode): retry OpenCode after coverage blockers clear | `05e95bb6872dd1363f9e21765f088cc7e50e0cf4` | main | BLOCKED | ready |
| #1150 | feat: add read-only Actions queue health evidence | `af65a69eb7308604a4fded9707ff987fcb9d0e80` | main | DIRTY | ready |
| #1147 | feat(integration): add ecosystem capability catalogue | `390af196aac5ffea55d2d0198dffa999bd3be182` | main | BEHIND | ready |
| #1146 | fix(figma): retain style references and component sets | `f661a8e0524742048c33cb0e90b81d446dbeabd4` | main | BEHIND | ready |
| #1145 | feat: enforce adaptive orchestration defaults | `2451889cc80afa9101275e1356f8757fabc69b44` | main | DIRTY | ready |
| #1143 | ci: schedule naruon hourly review repair | `d26e0cf320d87f7c11292afb894b475d84080451` | main | DIRTY | ready |
| #1123 | feat(edge): standardize organization runtimes on Cloudflare Pingora | `58ee96cc3886164cff89e427ce927326bf8d2b03` | main | BEHIND | ready |
| #1120 | Wire Noema to a same-job contextual-orchestrator sidecar | `101e6906cc3568beb99c19c28eaffb526bac335b` | main | BEHIND | draft |
| #1114 | fix(strix): retry transient visibility API failures | `46d5cae7136262250df69977c523bfb12806ed0c` | main | BLOCKED | ready |
| #1112 | fix(storage): reject embedded IPv4 rebinding hosts | `dc7e39cf7dff80c2e2ed8d348090394ddc643142` | main | BEHIND | draft |
| #1108 | feat(automation): run free-router hourly NVIDIA NIM review repair | `de22b1a8a919a7cfe6d76ed53f580655fd00628c` | main | BLOCKED | ready |
| #1107 | chore(deps): bump github/codeql-action/init from 4.37.0 to 4.37.7 | `e87d23e21c5fcd89f3821390df4e0c2b618383da` | main | BEHIND | ready |
| #1106 | chore(deps): bump typing-inspection from 0.4.2 to 0.4.4 | `b97adac6ef7eaca5f381f079f7db1447cf882343` | main | BEHIND | ready |
| #1104 | chore(deps): bump charset-normalizer from 3.4.7 to 3.5.1 | `ecdd786316fc49fb77460126d8687d474afaa6ee` | main | BEHIND | ready |
| #1103 | chore(deps): bump google-cloud-resource-manager from 1.17.0 to 1.18.0 | `3727a4e5002700178c04928532fc586b6925d1b8` | main | BEHIND | ready |
| #1101 | feat(automation): run EmbedRelay hourly NVIDIA NIM review repair | `bebc8815fda4edb448a7e02092879f95bc725b31` | main | BLOCKED | ready |
| #1100 | feat(automation): run RankWeave hourly NVIDIA NIM review repair | `1628c2e561262fb84af658c6e857868628733dc6` | main | BEHIND | ready |
| #1097 | feat(automation): run html4tree hourly NVIDIA NIM review repair | `5b69ff2429b86b6dcd1ce722e46ad0749a82568f` | main | BLOCKED | ready |
| #1095 | feat(automation): run mhtml-etl-gateway hourly NVIDIA NIM review repair | `d79f28a9ee5b4e1a3999ddf3bd5d951df9eef105` | main | BLOCKED | ready |
| #1094 | feat(automation): run DiagramWeave hourly NVIDIA NIM review repair | `0c625856ab9fe35b24de1b74f13224269f60275d` | main | BLOCKED | ready |
| #1092 | feat(automation): run psychometrics-commons hourly NVIDIA NIM review repair | `82e2faed0960bfe018e2ad71e2968419b8d78ca9` | main | BLOCKED | ready |
| #1088 | feat(automation): run mightyETL hourly NVIDIA NIM review repair | `71241dd6031754038923d4fe043123cc61f010a9` | main | BLOCKED | ready |
| #1087 | feat(automation): run life-os hourly NVIDIA NIM review repair | `aff596a361dc19cb839bdb37acde032148cdfb43` | main | BLOCKED | ready |
| #1086 | feat(automation): repair the LineageWeave buyer-surface stack hourly | `5822f84f559abe767ae69f09a7709f968de9305d` | main | BLOCKED | ready |
| #1085 | feat(automation): run kaefa hourly NVIDIA NIM review repair | `1c5fbb66510254de7bc3adc81590382e8f261acb` | main | BEHIND | ready |
| #1084 | feat(automation): run aFIPC hourly NVIDIA NIM review repair | `4d70c4724a1b51dff6206aa1b67f6c44b9a3f263` | main | BLOCKED | ready |
| #1083 | feat(automation): run pg-llm-batch hourly NVIDIA NIM review repair | `584141341346b7882fded053b459a7d4c16477a2` | main | DIRTY | ready |
| #1082 | feat(automation): run semantic-data-portal hourly NVIDIA NIM review repair | `571bc1fc4dac2479075dec4c0812bd8fed68b520` | main | DIRTY | ready |
| #1080 | feat(automation): run newsdom-api hourly NVIDIA NIM review repair | `d666e90229c81d5e72a26c219b294a0339aaa01f` | main | BLOCKED | ready |
| #1079 | feat(automation): run Appguardrail hourly NVIDIA NIM review repair | `a130b106399a0f57c247aaf532316cc61aca14d6` | main | BLOCKED | ready |
| #1078 | feat(automation): run Scopeweave hourly NVIDIA NIM review repair | `b48509ef9dc0e0861c714998264597dc10e7c95a` | main | BEHIND | ready |
| #1077 | feat(automation): run noema hourly NVIDIA NIM review repair | `0472ca6a12322bcf57c7e9f739e4cc03a59d6791` | main | BLOCKED | ready |
| #1076 | feat(automation): run pg-erd-cloud hourly NVIDIA NIM review repair | `55a4b74ea538a48f7e55e5d97b80a5bdda1c1b70` | main | BLOCKED | ready |
| #1075 | feat(automation): run codec-carver hourly NVIDIA NIM review repair | `471f9888616fabfa6ca3f1642d38e260786aaaf6` | main | BEHIND | ready |
| #1074 | feat(automation): run Keyverse hourly NVIDIA NIM review repair | `298b6b8eef50ab4f096b9e5778403fad2f908e20` | main | BEHIND | ready |
| #1070 | feat(automation): run Wardnet hourly NVIDIA NIM review repair | `5f899a472001f3cdaa22b20ada8d84d2cf314a00` | main | DIRTY | ready |
| #1065 | fix(scheduler): fall back to REST when auto-rebase GraphQL transport fails | `44e098154f37108508b573cb5f7dfeff3fd246a3` | main | BEHIND | ready |
| #1062 | fix(strix): map official modes without branch-selected dispatch | `74079e5bddd69bf7eac6d3b2492f25d598517905` | main | BEHIND | draft |
| #1061 | fix(scheduler): ignore manual Strix dispatch as merge evidence | `31576af6b96879a6168d3af2c3953834bb67f853` | main | BEHIND | draft |
| #1060 | fix(opencode): prove asyncio coverage plugin without colliding #896 | `cda448b7ad74171d0da374d0a17e485dbebbad68` | main | DIRTY | draft |
| #1058 | fix(operability): reject impossible control-plane SLI counts | `cdc4beef4ac31239459823a4431962312fe95771` | main | BEHIND | draft |
| #1057 | fix(coverage): restore trusted LLVM 19 producer pin | `e94811020ac28af78e8c675c2d4aed959cf899ed` | main | BLOCKED | ready |
| #1053 | fix(redaction): skip gh run view job/step prefixes | `8d948aba2ed80fc74b47b94516aaae224d438e3a` | main | BEHIND | draft |
| #1052 | fix(opencode): split review surfaces, give NIM two hours, and remove GitHub Models | `fe83dc0c2fe472d068477bb6a17c0820dee82aaa` | main | BEHIND | ready |
| #1051 | fix(pip-audit): keep index-url locks hashed and reject symlink parents | `e27bb1227a58e70c35a49f58e43c85940569035c` | main | BLOCKED | ready |
| #1050 | fix(security): reject dot path components before dependency-review compare | `b327d3a1b39c9b0ed67b7d3c0ebf2c7b02e1e465` | main | BEHIND | draft |
| #1046 | fix(opencode): pass trusted visibility into the private free-model hook | `8e36fe99ec995fef8c9798a72a8acd417ba68cd4` | main | DIRTY | draft |
| #1036 | fix(ci): bind stub-scan evidence and cap hourly fleet work at 12 | `d8205b139f8396c0452ecd4cc9b95caa45a56f42` | main | BEHIND | draft |
| #1035 | docs(automation): retarget closed-unmerged #840 and #906 lineage | `9f450d68b93c70079bf40fc8e9b46a5c96173f88` | main | BEHIND | draft |
| #1027 | fix(automation): stop mention sweep on already-exceeded rate limits | `2cd701fdb4a59cd4ebc28107bce5c3c13e1889e9` | main | BEHIND | draft |
| #1026 | feat(actions): inventory orphaned workflow identities | `8d141d51d5b891fda7e8638164f64d5f6fed5ea8` | main | BLOCKED | ready |
| #1024 | docs(ai): standardize adaptive contextual-orchestrator consumers | `a8e7e13592a4e98c4ecd70731afe878780032f07` | main | BEHIND | ready |
| #1015 | fix(coverage): defer interpreter-specific wheel gaps | `1fe4e8887caab2213df91e15630fe3c48d6c0556` | main | BEHIND | ready |
| #1009 | fix(strix): bind evidence to exact workflow artifacts | `99fee8b1b4ff4fc2219b98561cc4fea851c2f03a` | main | BEHIND | ready |
| #1002 | fix(review): fail closed when required check is not a verdict | `f36ec96bec8433837009547473d2a8f0764d7cc6` | main | BLOCKED | ready |
| #991 | fix(automation): reuse review node_id for mention eyes | `8f0d57815c380c24f6c277c74e9172f2ea7d4324` | main | BEHIND | draft |
| #949 | fix(opencode-review): discover multi-line run: blocks in safe_pytest_command | `437f21eefb6ee14346e74a7e2bb8f327719c6e91` | main | BLOCKED | ready |
| #946 | fix(review): publish substantive OpenCode LLM evidence | `208061726199dc7e00a271eec766e0cdf6af0934` | main | BLOCKED | ready |
| #941 | fix(semgrep): make the pinned image digest authoritative | `4c1654e78095acbb70aa4469179346b5d537d8d3` | main | BLOCKED | ready |
| #939 | fix: keep cross-repo OpenCode evidence healthy | `0912b865ee553f8af0345d58dddcb282f7765cf7` | main | BLOCKED | ready |
| #935 | fix(strix): gate dependency manifest updates | `374ffb75fa74cd95dc70d6b3c6998d548dc52e0b` | main | BEHIND | ready |
| #933 | fix: retry Strix provider tool protocol failures | `d1c86904ba4f4adf99a44a3ebec9c02e123ac986` | main | BEHIND | ready |
| #932 | fix(sbom): preserve Markdown report integrity | `68c03c086373480ffbb96a6d0fa0d8bed2dde75e` | main | BLOCKED | ready |
| #931 | fix(security): contain sandbox paths and output | `ccb079ed0a0107e1d301261e5005866a27d3d605` | main | BLOCKED | ready |
| #930 | fix(noema): fail closed on unsafe model endpoints | `3d7ae8c37079a6692721dfd49b535f1fbf4216bd` | main | BEHIND | ready |
| #928 | fix(opencode): bind coverage artifacts to workflow attempts | `33934d0ef2b98ba2e6d9abf6887e22c21680519a` | main | DIRTY | ready |
| #921 | chore(deps): bump google/osv-scanner-action/osv-scanner-action from a82132c0bd6c7261ffcb78e754c46c70ab57ad9a to f4cfcc01edc9c8b756a9b873b7a623ca674da51e | `60c708cc084d738ced9747792b3243e926663304` | main | DIRTY | draft |
| #920 | chore(deps): bump ossf/scorecard-action from 2.4.3 to 2.4.4 | `b9a0cc349d022c894548eb4ca7d94ebe0da99ae8` | main | DIRTY | ready |
| #918 | chore(security): align all CodeQL actions to v4.37.6 | `e94ce637242a391520e2a52e0f5a9592fc64f58e` | main | DIRTY | ready |
| #904 | fix(opencode): include adversarial gate in fallback scope | `8398eec607b006eb576b00e9a19cca840b37c4af` | main | BEHIND | ready |
| #901 | security(deploy-pages): declare minimal secret contract | `e1c99776a1c1c04b6b941799912b0e5c39dd8a0e` | main | DIRTY | ready |
| #899 | fix(scheduler): fail after summarized action errors | `56ffdd1cc1bc235a39b0373a58430fb8c7b00afb` | main | DIRTY | ready |
| #897 | fix(security): fail closed on unavailable dependency review | `d6bb46932d697e8820b9abfabbad03b53a23217d` | main | BLOCKED | ready |
| #834 | fix(noema): replay OIDC envelope repair on current main | `7b64d26c157df3b0da13d8ed0e1cd8365ae47d1e` | main | DIRTY | ready |
| #831 | feat(opencode): add head-matched gold corpus tooling | `3be33ebd22a403188802cc2d63d3726a33e2d137` | main | BLOCKED | ready |
| #828 | fix(scheduler): require independent exact-head approval | `ba270684dc1431af94dc44f48816ab1c44437369` | main | DIRTY | ready |
| #821 | fix(ci): replace conflicted fatal OpenCode process-group prerequisite | `5f250b0966d21a893ebcae223a5531562cb09062` | main | DIRTY | ready |
| #807 | fix(coverage): validate nested npm metadata through canonical pins | `cf4abba7086273743ce12e8c15a78e9623509fe6` | main | DIRTY | ready |
| #796 | feat(automation): run Inkspan hourly NVIDIA NIM review repair | `fa7c32c6fc2de53c8739a03be32cd19c62a02ac9` | main | DIRTY | ready |
| #790 | fix(coverage): retry transient trusted uv downloads | `afad81361377f1fe2e651018f1008a590f5344a5` | main | DIRTY | draft |
| #789 | feat(coverage): add bounded PyO3 peer-evidence gate | `6146bb991ed041985233eefa33985b2e40a00721` | main | DIRTY | draft |
| #785 | fix(coverage): materialize requirements-directory locks | `efd2ae85538bdb389da99f0fed6d1799ead5b343` | main | DIRTY | draft |

#1191은 같은 시각에 closed/unmerged로 확인되었고, #1192의 base SHA는 닫힌 PR의 head d9479cf486f731e8efe582e7b029234e05b36cae를 사용한다. 이는 stacked descendant의 live metadata이지 parent가 main에 들어갔다는 뜻이 아니다.
## 5. 실행 루프와 고객의 다음 행동

각 hourly pass는 아래 순서를 유지한다.

1. 조직·repo 책임 경계를 확인하고, current default branch SHA와 PR head SHA를 새로 읽는다.
2. 열린 PR 하나를 선택해 review threads, formal review commit SHA, required Checks와 failure logs를 확인한다.
3. 실패가 코드 결함이면 root cause를 해당 PR의 최소 범위에서 수정하고, 원격 agent의 concurrent commit은 normal forward history로 보존한다.
4. 현실적인 domain test, edge test, docstring/branch coverage, security/SBOM, actionlint/browser evidence를 실행한다.
5. 새 head에서 Checks를 재실행하고 independent current-head approval을 다시 요청한다.
6. protected ruleset의 approval·resolved thread·terminal Checks·exact head를 모두 충족할 때만 normal merge한다. 조건이 안 되면 merge하지 않고 다음 PR로 진행한다.
7. PR이 소진되면 Project #1과 소비 repo에서 가장 큰 buyer gap을 선택해 새 PR을 만들고, 이 문서의 Gap ID를 연결한다.

운영자는 receipt의 `next_action`만 실행하면 된다. 예를 들어 `PR_REVIEW_MERGE_TOKEN` 부재는 토큰 값을 로그에 남기지 말고 secret을 provision한 후 다음 hourly pass를 기다리며, Strix Caido bootstrap failure는 runner/container readiness를 복구한 후 같은 exact head를 재검증한다.

## 6. Compliance and data boundary

- PII 원문을 무조건 masking하여 업무를 끊지 않는다. 대신 purpose-bound access lease, field-level encryption/tokenization, consented minimal-disclosure consequence, audited access, revocation, retention/deletion을 사용한다. `COPILOT_GITHUB_TOKEN`은 사용하지 않는다.
- 모델·리뷰·sandbox·Checks·merge·release는 서로 다른 authority다. 하나의 PASS를 approval이나 release로 승격하지 않는다.
- 모든 untrusted input, repository patch, image/base64 payload, model output은 data로 취급하고 command/credential로 해석하지 않는다.
- demo/synthetic fixture는 unit test에만 두며 production seed/fixture에는 포함하지 않는다.

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
