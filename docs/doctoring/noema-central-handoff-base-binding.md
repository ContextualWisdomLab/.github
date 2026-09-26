# Noema 중앙 handoff와 live base 검증

## 원인과 수정 범위

기준 소스는 `fb17ef556f94f673234aa557254ae52779e9a7b0`이다.
`scripts/ci/noema_review_handoff.py`는 소비자 저장소의 dispatch endpoint에
`noema-review`를 보냈지만, 이 이벤트의 수신 workflow는 중앙 `.github`에 있다.
소비자의 HTTP 204 응답만으로 중앙 리뷰가 시작됐다고 볼 수 없다.

송신 위치를 `repos/ContextualWisdomLab/.github/dispatches`로 맞추고,
OpenCode의 검증된 metadata 출력에서 target repository, PR number,
base ref/SHA, head SHA를 전달한다. 중앙 수신기는 최초 admission과 기존
모델 직전 live PR 조회에서 같은 입력을 확인한다. 대기 중 base가 바뀌어도
예전 입력으로 모델 실행을 허용하지 않는다.

정식 필드는 `pr_base_ref`이고, 기존 agent-mention 송신자의 `base_branch`도
허용한다. 두 값이 모두 있으면 같아야 한다. 누락·잘못된 형식·live PR의
repository/number/base/head 불일치는 fail closed이며 기본 base를 지어내지 않는다.
기존 `pull_request_target` 경로는 event의 PR base/head를 사용한다.
이 수신 workflow에 `workflow_call` 또는 `pull_request` trigger를 새로 추가하지 않는다.

## 재현과 검증

`tests/test_noema_review_handoff.py`는 실제 송신 함수를 주입 runner로 실행하고
중앙 endpoint와 전체 payload를 확인한다. 수신기 검증은 기존 workflow shell
추출기를 재사용해 실제 두 `run:` 블록을 실행한다. fake `gh`는 지정된 PR GET만
허용하며 외부 API를 호출하지 않는다. canonical/legacy/both 양성과 충돌·누락·
malformed·base 변경·다른 repository/PR/head 음성을 함께 검증한다.

최초 endpoint/admission RED는 11 failed, 4 passed였다. 모델 직전 검사에도
같은 회귀를 연결한 RED는 10 failed, 18 passed였다. 초기 fixture 목록의
SyntaxError와 shell 추출 오류는 별도 테스트 작성 오류였으며 생산 결함의 RED에
포함하지 않는다. 정확한 최종 실행 명령과 결과는 PR receipt에 기록한다.

최종 영향 범위는 18개 기존 테스트 파일이다. normal과 `GITHUB_ACTIONS=true`에서
각각 `-W error`로 788 passed, 1 skipped를 확인했다(8파일 308 + 인접 7파일
135/1 skipped + scheduler 3파일 345). 전체 저장소 suite 결과로 확대하지 않는다.
handoff 모듈만 별도 측정한 coverage는 154 statements, 50 branches 모두 100%다.

로컬 actionlint 1.7.12의 두 파일 동시 검사는 출력 없이 condition wait에 머물렀다.
자식 process가 없음을 확인하고 본인 실행 PID 46672만 종료했다(exit 143).
`GOMAXPROCS=2` 재시도 PID 53592도 같은 증상으로 종료했다(exit 143).
다른 세션의 PID 89987은 변경하지 않았다. 이후 `gtimeout 30` 단일 파일 검사에서
Noema는 exit 0, OpenCode는 exit 124였고, **기준 fb17ef 원본 OpenCode도**
`gtimeout 20`에서 exit 124였다. 정지 원인 자체는 미확정이다.

따라서 OpenCode 전체 외부 검사 완료를 주장하지 않는다. 두 파일의 actionlint
native YAML/expression 검사(`-shellcheck= -pyflakes=`)는 exit 0이고, 기존
추출기로 읽은 변경된 세 shell 블록의 ShellCheck는 각각 exit 0이다. 기존 shell
syntax/queue 계약과 위 normal/CI 회귀도 통과했다. 재발 시 기준·변경본의 동일
검사를 비교하고, 제한 시간 종료나 출력 부재를 통과로 세지 않는다.

## 남은 경계와 운영 확인

HTTP 204 뒤에도 기존 trusted publisher의 exact-head terminal review를 확인해야
하며, 접수·queued·모델 시작을 승인으로 바꾸지 않는다. 이 변경은 리뷰 자체의
base/workflow/run provenance를 새로 증명하지 않는다. webhook 설정 소유권,
Strix→OpenCode→Noema 순차 admission, provider runtime 502 복구도 별도 작업이다.
ContextualWisdomLab/.github#2051의 remote terminal model-run binding도 이 변경에
포함하지 않는다.
토큰 선택, 권한, concurrency, 재시도/대기 시간, free-only/ZDR 정책은 바꾸지 않는다.

배포 후 운영자는 중앙 receiver run의 target PR metadata와 실제 terminal review를
각각 확인해야 한다. 로컬 mock 테스트는 배포·credential 접근·실제 모델 완료
증거가 아니다. 실패 시 원래 진단을 보존하고 무조건 재dispatch하지 않는다.
