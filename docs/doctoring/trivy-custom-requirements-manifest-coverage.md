# Trivy 사용자 정의 requirements manifest 탐지 범위

상태: 필수 workflow와 주기 workflow가 protected `main`에 반영되기 전까지
`active_pr`, 반영된 뒤에는 `implemented_on_protected_main`.

## 원인과 수리

Trivy 기본 pip analyzer는 생성된 파일이나 용도별로 이름 붙인
`requirements-*.txt`를 모두 찾지 못한다. Trivy 0.74.0으로 Naruon merge-ref를
검사했을 때 기본 탐지는 dependency manifest 4개를 찾았고, pip pattern을
추가한 뒤에는 11개를 찾았다. 확장 검사는
`requirements-strix-ci-hashes.txt`의 `CVE-2026-69244`를 드러냈다. 설치된
aiohttp 3.14.1은 영향받으며 3.14.3에서 수정됐다.

중앙의 두 filesystem scan owner는 pinned Trivy action step에
`TRIVY_FILE_PATTERNS=pip:requirements-.*\.txt`를 직접 설정한다. 검사 대상
저장소의 configuration file이 아니라 trusted workflow 설정이다. Trivy의
기본 탐지는 유지하면서 사용자 정의 pip manifest 탐지만 추가한다. 따라서
필수 PR 검사와 default branch 주기 backstop은 workflow, job, step, scanner
호출을 늘리지 않고 같은 manifest 경계를 사용한다.

severity 집합, 수정판이 없는 취약점 처리 정책, SARIF를 보존하기 위한 scanner
exit 0, hard-fail SARIF parser, upload 동작은 바꾸지 않았다.

## 검증 경계

회귀 계약은 기존 action 호출 두 곳의 실제 `env.TRIVY_FILE_PATTERNS` 값을
검사하고, pinned action이 지원하지 않는 `with.file-patterns` 입력이 없음을
확인한다. 별도의 로컬 Trivy 0.74.0 fixture 검사는 기본 결과에
`requirements-strix-ci-hashes.txt`가 없고 환경값을 설정한 결과에는 있음을
실증한다. protected `main`과 consumer merge-ref 실행은 여전히 필요한 runtime
증거다.

## 참고문헌

Aqua Security. (2026). *Customizing file handling*. Trivy documentation
v0.74.0, “Filtering”.
https://github.com/aquasecurity/trivy/blob/v0.74.0/docs/guide/configuration/skipping.md

aiohttp project. (2026). *Out-of-bounds heap read in C HTTP response parser may
lead to DoS* (GHSA-cq5v-8q36-5273; CVE-2026-69244).
https://github.com/aio-libs/aiohttp/security/advisories/GHSA-cq5v-8q36-5273
