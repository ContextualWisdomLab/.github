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
