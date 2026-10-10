# Goal — K-CSAP 중앙 self-hosted 실행과 조건부 병합

갱신: 2026-10-10 23:04 KST. 이 worktree의 단일 작성자는 goosefish 부모다.

## 완료 결과

중앙 `ContextualWisdomLab/.github` PR #2615를 검증과 독립 App 승인 후 일반 병합으로 `main`에 전달한다. 제품 `k-csap-skills`에는 검증된 중앙 commit을 호출하는 얇은 caller만 남긴다. 실제 self-hosted job과 개인 LiteLLM `auto` 리뷰를 실행하고, 작성자와 다른 Noema/OpenCode App의 현재 head 승인을 확인한다.

사용자는 commit/push/조건부 merge와 Startup failure 경로의 중앙 self-hosted 전환을 승인했다. 전환 불가 hosted 절차의 비활성화도 승인했다. 이는 검증·개인정보·키 관리·보호 규칙 완화나 미실행 증거의 통과 승격 승인이 아니다. 별도의 인간 개발자를 전제로 하지 않는다.

## 현재 직접 확인

- PR #2615 head: `aacc387349c62b54ed96a9bd96b17c022296897b`; OPEN/Draft/BLOCKED, formal review 0.
- 중앙 protected base: `7554587c2e3106a388998bcad048a3d7121de25e`.
- 공유 #2565 head: `ef0c9d4c668fac7f01609b8fbd61a4126b103f5c`, 아직 protected main에 전달되지 않았다.
- callee workflow SHA-256: `2b14845ebf761652ca78ecdaac86c6e851ea41dc573312f41ade2695b0a719b7`.
- test SHA-256: `36bbf733ea0bec7e0cd3b03cb07d6c466cf19fffb578f16114e820a9d69c3737`.
- fresh source review `dbc0d58d24a098c68f33268fcd8dc1a6de00f57bfe729aa0dd0272fd4e29ff62`: 조건부 소스 수용. actual admission 35개와 SHA 소비자 4개 통과, frozen test 28개 통과. 실행 도구 대체는 합성 fixture이며 제품 runtime 실행이 아니다.
- setup-uv review `2159eec4f6343b82250124b78af57ed8925deaa8a63dc007a6f7e15a9670da83`: 실제 pinned dist macOS arm64/Node24 설치·checksum 거부·post cleanup 확인. Linux X64/Node20 및 Python runtime 무결성은 미검증이다.
- 제품 repo runner id 2 `k-csap-isolated-linux`는 online/idle이며 labels `[self-hosted, Linux, X64, k-csap-isolated]`다. online/label은 격리·실행 증거가 아니다. Group 13은 사용하지 않는다.
- 제품은 비공개다. 원문·추출본·private 증적·키를 공개 중앙 저장소로 전송하지 않는다.

## 소유권과 기존 경로

| 영역 | 단일 담당 | 이 Goal의 경계 |
|---|---|---|
| PR #2615 producer, 전용 tests/hash lock, 이 Goal, doctoring 문서 | goosefish 부모 | exact reviewed bytes만 수정·출판 |
| 제품 thin caller와 runner 활성화 | oscar 및 기존 운영 담당 | 승인된 새 caller/격리 packet을 받아 연결; 경쟁 편집·runner 이동 금지 |
| acceptance 조정 | salmon, 독립 admission oracle | actual packet을 확인하며 보고를 승인으로 승격하지 않음 |
| shared routing/Noema/OpenCode/canonical actionlint | #2565/Remora 담당 | accepted exact-hunk 인계 전 shared 파일 편집 금지 |
| 서비스 키·relay·effective auto route | 기존 #2560 담당 | Secret 값 읽기·중복 발급·덮어쓰기 금지 |
| 제품 dynamic Code Quality 설정 | kelp | GET not-configured 확인 완료, 이 session 제품 설정 write 0 |

## 실행 계약

- `workflow_call`만 사용하고 executable inputs/inherited secrets는 없다.
- caller 신뢰 gate를 runner 배정 전 job-level `if`에 둔다. 첫 step는 checkout 전 방어층이며 host 격리를 대신하지 않는다. skip은 quality 통과가 아니다.
- same-repo open PR과 positive-number `refs/pull/N/merge`만 허용한다. PR head와 event SHA/state는 분리한다. missing head/state fallback은 금지한다.
- PR exact head, master push/manual event SHA를 admission에서 확정한다. checkout과 HEAD 검증은 동일 `expected_sha` 출력만 소비한다. merge candidate 검증은 별도다.
- 일회용 source child와 private uv tool/cache/temp/venv, archive checksum 및 정상 종료 cleanup을 유지한다. hostile same-UID 동시 작업·잔류 프로세스·강제 종료에 대한 격리는 별도 운영 gate다.
- Python 3.11.14와 uv 0.9.7로 locked ruff/pytest/validate/diff-check를 실행한다. 로컬 contract 환경 Python 3.11.16을 workflow pin 실행으로 주장하지 않는다.
- canonical actionlint의 `k-csap-isolated` vocabulary와 전용 test lock 설치 linkage를 수락해야 한다. scratch vocabulary 통과는 canonical gate 통과가 아니다.
- 모델은 literal `auto`, endpoint는 `https://litellm.poinnetworks.net`다. `orchestrator/free` 실행은 대체 수락하지 않는다. 비용·private retention 사실을 임의 attestation으로 만들지 않는다.

## 병합 전 수락 단계

1. 실제 source bytes와 로컬 독립 review의 hash binding을 유지한다. unchanged suite 반복 대신 다음 미충족 gate로 진행한다.
2. exact-head 운영 packet에서 Linux/Node runtime, toolchain provenance, 격리·동시 작업·network·cleanup을 확인한다. approved runtime이 없으면 운영 담당과 좁게 수리한다.
3. 공유 auto route의 base chain을 default `main`까지 추적한다. feature-stack merge는 배포가 아니다. canonical lint label과 test dependency linkage도 해당 소유자와 결합한다.
4. 실제 self-hosted run/job ID와 runner_name, 실행된 source SHA 및 required step exits를 확인한다.
5. 실제 개인 gateway 인증 추론과 substantive verdict, author-distinct canonical App의 현재 head/base review를 확인한다. Draft skip/무료 요약/인프라 오류는 approval이 아니다.
6. live head/checks/required rules/unresolved findings를 fail-closed로 판정한다. 실패·skip·부재·다른 head 증거는 Ready/merge로 진행하지 않는다. 성공 후 일반 merge를 수행하고 state/mergedAt/mergeCommit/default branch를 읽어 확인한다.
7. 제품 caller를 immutable protected producer pin으로 전환하고 실제 caller-context 실행을 확인한다. hosted fallback 없이 교체한다.

## 현재 수락 상태

현재 사용자 지시에 따라 병합 작업까지 진행한다. PR #2615는 `OPEN/DRAFT/BLOCKED`, head `aacc387349c62b54ed96a9bd96b17c022296897b`, source review는 `CONDITIONAL_SOURCE_ACCEPTANCE`다. 이는 merge gate 충족이 아니다. source owner scope는 #2615의 여섯 파일이며 shared #2565, #2560, Remora, kelp 설정 파일은 소유하지 않는다.

## 다음 실제 작업

1. 이미 시작한 운영 진단 작업의 실제 호스트 관측과 실행 receipt를 대조하고, 격리·toolchain의 좁은 수리를 담당자와 실행한다.
2. 병렬 전달 경로 작업으로 #2565의 base chain과 canonical label의 다음 정상 통합 지점을 결정한다. 운영 작업과 불필요한 선행조건으로 묶지 않는다.
3. 개인 gateway `auto` 추론과 작성자와 다른 App의 현재 head review를 검증한다. shared/key 담당자의 source와 custody를 유지한다.
4. 모든 병합 gate가 충족되면 최신 head에 결속한 preflight와 동일 실행 경로에서 정상 Ready/merge를 수행한다. 실패·skip·부재 시 mutation을 멈추고 해당 원인을 수리한다.
5. Kelp/Flatback은 이 worktree를 편집하지 않고 독립 packet을 반환한다. 다음 checkpoint는 실행 중인 두 작업의 구조화된 결과다.

## Hosted 절차 중단 상태

중앙 동적 Code Quality는 supported PATCH로 `not-configured`를 설정하고 GET으로 확인했다. generic workflow disable은 422여서 registry active identity와 feature 활성화를 구분한다. advanced CodeQL security workflow는 보존했다. 제품 설정은 kelp receipt `92e725eaa5422cbc0d3356a74afc749f75f4779854bcfda270572ea24e734f94`에서 not-configured이며 중복 write는 하지 않았다. 과거 billing failure와 artifact quota 실패는 역사 증거로 유지한다. disabled/unavailable 절차를 성공·보안 면제·merge 우회로 간주하지 않는다.
