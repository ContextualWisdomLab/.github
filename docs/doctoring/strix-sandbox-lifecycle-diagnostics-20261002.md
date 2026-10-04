# Strix sandbox의 관측 전용 진단

## 확인된 실패와 형상 한계

PR #2261 run `36873538850`과 PR #2550 run `36872425586`은 gateway health·provider route·chat preflight를 통과한 뒤, sandbox 내부 `127.0.0.1:48080`의 Caido guest 인증에서 curl 7로 실패했다. 스캔 토큰과 취약점 수 0은 완료된 보안 검사 근거가 아니다.

역사 로그는 `ghcr.io/usestrix/strix-sandbox:1.3.0` tag를 선택했다고 기록하지만 실제 image identity와 lifecycle 상태는 제공하지 않는다. Git v1.3.0 entrypoint에는 runtime `chown`이 없지만 후속 공개 OCI 조회의 현재 tag 1.3.0에는 Git v1.5.3과 같은 조건부 UID/GID remapping·`chown`이 있다. 현재 amd64 manifest는 `sha256:e5e5d9927f15ca95ad49804ef7d22439771cd27378f400da6edd47556799baff`다. Mutable OCI tag 이름을 같은 이름의 Git tag source와 결합하면 잘못된 결론이 된다. 현재 OCI 내용도 역사 실행과의 동일성을 증명하지 않아 `chown`이나 entrypoint 누락을 실제 원인으로 귀속하지 않는다.

## 최소 관측 계약

기존 version-gated inference launcher를 재사용한다. 모델·provider·secret·workflow·이미지·backend factory·session ownership·cleanup·retry·deadline·guest 인증 결과는 변경하지 않는다. 기존 Strix 1.5.3 inference version gate는 유지한다. 관측은 그 초기화가 끝난 뒤 설치하며 `load_settings()`를 추가 호출하지 않는다.

추가 진단만 SDK 0.19.4 및 원래 guest 함수 ABI에 결속한다. Version·import·ABI가 지원되지 않으면 `STRIX_SANDBOX_DIAGNOSTICS unavailable`라는 고정 marker만 기록하고 원 scan 경로를 유지한다. 이 marker는 승인이나 실패 판정을 대체하지 않는다.

인증 시작·성공·실패 때 검증된 Docker session의 `_inner` 타입, container object ID, state의 container ID와 이미 존재하는 Docker attributes의 ID가 일치할 때만 다음 값을 보존한다.

- `phase`: 세 개의 고정 authentication 단계
- `freshness=cached`: 값은 이미 존재한 SDK-owned cache다. 현재 Docker 상태라고 주장하지 않는다.
- `image_config_id`: container inspect의 `Image`가 정확히 `sha256:` + 소문자 64 hex인 경우만 보존한다. Registry manifest digest나 공개 source commit이 아니다.
- `status`: 고정 Docker lifecycle enum
- `exit_code`: bool이 아닌 0~255 정수
- `oom_killed`: bool

`reload()`·daemon·image lookup·readiness probe·settings 읽기는 전혀 추가하지 않는다. Binding 불일치, malformed cache, 접근 실패는 `<omitted>` 필드로 기록한다. Non-Docker session의 private Docker 속성은 건드리지 않는다. 진단 출력 실패도 원 인증 return·exception·cancellation을 변경하지 않는다. Cached terminal 값에서도 원 인증을 생략하지 않는다. 별도 delete·backend wrapper·weak registry는 없다.

Container ID·이름·경로·환경값·raw container log·daemon error·guest token·provider body는 출력하지 않는다. 관측값은 운영 증거일 뿐 스캔 결과가 아니다.

## 실제 검증

Test fixture는 hash-pinned Strix wheel의 `_login_as_guest` 함수 그대로이며 함수 SHA-256은 `4e23ddba5879b791440169980433f83b17f1046892d4ee6d2496f27a56853d1c`다. Apache-2.0 원문·attribution을 보존한다. Clock과 curl I/O만 합성하며 validation 결과를 mock하지 않는다.

현재 관측 전용 변경은 관련 tests **43 passed**, 두 helper statement·branch coverage **100%**, docstring **100%**, diff check PASS다. 이 값은 축소 전 73/89개 테스트 결과와 별개다. 정상 token·terminal cache에서 원 auth 실행, 실제 token parser 오류·동일 retry 수, 원 예외/cancellation 객체, cache mismatch/접근 실패, 출력 실패, unsupported version/import/ABI의 비간섭과 backend/settings 미변경을 검증했다.

모델·컨테이너·GitHub API를 실행하지 않았으며 역사 CI 원인이나 장애 복구를 증명하지 않는다. Cache의 freshness 한계 때문에 fresh lifecycle 증명이 필요하면 별도 검토된 실행 진단으로 확보해야 한다. 이 변경으로 필수 실패를 성공으로 바꾸거나 보안 검사를 면제하지 않는다.

## 확인한 package source

- `strix-agent` 1.5.3 wheel SHA-256: `ba0b6b13f13f41e45f3eb4dba515641d1bc71363ca6e758d0cd05c20ff56b6ea`, Apache-2.0
- `openai-agents` 0.19.4 wheel SHA-256: `12e0372fae9698fe6f78e05aaeb4ccdb229602f7ef99b8195a7d68dc82869f51`, MIT
- SDK source의 `DockerSandboxSession._container`, `container_id`, facade `_inner` binding을 확인했다. 일반 최신 문서는 보조 근거이며 pinned source를 대체하지 않는다.
