# 토큰 파일 권한 테스트의 실제 모드 검증

## 상태와 원인

2026-09-06 제안. 운영 토큰 loader의 보안 조건을 바꾸지 않는 테스트 수정이다.
기준 커밋은 `43024633eba9d96b0456970391360da5a171fbda`이며,
대상은 `tests/test_contextual_orchestrator_review_sidecar_contract.py`의
`test_token_loader_accepts_only_private_owned_single_line_files`다.

macOS 공유 임시 디렉터리에서 파일은 GID 0을 상속했지만 프로세스 GID는
20이었고 그룹 0에 소속되지 않았다. Python의 `chmod(0o2600)`은 오류 없이
돌아왔으나 실제 파일 모드는 `0600`이었다. 따라서 loader가 안전한 파일을
받아들였는데도 테스트가 거부를 기대했다. Linux도 권한 없는 호출자의 파일
그룹이 소속 그룹과 다르면 setgid를 오류 없이 제거할 수 있다고 명시한다.
이 Linux 설명은 표준 근거이며 이번 macOS 실행을 Linux 실행 증거로 보지 않는다.
([Linux man-pages project, 2026](https://man7.org/linux/man-pages/man2/chmod.2.html))

## 수정과 보존한 경계

테스트가 만든 파일만 `os.chown(file, -1, os.getgid())`로 준비한 뒤 모드를
설정한다. `-1`은 UID를 그대로 유지한다.
([Python Software Foundation, n.d.](https://docs.python.org/3/library/os.html#os.chown))
각 `1600`, `2600`, `4600` 모드를 `stat()`으로 확인한 다음 실제 shell loader의
거부를 검사한다. 모드를 흉내 내거나 검사를 skip하지 않는다. `0600` 허용,
`0644`·특수 비트·symlink·여러 줄 거부와 Actions 마스킹 검사는 유지한다.
자식 프로세스에는 PATH와 명시적 테스트 변수만 전달해 운영 환경을 상속하지 않는다.

## 재현과 검증

실제 모드 assertion을 추가한 `952963caabfb17aa000dbac21b66f894b851f851`은
loader 실행 전에 `0600 != 2600`으로 실패했다. GID 준비를 추가한
`fbe8a1f086544d12b8eedcca76eda086247088a8`은 동일한 격리 환경에서 해당 파일의
29개 테스트를 모두 통과했다. Python 3.14.6 / pytest 9.1.1의 기존 프로젝트
가상환경을 사용했으며 새 lock 설치 검증은 아니다.

프로젝트 가상환경에서 실행할 최소 검증 명령은 다음과 같다.

```sh
env -i PATH="$PATH" CI=true GITHUB_ACTIONS=true python -m pytest -q -W error \
  tests/test_contextual_orchestrator_review_sidecar_contract.py
```

전체 `tests/` 결과와 최종 정확 HEAD는 PR 증거에 별도로 기록한다. 기준 main의
다른 HTTP 응답 정리 실패 11건은 [#1879](https://github.com/ContextualWisdomLab/.github/pull/1879)가
담당하며 이 테스트 수정에 운영 코드를 복사하지 않는다. 로컬 통과는 hosted
Checks, 독립 승인, 보호 병합 또는 조직 전체 Actions 적체 해소의 증거가 아니다.

## 참고 문헌

Linux man-pages project. (2026, February 8). *chmod(2)—Linux manual page (6.18).* https://man7.org/linux/man-pages/man2/chmod.2.html

Python Software Foundation. (n.d.). *os—Miscellaneous operating system interfaces: os.chown.* Python 3.14 documentation. Retrieved September 6, 2026, from https://docs.python.org/3/library/os.html#os.chown
