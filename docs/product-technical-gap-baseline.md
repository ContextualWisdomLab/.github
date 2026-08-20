# Product and Technical Gap Baseline

검토 기준일: **2026-08-20 (Asia/Seoul)**  
대상: **ContextualWisdomLab/.github** 중앙 거버넌스·자동화 레포지터리와 이를 소비하는 naruon 생태계  
현재 보호된 `main`: `6479989bbff475404cc2cccc468d5fb1d6c632e5`
현재 열린 PR 수: **100** (아래 표에 이 스냅샷의 전체 목록 포함)

이 문서는 제품·기술·운영 Gap을 현재 문서와 현재 GitHub 상태에 묶어 두는 기준선이다. 새 작업은 먼저 이 문서의 Gap ID를 PR 설명과 테스트 증거에 연결하고, PR의 정확한 HEAD·Checks·리뷰를 다시 수집한 뒤 구현한다. 표의 상태는 작성 시점의 관측값이므로, 병합 판단에는 재사용하지 않는다.

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
| G-01 | 열린 PR 99개 중 현재 main 기준 PR과 behind/dirty PR이 섞여 있고, 대부분 formal current-head approval이 없다 | “merge-ready”라고 믿은 변경이 실제 보호 규칙을 통과했는지 판단할 수 없다 | exact-head queue를 PR 단위로 재수집하고, stale approval/check를 폐기하며, 독립 approval + terminal required Checks 없이는 merge하지 않는다 |
| G-02 | #1162는 review credential route를 고치지만 current Checks가 queued/cancelled로 반복되며 router의 403 경로가 선행 main에 남아 있다 | 리뷰가 호출돼도 승인 증거가 생성되지 않아 자동화가 멈춘다 | #1162 current-head quality와 OpenCode/Noema/Strix를 재실행하고, 병합 뒤 router comment/dispatch의 403을 실제 PR에서 검증한다 |
| G-03 | #1153의 Strix run은 `loginAsGuest`/Caido `127.0.0.1:48080` bootstrap 실패를 provider signal로 분류하지 않았다 | 취약점 0건이더라도 CI 인프라 결함이 보안 결과처럼 보이고 큐가 막힌다 | exact runtime signature를 불완전 evidence로 fail-closed 분류하고, vulnerability marker가 있으면 절대 neutralize하지 않는 regression을 유지한다 |
| G-04 | 99개 live PR 중 많은 항목이 BEHIND 또는 CHANGES_REQUESTED이며, 자동 caller PR이 제품 기능보다 앞서 쌓였다 | 제품 개발 속도가 queue hygiene에 소모되고, stacking 순서가 불명확하다 | product/ownership boundary별로 stack을 재정렬하고, 오래된 PR은 current main으로 normal merge/rebase 후 변경 범위를 검증한다 |
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

## 4. 현재 PR inventory (live snapshot)

다음 표는 기준선 PR의 live update 직전 `gh pr list --state open --limit 100`으로 얻은 값이다. 기준선 자체인 #1163과 이후 이 루프에서 새로 검증한 head는 별도 행으로 갱신했다. merge 판단에는 사용하지 말고, 각 루프에서 `gh pr view <number>`로 다시 확인한다.

| PR | title | head SHA | base | merge state | review decision |
|---|---|---|---|---|---|
| #1169 | fix(security): keep baseline-only Strix outages non-blocking | `24893cee8fbb33791fe77629efa35ce2d8fb7076` | main | BLOCKED | — |
| #1168 | feat: route autofix through contextual orchestrator | `e30ce15fd2e53c43b24c6a782a306e82209d2b0d` | main | BLOCKED | — |
| #1167 | feat: add Orgmetra hourly review repair caller | `17ad155cad325cd159cb88a661e356ddcc5372cc` | develop | BLOCKED | — |
| #1166 | fix(ci): recognize replacement tests in existing files | `634303023cea09e8496b8abd10ec47d5ca76f732` | main | BLOCKED | — |
| #1165 | fix(automation): yield completed mention repositories fairly | `941e4bdf7e11157c3f9b596bd6648e7491501054` | main | BLOCKED | — |
| #1162 | fix: use review credentials for agent dispatch | `fad1ed4de66e090d31881348a7c3c3f6518aa177` | main | BLOCKED | — |
| #1163 | docs: establish live product and technical gap baseline | `e0c96d567a0ecf67340b64f6fdccb7567a4f9769` | main | BLOCKED | — |
| #1161 | fix: make hourly coordinator credential absence auditable | `dbc3eca51444e46ce7a3a07ea818c72ad8bf124a` | main | BLOCKED | — |
| #1159 | fix(coverage): classify Storybook development evidence | `5775073735360250ba5ef7bfaaf30b8f50d6dc1d` | main | BLOCKED | — |
| #1158 | fix(osv): preserve immutable direct-source provenance | `d1da60569c079f59b211a2495cbe0fdb6a7a1d02` | main | BLOCKED | — |
| #1157 | fix(coverage): discover hash-pinned requirements lock files | `107c572ab1ea077333c1199e98c734957a305ff6` | main | BLOCKED | — |
| #1156 | 🛡️ Sentinel: [MEDIUM] sandboxed_web_e2e.py의 subprocess 호출에 shell=False 명시 | `d4948f21818a351db22292a686b361581f33b6ed` | main | BLOCKED | — |
| #1155 | Fix duplicate repository dispatch scheduler runs | `5ef1fc6bb4aa7b2abc8e393f4a1abc45b4425e33` | main | BLOCKED | — |
| #1154 | ⚡ Bolt: 민감한 데이터 스크러버(Redaction) 루프 O(N) 성능 최적화 | `ded4d1ae4f8578f0c4eaad090be97dadc4ae4697` | main | BLOCKED | — |
| #1153 | fix(strix): fail closed on incomplete provider scans | `e21951d73fbe05a3b9dda871b18c7480f1fe3e41` | main | BLOCKED | — |
| #1152 | fix(opencode): retry OpenCode after coverage blockers clear | `a37fecbe96c01f5d3638085876371313713823c4` | main | BLOCKED | — |
| #1150 | feat: add read-only Actions queue health evidence | `3196c2db08f84235aaf58bf612806e75d2b33023` | main | BLOCKED | — |
| #1147 | feat(integration): add ecosystem capability catalogue | `9ac03e0c1f9f2e12f0d29d354f5e9541a1feffbb` | main | BLOCKED | — |
| #1146 | fix(figma): retain style references and component sets | `54cb0220ca95603831dc8defeedd766d47cf4a62` | main | BLOCKED | — |
| #1145 | feat: enforce adaptive orchestration defaults | `f96c80b70d024bdaad13efd3a728caa4c1ce12bf` | main | BLOCKED | — |
| #1143 | ci: schedule naruon hourly review repair | `3a7a7039741069d16204d40633d3a1cd754e376b` | main | BLOCKED | — |
| #1123 | feat(edge): standardize organization runtimes on Cloudflare Pingora | `6915bb9395bbe653f41db944c40186e7c3f8c153` | main | BLOCKED | — |
| #1120 | Wire Noema to a same-job contextual-orchestrator sidecar | `0c700f6f931986d58bd0005ea2d248ca2e459d77` | main | BLOCKED | — |
| #1114 | fix(strix): retry transient visibility API failures | `61a82288fddd714a80abb201839631897490f7a9` | main | BLOCKED | CHANGES_REQUESTED |
| #1112 | fix(storage): reject embedded IPv4 rebinding hosts | `ed42fda7fc712f09930c8c4c0398aa261291c960` | main | BLOCKED | — |
| #1108 | feat(automation): run free-router hourly NVIDIA NIM review repair | `4e233c48ecfadf3d3af9ec30f9158da5052102b6` | main | BLOCKED | — |
| #1107 | chore(deps): bump github/codeql-action/init from 4.37.0 to 4.37.7 | `705b854214d4624c3276c62f92a105278ebec199` | main | BLOCKED | CHANGES_REQUESTED |
| #1106 | chore(deps): bump typing-inspection from 0.4.2 to 0.4.4 | `ed7c4b2314f7acb3c1821fdd476e6078cbaad9fb` | main | BEHIND | CHANGES_REQUESTED |
| #1105 | chore(deps): bump openai from 2.54.0 to 3.1.0 | `4f6e3f63e72111c29329b9bc0a767127a1315e9d` | main | BEHIND | — |
| #1104 | chore(deps): bump charset-normalizer from 3.4.7 to 3.5.1 | `97ffca37a169e41c15da8976fcb3484a3ee526ff` | main | BEHIND | — |
| #1103 | chore(deps): bump google-cloud-resource-manager from 1.17.0 to 1.18.0 | `d76211d0038afe90b8374dfa1fa6e1dae680ced5` | main | BEHIND | — |
| #1101 | feat(automation): run EmbedRelay hourly NVIDIA NIM review repair | `430a3b63c7e081bd89ffea38755b26d982c5e755` | main | BEHIND | CHANGES_REQUESTED |
| #1100 | feat(automation): run RankWeave hourly NVIDIA NIM review repair | `6181c705e244aa39db6d14a117c037e3090e7696` | main | BEHIND | CHANGES_REQUESTED |
| #1097 | feat(automation): run html4tree hourly NVIDIA NIM review repair | `22c3e8874238ac2196657823860e7673d0f8676e` | main | BEHIND | — |
| #1095 | feat(automation): run mhtml-etl-gateway hourly NVIDIA NIM review repair | `0a1aa80e994b73ed50a2c0242aac1b3abf37a3af` | main | BEHIND | CHANGES_REQUESTED |
| #1094 | feat(automation): run DiagramWeave hourly NVIDIA NIM review repair | `c2e164621755cd275c9b4aef78ff511fc6eb7ca2` | main | BEHIND | — |
| #1092 | feat(automation): run psychometrics-commons hourly NVIDIA NIM review repair | `6bb0d991098cb70a8f3e0df09a5a9424b867117f` | main | BEHIND | CHANGES_REQUESTED |
| #1089 | fix(opencode): system llvm for cargo-llvm-cov (v3 concurrency) | `cd7d72c64443572c77343f1456a52b54f956240e` | main | BEHIND | — |
| #1088 | feat(automation): run mightyETL hourly NVIDIA NIM review repair | `38e9d80c908f060f738a7e890ae509a66cf7b2a5` | main | BEHIND | — |
| #1087 | feat(automation): run life-os hourly NVIDIA NIM review repair | `cdb5d773c93628a6f22450fc9dafbc0d7495e40c` | main | BEHIND | — |
| #1086 | feat(automation): repair the LineageWeave buyer-surface stack hourly | `1759b47ecb8f0bde886e90e1cb9b734c305cefc8` | main | BLOCKED | — |
| #1085 | feat(automation): run kaefa hourly NVIDIA NIM review repair | `49596268d4a2ebf9979c893ad883f9ae47472d17` | main | BEHIND | CHANGES_REQUESTED |
| #1084 | feat(automation): run aFIPC hourly NVIDIA NIM review repair | `9448d1d79abc00c80736b3bd0f69e928e331ca19` | main | BEHIND | — |
| #1083 | feat(automation): run pg-llm-batch hourly NVIDIA NIM review repair | `ce713d98ec556abf29cde32100268642160344a2` | main | BEHIND | CHANGES_REQUESTED |
| #1082 | feat(automation): run semantic-data-portal hourly NVIDIA NIM review repair | `ddc024ffa5b5af0f2ed8d5d5a84b615093abcbad` | main | BEHIND | CHANGES_REQUESTED |
| #1080 | feat(automation): run newsdom-api hourly NVIDIA NIM review repair | `6f3e279cd47c5c4e694ef94ea5d86c613a7ee2d3` | main | BEHIND | CHANGES_REQUESTED |
| #1079 | feat(automation): run Appguardrail hourly NVIDIA NIM review repair | `6dfe18379c325ce866b223b43e7a7a3729a57025` | main | BEHIND | — |
| #1078 | feat(automation): run Scopeweave hourly NVIDIA NIM review repair | `d078d62f03dba8f4caaa6971096c053ac2b317d4` | main | BEHIND | — |
| #1077 | feat(automation): run noema hourly NVIDIA NIM review repair | `3fe974dbedd91d118ec446aa3927386d33f2dba0` | main | BEHIND | CHANGES_REQUESTED |
| #1076 | feat(automation): run pg-erd-cloud hourly NVIDIA NIM review repair | `3eb45141bd4792bec83d8a719c233c47aa814d9d` | main | BEHIND | CHANGES_REQUESTED |
| #1075 | feat(automation): run codec-carver hourly NVIDIA NIM review repair | `65113968dd0c703e8e879b08bdfb533b6b6dc79f` | main | BEHIND | CHANGES_REQUESTED |
| #1074 | feat(automation): run Keyverse hourly NVIDIA NIM review repair | `4e880101d8a78c11fcd4555bf21bd0e53bebca4f` | main | BEHIND | CHANGES_REQUESTED |
| #1070 | feat(automation): run Wardnet hourly NVIDIA NIM review repair | `b1cbe69d60a22f33fa3aaff82c4cd7efccf888ce` | main | BLOCKED | CHANGES_REQUESTED |
| #1068 | feat(automation): run contextual-orchestrator hourly NVIDIA NIM review repair | `e1307c37d177b1efa297bdd6871d958ba03d9731` | main | BEHIND | — |
| #1065 | fix(scheduler): fall back to REST when auto-rebase GraphQL transport fails | `d080c09161c92ffad7b9cf630ab774b6262eeba6` | main | BEHIND | — |
| #1062 | fix(strix): map official modes without branch-selected dispatch | `74079e5bddd69bf7eac6d3b2492f25d598517905` | main | BEHIND | — |
| #1061 | fix(scheduler): ignore manual Strix dispatch as merge evidence | `3865b1fccb3d5325b35f3bcf837613cb9ee6a1fd` | main | DIRTY | — |
| #1060 | fix(opencode): prove asyncio coverage plugin without colliding #896 | `8edf65f1021c885c446da3aad2d892f3b248c603` | main | BEHIND | — |
| #1058 | fix(operability): reject impossible control-plane SLI counts | `c2240af1e6e1d701c3a795ae60f0d89bc0ee738c` | main | BEHIND | — |
| #1057 | fix(coverage): restore trusted LLVM 19 producer pin | `d51496ddb0f33de836e6b1ecb1b8339d8cca5cd5` | main | BLOCKED | — |
| #1053 | fix(redaction): skip gh run view job/step prefixes | `cd4b30e560e651f3d2d3c4e418d8f51ee650f9a2` | main | BEHIND | — |
| #1052 | fix(opencode): split review surfaces, give NIM two hours, and remove GitHub Models | `030af95f78e2910191d5e7f53a771e26f87f4dee` | main | BEHIND | CHANGES_REQUESTED |
| #1051 | fix(pip-audit): keep index-url locks hashed and reject symlink parents | `4deb1376d3bb661e9d9934511f46bbf52d9b5b1c` | main | BEHIND | CHANGES_REQUESTED |
| #1050 | fix(security): reject dot path components before dependency-review compare | `948de32e869e1656e7ae1ba770b16c0b652f4c29` | main | BEHIND | — |
| #1046 | fix(opencode): pass trusted visibility into the private free-model hook | `b78f361780bbddfb54d63f78ffa13a56c8f76ab0` | main | BEHIND | — |
| #1036 | fix(ci): bind stub-scan evidence and cap hourly fleet work at 12 | `1ac4d90af45f3106afd92fc81a0ec43cb43881bd` | main | BEHIND | — |
| #1035 | docs(automation): retarget closed-unmerged #840 and #906 lineage | `271fc60592b9eb02cf81ff5281f9c2d0b36b9067` | main | DIRTY | — |
| #1027 | fix(automation): stop mention sweep on already-exceeded rate limits | `2cd701fdb4a59cd4ebc28107bce5c3c13e1889e9` | main | BEHIND | — |
| #1026 | feat(actions): inventory orphaned workflow identities | `1e84d65f38b2112c56d9ce7828a041ad3c198b07` | main | BLOCKED | — |
| #1024 | docs(ai): standardize adaptive contextual-orchestrator consumers | `4fbe9961e92748e88bf129d435ed69682fb49a34` | main | BLOCKED | — |
| #1015 | fix(coverage): defer interpreter-specific wheel gaps | `53f05d3d6f55ab1eeba730851439fd1d31db8e41` | main | BLOCKED | — |
| #1009 | fix(strix): bind evidence to exact workflow artifacts | `805f4d32463aeef1b7557eb416fc5eb809874368` | main | BLOCKED | CHANGES_REQUESTED |
| #1002 | fix(review): fail closed when required check is not a verdict | `5fe83ff0d3c8d6c8d645190076aad0271f75b78d` | main | BEHIND | — |
| #991 | fix(automation): reuse review node_id for mention eyes | `ac496b0cf993f0bd7a058cb297566c6da63d77d3` | main | BEHIND | — |
| #949 | fix(opencode-review): discover multi-line run: blocks in safe_pytest_command | `de073535569b7e4904cac699df9f159ee8f93dd7` | main | BLOCKED | CHANGES_REQUESTED |
| #946 | fix(review): publish substantive OpenCode LLM evidence | `efc069b56abf142312aa4f3bb7b5b98e3698b9c9` | main | BLOCKED | CHANGES_REQUESTED |
| #941 | fix(semgrep): make the pinned image digest authoritative | `84b2b924547502db72856c657a171814e64142fb` | main | BLOCKED | — |
| #939 | fix: keep cross-repo OpenCode evidence healthy | `663b53d025424b32625d7a935fbbbe09d33b78c5` | main | BEHIND | CHANGES_REQUESTED |
| #935 | fix(strix): gate dependency manifest updates | `5392334fed731e3652b7bc9362fe8fa3c8332876` | main | BLOCKED | CHANGES_REQUESTED |
| #933 | fix: retry Strix provider tool protocol failures | `c95197bab04c940a1e9ddfd621b044689df88c50` | main | BLOCKED | CHANGES_REQUESTED |
| #932 | fix(sbom): preserve Markdown report integrity | `509690b9edac82b4ca1e2f6689526796a4f50838` | main | BLOCKED | — |
| #931 | fix(security): contain sandbox paths and output | `c2f28e0a85f03b38739eac7cc827e280a4db1dab` | main | BLOCKED | — |
| #930 | fix(noema): fail closed on unsafe model endpoints | `43940c128bbe00b721cf8589039df04d15769576` | main | BLOCKED | CHANGES_REQUESTED |
| #928 | fix(opencode): bind coverage artifacts to workflow attempts | `9315e4ae87074549f0147627fa3ff55f673091ae` | main | BLOCKED | — |
| #921 | chore(deps): bump google/osv-scanner-action/osv-scanner-action from a82132c0bd6c7261ffcb78e754c46c70ab57ad9a to f4cfcc01edc9c8b756a9b873b7a623ca674da51e | `60c708cc084d738ced9747792b3243e926663304` | main | BLOCKED | — |
| #920 | chore(deps): bump ossf/scorecard-action from 2.4.3 to 2.4.4 | `ed08a94ba3eaeb217b2b0e3cc4745483b18a162d` | main | BLOCKED | — |
| #919 | chore(deps): bump step-security/harden-runner from 2.20.0 to 2.20.1 | `1c5a38eaa193dd3482b729ec7e9cd1a61bbe6e5f` | main | BLOCKED | — |
| #918 | chore(security): align all CodeQL actions to v4.37.6 | `c143b495c94159125961a65ec484fa2c6918d360` | main | BLOCKED | — |
| #904 | fix(opencode): include adversarial gate in fallback scope | `40565c9299d64c256caa63df1d9febff2092e516` | main | BLOCKED | CHANGES_REQUESTED |
| #901 | security(deploy-pages): declare minimal secret contract | `b0379e5961db85b92eee2263d2f8db1b59f05c2f` | main | BLOCKED | — |
| #899 | fix(scheduler): fail after summarized action errors | `41e2e6bd236cdba988cb2cae23b4cb5b66783951` | main | BLOCKED | CHANGES_REQUESTED |
| #897 | fix(security): fail closed on unavailable dependency review | `d52b13075f614ee0da8f61571f2c8ed02430ff34` | main | BLOCKED | CHANGES_REQUESTED |
| #896 | docs: establish authoritative automation control-plane specifications | `784bc9ff36b12b3d476d9caf5daaea415a58c847` | main | DIRTY | CHANGES_REQUESTED |
| #882 | feat: eradicate production-only demo stubs across the organization | `4e9dc54762845fc7742a375bbe0e9197a4d40b14` | main | BLOCKED | CHANGES_REQUESTED |
| #834 | fix(noema): replay OIDC envelope repair on current main | `93d3102ea1b96f2aae3ac1f0e6c5d83c664ce7c1` | main | BLOCKED | CHANGES_REQUESTED |
| #831 | feat(opencode): add head-matched gold corpus tooling | `16f9ec8b49b7bae8c51f4fb27e373f53eb94bb05` | main | BLOCKED | CHANGES_REQUESTED |
| #828 | fix(scheduler): require independent exact-head approval | `7e15d2ffc288ba447d95c4e43f776be03d06dd22` | main | BLOCKED | CHANGES_REQUESTED |
| #821 | fix(ci): replace conflicted fatal OpenCode process-group prerequisite | `5a099cd7a4ce8bb5724401da901a63236980c284` | main | BLOCKED | — |
| #807 | fix(coverage): validate nested npm metadata through canonical pins | `362479dfa8f675dec59cf86d220736c651e3d83e` | main | BLOCKED | CHANGES_REQUESTED |
| #797 | release: attest exact sealed SBOM evidence | `bbf5519bd676e666869d5292b744245255345e8f` | main | BLOCKED | — |
| #796 | feat(automation): run Inkspan hourly NVIDIA NIM review repair | `8c0e6b3823b3e595a08512616e3bcc10dd8e328d` | main | BLOCKED | CHANGES_REQUESTED |
| #790 | fix(coverage): retry transient trusted uv downloads | `afad81361377f1fe2e651018f1008a590f5344a5` | main | BEHIND | — |
| #789 | feat(coverage): add bounded PyO3 peer-evidence gate | `6146bb99f7e4ffc2ce6ddc9d5d7f2b934ad26f2f` | main | BEHIND | CHANGES_REQUESTED |
| #785 | fix(coverage): materialize requirements-directory locks | `efd2ae85538bdb389da99f0fed6d1799ead5b343` | main | BEHIND | — |

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
