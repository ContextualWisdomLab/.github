# OpenCode 공개 coverage source 전달

상위 목표: ContextualWisdomLab/.github#2560. 하위 목표: ContextualWisdomLab/.github#2638.

## 원인과 수리 범위

공개 PR의 검증된 merge-tree archive도 metadata job에서 GitHub artifact로 업로드했다. storage quota에 도달하면 metadata job이 실패하여 격리된 coverage 실행과 실제 OpenCode 모델 리뷰가 시작되지 않았다.

공개(`is_private == 'false'`) source는 isolated coverage job에서 고정 HTTPS Git origin과 정확한 base/head 객체로 다시 구성한다. private(`'true'`) source는 기존 인증된 acquisition과 archive upload/download를 그대로 사용한다. unknown은 명시적으로 실패한다. 공개 경로가 실패해도 인증·private artifact·moving ref로 fallback하지 않는다.

이 수리는 공개 **source 전달**만 artifact에 의존하지 않게 한다. private artifact, 다른 증적 업로드, scanner, release, runner capacity, 모델/API availability를 해결했다고 주장하지 않는다.

## 신뢰와 실행 계약

- coverage helper는 PR checkout이 아니라 중앙 immutable `github.workflow_sha`의 trusted checkout에서 실행한다. moving main fallback 및 전체 `toJSON(github)` 환경 전달은 coverage resolver에서 제거했다.
- trusted checkout bootstrap과 public Git child는 새 HOME/XDG, config/system/global 차단, empty init template, hooks/credentials/extraheader/redirect/proxy 차단을 사용한다. TLS 검증은 유지한다.
- 공개 repo slug, 두 lowercase40hex SHA, run/attempt를 검증한다. full history와 `.git`를 보존하며 기존 base detach → head merge `--no-ff --no-edit` 의미를 유지한다. 합성 merge commit SHA가 아닌 tree와 base/head가 동일성 기준이다.
- 정상 파일과 공백 포함 파일명을 허용한다. symlink/gitlink/non-regular, traversal, `.git` lookalike 및 control path는 checkout 전 거부한다.
- output은 validated RUNNER_TEMP 아래 독점 run/attempt 경로만 생성한다. 기존 output은 덮어쓰거나 삭제하지 않는다. 실패 시 처음 생성한 inode가 그대로인 owned directory만 정리한다.
- helper의 Git subprocess에는 Actions/App/Git 환경 자격증명이 전달되지 않는다. 이것은 실행중 Actions worker ancestor 또는 동일 UID의 경쟁 프로세스에 대한 sandbox 증명이 아니다. 기존 isolated job과 제품 Docker sandbox를 유지한다.
- 기존 syntax/replay/coverage identity, 100% 품질 기준, distinct App actor, 정확한 head/base 재검증과 실제 모델 verdict 조건은 변경하지 않는다.

## 검증과 운영 상태

새 helper와 workflow 회귀는 RED를 실행한 뒤 수리했다. actual-shell helper는 실제 Git fixture와 정상 merge/history 대조를 사용한다. 공개 HTTPS acquisition의 별도 smoke도 실행했다. 이 결과는 제품 테스트나 원격 Actions/App 승인 대신이 아니다.

`agent-review-runtime-quality-ci.yml`은 trigger·affected suite 선택·명령 목록 모두 새 회귀와 helper coverage100을 호출한다. 로컬 전체 suite, actionlint, 독립 구현 검토, 원격 exact-head 실행, 실제 모델 리뷰, App 승인은 각각 별도 receipt와 상태로 기록한다. 실패·skip·미실행을 PASS로 바꾸지 않는다.

기존 Noema production permission test는 prepare/read-only metadata와 최종 publication의 역할을 구분하도록 현재 계약과 일치시켰다. production Noema workflow는 바꾸지 않았다. read-before-write와 prepared envelope 조건을 검증하며 reviewer 권한을 줄이거나 가장하지 않는다.
