# Goal — 중앙 self-hosted CI 및 독립 AI 리뷰 복구

상태: 실행 중. 로컬 구현·실제 CI·리뷰·승인·병합은 별도 단계다.

## 사용자 승인 범위

- 전환 가능한 CI는 ContextualWisdomLab/.github 중앙 self-hosted runner로 전환한다.
- GitHub-hosted 전용 절차가 병목이라면 그 절차를 중단한다. 비실행을 보안 PASS로 표시하지 않는다.
- Noema/OpenCode는 self-hosted runner에서 실질적인 독립 리뷰를 실행한다. 실제 통과 판정에만 작성자와 다른 GitHub App 계정의 exact-head APPROVED를 게시한다. 가상의 두 번째 인간 개발자를 요구하지 않는다.
- 모델은 auto를 사용한다. personal LiteLLM의 기존 서비스 키 custody를 재사용한다. 중복 키 발급·master/provider 키 출력·무제한 비용 승인은 하지 않는다.
- guest04는 기존 queue-wait 담당의 no-start/no-reboot hold와 원격 협력 flock 경계를 유지한다. 이 lane은 VM·runner ACL을 변경하지 않는다.

## 현행 근거

| 항목 | 관측 | 다음 검증 |
|---|---|---|
| 보호 중앙 main | fetch한 7554587c2e3106a388998bcad048a3d7121de25e | 변경 전 재조회 |
| package successor | #2261 closed, #2573 open / 41e9c45407e3f72d138da2ad24cdf934aa42fbe1 | 보존 및 current-head 수용 |
| 전체 runner 전환 owner | #2565 open / 6e924f32a2dbaa0950709c6d8f1391fc1058ef43 | owner 수리·실제 runner 수용 |
| AI/서비스 키 owner | #2560 open; 기존 LLM_GATEWAY_API_KEY metadata와 auto 변수는 peer receipt이며 실질 모델 실행 증거 아님 | serialized custodian·effective key/model·consumer 검증 |
| remora | 별도 중앙 worktree의 Noema/sidecar/model/App 코드 수정 확인 | 공동 파일 덮어쓰기 금지; package scope 전달 |
| 인증 | gh auth status는 실패했으나 authenticated GraphQL viewer 및 PR 읽기는 성공 | 토큰 폐기/재발급 금지; 실제 HTTP 경계로 판정 |
| gateway | 지정 TLS endpoint의 OpenAPI 수신, version 1.104.0 | credential custody 후 실제 auto 추론 |

## 단계와 완료 기준

### G1 — package runner 전환과 실제 결함 수리

두 package job을 CWL CI isolated 그룹과 self-hosted/linux/x64/cwlab-ci-isolated labels로 지정했다. Hosted fallback은 없다. producer와 inspector 분리, called workflow exact SHA, credential 비영속화, artifact 실패 거부는 유지한다.

로컬 focused: 39 passed 정상 및 GITHUB_ACTIONS=true. 전체 실행: 5,350 passed, 4 skipped, 40 subtests, 1 failed. 실패는 audit CodeQL fixture가 고정 날짜를 실제 시계에 비교하는 경계다. 이전 baseline 재현은 cwd가 원 checkout이어서 clean baseline 증거가 아니며 폐기하지 않고 이 한계를 보존한다. 실제 baseline cwd에서 재현한 뒤 deterministic clock fixture로 수리한다.

Actionlint 1.7.12는 GitHub.com 공식 job.workflow_repository/sha를 모른다. 기존 ignore는 삭제한다. parser/schema 미지원은 미통과로 남긴다. custom labels 선언은 유지한다. cross-repo 실제 checkout은 별도 미수행이다.

### G2 — 전체 중앙 runner 정책 수용

#2565가 전체 source routing을 소유한다. 이 lane은 누락 package job만 소유한다. owner의 source 전환은 완료 증거가 아니다. 모든 workflow source와 live registry 및 dynamic hosted producer를 각각 조사한다. 불가피한 hosted-only 중단은 lost evidence와 required consumer 영향을 명시한다. missing/offline runner를 hosted-only로 분류하지 않는다.

완료: 실제 eligible self-hosted job assignment, 격리/cleanup canary, 현재 source의 terminal required Checks. ACL·VM 변경은 해당 운영 담당과 협력한다.

## 최신 로컬 검증

실제 clean baseline cwd에서 audit 고정 날짜 fixture 실패를 재현했다. CLI fixture는 기준 시계를 고정하고 default-clock positive는 현재 analysis timestamp를 생성하도록 수리했다. 승인 기준이나 production freshness 상한은 변경하지 않았다.

scratch가 home 아래에 있으므로 sandbox 테스트 5건이 실제 host home 차단 조건과 섞여 실패했다. 이 5건은 synthetic guest home을 명시해 launcher/path-traversal을 독립 검증하도록 보강했다. Production home-denial은 그대로다.

최종 CI-mode 전체 실행: 5,351 passed / 4 skipped / 40 subtests, exit 0, 343.51초. HTTPError cleanup ResourceWarning은 출력에 남는다. Actionlint의 schema 오류는 suppress하지 않는다. 변경 파일은 아직 미commit/미push이며 독립 리뷰 및 current-head 원격 수용이 남는다.

### G3 — LiteLLM auto 독립 AI 리뷰 및 조건부 승인

#2560 기존 transport/key 담당과 remora shared model/App 담당을 재사용한다. 전달 요청은 합의/실행 증거가 아니다. key를 chat/log/artifact로 출력하지 않는다. provider fallback·private retention 제한을 우회하지 않는다.

완료: effective 서비스 키의 auto 허용 검증, 실제 authenticated auto 호출, Noema/OpenCode 각각 substantive verdict, exact head/base 재확인, author-distinct App formal approval, resolved threads와 required Checks 후 ordinary protected merge. 자신 계정 승인·synthetic status·admin bypass 금지.

## 소유 파일 및 다음 실행

이 worktree는 package workflow/test/doctoring, .github/actionlint.yaml, GOAL.md를 소유한다. audit time fixture는 root-cause 수리 후보로 baseline 재현 후 최소 수정한다. shared Noema/OpenCode/model/relay와 다른 worktree에는 쓰지 않는다.

다음: 시계 fixture baseline 재현·수리, actionlint ignore 제거, focused 및 전체 수용 재실행, owner와 credential/AI integration 인계 확인. 기존 목표 전체는 G2/G3 완료까지 유지한다. 로컬 PASS를 원격 승인/병합으로 보고하지 않는다.
