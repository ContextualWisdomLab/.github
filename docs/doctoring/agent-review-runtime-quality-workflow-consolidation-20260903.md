# Agent 리뷰 런타임 품질 Workflow 통폐합

- 기준 저장소: `ContextualWisdomLab/.github`
- 구현 기준: `main@232107a0b6235efaa4a221a41443c436eac3dd00`
- 확인 시점: 2026-09-03 KST
- 상태: 구현 및 exact-head 검증 대상

## 문제

다음 세 Workflow는 서로 다른 계약을 검증하지만 동일한 Pull Request에서 각각
Workflow run과 runner job을 생성했다.

- `noema-token-lifetime-quality-ci.yml`
- `opencode-rust-coverage-toolchain-quality-ci.yml`
- `strix-changed-path-quality-ci.yml`

세 파일은 각자 checkout, Python 준비, dependency 설치를 반복했다. 특히
`CHANGELOG.md` 변경은 세 Workflow 모두의 path trigger에 포함되어 있어, 제품 코드와
무관한 공통 변경 한 번으로 세 개의 별도 실행이 생성됐다. Strix 전용 품질 Workflow는
선언된 Strix 계약 파일보다 훨씬 넓은 `tests` 전체를 실행해 path-gated 검증의 책임
경계도 흐렸다.

2026-09-03에 `.github` 저장소에서만 queued run 1,544개를 다시 확인했다. 이 상태에서
독립적인 품질 Workflow 부팅을 계속 추가하는 것은 60-job ceiling과 대기열 적체를
악화시키는 구조적 원인이다.

## 선택

세 실행 책임을 `agent-review-runtime-quality-ci.yml`의 단일 Pull Request Workflow와
단일 runner job으로 통합한다.

1. concurrency group은
   `agent-review-runtime-quality-{repository}-{PR번호}`로 고정한다.
2. `cancel-in-progress: true`로 같은 저장소·같은 PR·같은 Workflow의 구형 실행만
   취소한다.
3. checkout과 Python 준비는 각각 한 번만 수행한다.
4. `git diff --name-only base...head`로 Noema, OpenCode, Strix 계약 집합을 선택한다.
5. 공통 Workflow 또는 `CHANGELOG.md`가 바뀌면 세 집합을 모두 검증하되 하나의
   runner에서 순차 실행한다.
6. Strix는 trigger에 열거된 현실적인 계약 테스트와 shell regression만 실행한다.
   저장소 전체 `tests` 재실행은 일반 통합 CI 책임으로 남긴다.
7. runner를 붙잡는 `sleep`, GitHub API polling, `workflow_dispatch`를 두지 않는다.
8. 세 기존 Workflow 파일은 successor가 테스트·path·supply-chain 계약을 완전히
   승계한 같은 commit에서 삭제한다.

## 보존한 계약

- Noema: 장시간 리뷰 중 installation token 재발급, two-phase handoff, stale-run
  cancellation 계약
- OpenCode: 격리 Rust coverage image의 LLVM 19 경로와 dispatch blob exact hash 계약
- Strix: docs-only admission, 변경 경로, ModelBehaviorError, NVIDIA NIM fallback,
  dependency hash, timeout fixture, shell quick-gate 계약
- 공급망: pin된 checkout/setup-python/harden-runner와 hash-verified Python dependency
- exact head: checkout SHA와 `github.event.pull_request.head.sha` 일치 검증

## 검증

새 회귀 계약 `tests/test_agent_review_runtime_quality_consolidation.py`는 다음을 실패
조건으로 고정한다.

- 삭제 대상 Workflow 중 하나라도 남음
- runner, checkout 또는 Python setup이 둘 이상임
- group에 Workflow·repository·PR 번호 중 하나가 없음
- `cancel-in-progress: true`가 없음
- `sleep`, `gh api`, `workflow_dispatch`가 다시 도입됨
- Noema, OpenCode, Strix의 승계 대상 테스트가 누락됨
- exact-head 검증보다 먼저 suite가 실행됨

격리된 임시 repository 구조에서 이 계약 5개를 실행해 `5 passed`를 확인했다.
GitHub의 current-head checks는 queued 상태를 성공으로 간주하지 않으며, 병합 뒤
보호된 `main`에서 파일 삭제와 새 Workflow 구문을 다시 확인한다.

## 운영 효과와 측정

공통 경로 변경 기준으로 Workflow run 수는 3개에서 1개로, runner job 수는 3개에서
1개로 줄어든다. checkout·Python setup도 각각 3회에서 1회로 줄어든다. 이는 해당
품질 lane의 부팅 수를 66.7% 줄이는 변화다.

전체 41개 요구의 진척률은 별도 project ledger에서 계속 계산하며, 이 변경 하나만으로
60-job ceiling 전체가 해소됐다고 주장하지 않는다. 다음 우선순위는 Required OpenCode,
Noema, Strix 본 실행의 current-head admission과 `cancel-in-progress: true`, 그리고
scheduler wake-up coalescing이다.

## Rollback

문제가 확인되면 이 merge commit을 revert하여 세 predecessor Workflow와 기존 테스트
경로를 함께 복원한다. successor 파일만 삭제하거나 predecessor 일부만 복구해 검증
공백 또는 중복 trigger를 만들지 않는다.

## 2026-09-06: main 전체 검사 통합 제안

기존 PR #1911의 `c36533beb63ba980c2c520fc9fe5c4c448937c8b`에 보호된
`main@43024633eba9d96b0456970391360da5a171fbda`를 일반 merge해 비교했다.
새 `main-full-suite-gate.yml`을 그대로 추가하면 materializer 관련 main 변경에서
기존 trusted-uv 두 작업과 새 작업이 함께 시작하며 전체 pytest를 두 번 실행한다.
아래 수치는 두 quality workflow의 선언된 작업 수이며 조직 전체 점유량이 아니다.

| 변경 | 보호 main | 기존 #1911 제안 | 통합 제안 |
| --- | ---: | ---: | ---: |
| materializer 관련 main push | 2 | 3 | 1 |
| 그 밖의 main push | 0 | 1 | 1 |
| 기존 PR 경로 필터에 해당하는 변경 | 2 | 2 | 1 |

`trusted-uv-materializer-quality-ci.yml`을 재사용한다. main push의 경로 제한만
없애고 기존 PR 필터·권한·action SHA·동시 실행 구분은 보존한다. checkout은 PR의
정확한 head 또는 push의 event SHA다. 별도 workflow 제안과 비교하면 해당 main
변경의 작업 수는 66.7%, 전체 suite 중복 실행은 50% 감소한다. 실제 runner 시간이나
전체 41개 목표의 완료율을 뜻하지 않는다.

Python 3.10 compile·tomli 계약을 생략하지 않고 3.14 앞에서 실행한다. 단순히
두 작업을 이어 붙이면 3.10 실패가 전체 검사를 막으므로 native `!cancelled()`와
선행 step 결과를 조건으로 사용한다. hardening·checkout·도구 준비가 실패하면
그 도구에 의존하는 실행은 막고, 취소는 존중한다. 3.10이나 focused 검사가 실패해도
준비된 3.14의 전체 검사는 실행하며 앞선 실패는 job 실패로 남는다. 실패를 성공으로
바꾸는 설정이나 별도 결과 집계 프로그램은 추가하지 않는다. 이 조건은 GitHub의
기본 `success()` 적용 규칙에 따른다. [GitHub 표현식 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions).

전체 tests·branch coverage·docstring 범위를 승계한 뒤 제안됐던 69줄 workflow만
제거한다. 파일과 변경 이력은 Git에서 복구할 수 있다. PR 전용 runtime-quality
workflow에 push를 추가하는 대안은 PR 전용 diff selector를 바꿔야 하므로 제외했다.
전체 pytest에 `-W error`, interrogate에 `--fail-under 100`을 명시한다. 기존 계약
테스트에는 단일 작업·실행 조건·설정 범위를 검증하고, 실제 pytest 명령을 비밀 없는
임시 환경에서 실행해 정상 fixture는 성공하고 경고 fixture는 실패함을 확인한다.
GitHub의 실패 후 step 실행 자체는 hosted 실행 전까지 로컬 검증으로 주장하지 않는다.

최초 통합 후보 `d9b52ca9fc34bda08feb6c3e5038490a7fef78c1`의 전체 검사는
2919 passed, 11 failed, 1 skipped, 21 subtests passed였다. 실패 11개 모두
HTTPError의 ResourceWarning을 포함했다. coverage 100%만으로 이 실행을 성공으로
취급하지 않는다. HTTP 응답 정리는 기존 owner PR #1879가 맡으며 여기로 복제하지
않는다. #1879의 보호 브랜치 반영과 이 PR의 정확한 head 재검증이 선행 조건이다.
3.10 확인은 설치된 uv Python 3.10.20으로 실제 compile·조건부 import를 실행했다.
검사 환경 재사용은 새 hash-lock 설치나 Linux hosted 실행 증거가 아니다.

근거: GitHub. (n.d.). *Evaluate expressions in workflows and actions*.
위 링크에서 2026년 9월 6일 확인. Context7 할당량 부족으로 공식 문서를 직접 확인했다.
