# Exact Artifact SBOM 품질 runner 통합

## 2026-09-04 통합 품질 job 이관

전용 품질 workflow는 삭제하고 계약을
`.github/workflows/agent-review-runtime-quality-ci.yml`의 영향 선택 job으로 옮겼다.
같은 PR의 관련 파일이 바뀔 때만 실행하며, 통합 job의 exact-head checkout과
`contents: read` 권한을 공유한다. Python 3.10 compile을 먼저 수행한 뒤 Python 3.14를
복원해 hash-locked 도구로 coverage, pytest, interrogate, compile을 실행한다.
SBOM 발행·attestation reusable workflow 자체는 변경하지 않았다.

- 기준: `ContextualWisdomLab/.github@5afbf58cc62c8ff12a57c60d426d1352307fcd04`
- 확인 시점: 2026-09-03 KST
- 상태: 구현 및 current-head 검증 대상

## 문제

`Exact Artifact SBOM Attestation Quality`는 동일 source revision을 검증하기 위해
Python 3.10 compile job과 Python 3.14 coverage job을 별도 runner에 배치했다. 그 결과
한 workflow run마다 runner 부팅, harden-runner, checkout, exact-head 검증이 두 번
수행됐다.

Python 3.10 경로는 compile만 수행하며 Python 3.14 경로와 병렬 결과를 합성하지 않는다.
따라서 두 job 사이에 독립 장애 격리나 병렬 계산상 이점이 없고, 60-job ceiling에서는
별도 runner가 queue slot과 boot 시간을 추가 소비한다.

## 선택

두 Python 검증을 하나의 `exact_artifact_quality` job에서 순차 실행한다.

1. runner hardening, checkout, exact-head 검증은 한 번만 수행한다.
2. Python 3.10을 설치해 production과 contract 파일을 compile한다.
3. 같은 runner에서 Python 3.14를 활성화해 hash-locked tooling을 설치한다.
4. 기존 세 contract suite와 새 workflow regression을 실행한다.
5. verifier branch coverage 100%, docstring 100%, Python 3.14 compile을 그대로 보존한다.
6. PR concurrency는
   `exact-artifact-sbom-attestation-quality-{repository}-{PR번호}`를 사용하고
   `cancel-in-progress: true`로 같은 PR의 구형 품질 실행만 취소한다.
7. push 검증에서는 PR 번호 대신 ref를 사용해 default-branch revision별 품질 검증을
   이어간다.
8. API polling, runner-held sleep, manual dispatch를 두지 않는다.

## RED와 GREEN 계약

`tests/test_exact_artifact_quality_single_runner.py`는 다음을 고정한다.

- `runs-on`, harden-runner, checkout이 각각 정확히 1회
- Python 3.10과 3.14 setup이 각각 1회
- 3.10 compile이 3.14 coverage보다 먼저 실행
- concurrency group에 workflow 이름, repository, PR 번호가 포함
- `cancel-in-progress: true`
- predecessor의 production 및 contract 파일 전부 보존
- branch coverage·docstring threshold 100% 보존
- `gh api`, `sleep`, `workflow_dispatch` 없음

## 효과

한 workflow run의 runner job 수는 2개에서 1개로 50% 줄어든다. hardening과 checkout도
각각 2회에서 1회로 줄어든다. Python runtime setup은 최소 지원 버전과 현재 버전을
실제로 검증해야 하므로 2회를 유지하지만, 두 setup은 동일 runner에서 수행된다.

이 변경은 SBOM publication workflow나 attestation mutation을 취소하지 않는다. 오직
품질 검증 workflow만 stale-run cancellation 대상이다.

## Rollback

문제가 발견되면 이 commit 전체를 revert해 두 job 구조와 기존 context를 함께 복원한다.
Python 3.10 compile 또는 Python 3.14 coverage 중 하나만 제거하는 부분 rollback은 하지
않는다.
