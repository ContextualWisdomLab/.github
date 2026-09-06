# OpenCode 접수 runner 통합

- 상태: Proposed. 보호 병합·실제 runner 검증 전.
- 기준: `main@43024633eba9d96b0456970391360da5a171fbda`, 2026-09-06.
- 범위: `.github/workflows/opencode-review.yml`와 기존 접수 회귀 테스트.

## 문제와 선택

기존 경로는 trusted bootstrap 뒤에 live-head 접수만 수행하는 runner를 하나 더
배정했다. 접수 shell을 bootstrap의 Pingora 정책 검사 뒤로 옮기고, step 출력을
job 출력으로 전달한다. 세 후속 job은 bootstrap 성공과 접수 결과를 직접 요구한다.
새 workflow·helper·의존성·API 호출·polling을 추가하지 않는다.

접수 shell은 기준 커밋과 동일하다. SHA-256은
`de6d073fec78d249c92c153f1c5235bc8c6858984f43be3b106d2d596aeb5c3a`다.
기존 접수 job의 5분 상한은 해당 metadata step에 보존한다. 모델 timeout이 아니다.
오래된 이벤트는 성공한 `admitted=false`로 종료한다. API 오류와 잘못된 이벤트
입력은 이제 별도 접수 job 대신 필수 bootstrap을 실패시키며 후속 작업을 막는다.

bootstrap의 기존 read 권한과 OIDC 권한을 유지한다. 이전 접수 전용 job에는
OIDC 권한이 없었지만, 옮긴 step은 이제 `id-token: write`를 상속하는 job 안에서
실행된다. 접수 step 자체는 OIDC 토큰을 요청하지 않으며 PR 코드를 checkout하거나
실행하지 않는다. 이 권한 경계 차이는 runner 통합의 명시적인 검토 대상이다.
별도 cleanup job의 Actions write 권한과 workflow concurrency는 그대로 둔다.

## 제거하지 않은 작업과 근거

2026-09-06 읽기 전용 GitHub API 조사에서 활성 저장소 75개, 보호 브랜치 409개,
고유 ruleset 34개를 확인했다. 기존 두 접수 표시명 `admit-current-head`와
`Admit current pull request head`를 요구하는 status context는 없었다.
단순 출력만 하는 `coverage-source-tree`도 Naruon·linux-cluster-ops의 `develop`
보호 설정이 요구한다. 따라서 두 coverage context와 실제 dispatch coverage 작업은
삭제하지 않았다. 권한이 다른 cleanup 통합도 이 변경에서 제외했다.

조사 경로는 `repos/{repo}/branches?protected=true`, 각 저장소의
`rulesets?includes_parents=true`, 고유 ruleset 상세이며 모든 페이지를 포함했다.
원시 조사 파일 SHA-256은
`db783b2bcfa48ad9354ba075aad8e4d42fd379ac7f3e3b23b08519f1a88104ff`다.
이 조사는 시점 증거다. 병합 전 보호 설정을 다시 확인하고 바뀐 필수 context가
있으면 삭제 후보를 재평가한다. 설정을 지우거나 gate를 완화하지 않는다.

## 측정과 검증

| 선언된 실행 경로 | 기준 | 후보 | 감소율 |
|---|---:|---:|---:|
| 유효 opened/ready PR job | 5 | 4 | 20% |
| synchronize job, 별도 cleanup 포함 | 6 | 5 | 16.7% |
| review 진입까지 직렬 runner 배정 단계 | 3 | 2 | 33.3% |

이는 job 구조의 감소량이며 조직 전체 runner 점유·대기시간·41개 요구의 완료율이
아니다. 기준의 관련 테스트 48개는 통과했다. 접수 계약을 먼저 추가한 커밋
`2320129a0c5be139ae913e1f271e04308d96bb22`에서 1 failed/52 passed를 확인한 뒤 통합 구현을 적용했다.
실제 접수 shell을 격리된 가짜 GitHub 응답으로 실행해 현재/구형 head, 열린/닫힌
PR, 닫힘 이벤트, API 실패 여섯 경우를 검증한다. 운영 환경 변수는 상속하지 않는다.

```sh
python -m pytest -q -W error tests/test_opencode_required_rerun_capacity.py tests/test_opencode_required_verdict_regression.py tests/test_pingora_edge_workflow_contract.py tests/test_opencode_agent_contract.py tests/test_required_workflow_queue_contract.py tests/test_opencode_coverage_identity.py tests/test_opencode_coverage_publication_regression.py
actionlint .github/workflows/opencode-review.yml
CI=true GITHUB_ACTIONS=true python -m pytest -q -W error tests --cov --cov-branch --cov-report=term-missing
```

각 명령은 저장소에서 실행한다. 정확한 후보 SHA의 결과·종료 코드·실패 분모는
PR에 기록한다. 격리된 macOS PATH의 전체 검증은 기준·후보 모두 같은 12개 실패를
재현했다. 11개는 HTTP 응답 정리, 1개는 기존 token-file 특수 권한 비트 검사다.
전자는 선행 #1879에서 해결하며 후자는 별도 원인 조사 대상으로 남긴다. 이 후보에
runtime 코드를 복제하거나 warning을 숨기지 않는다. 선행 보호 병합 뒤 새 base를
일반 merge로 반영하고 전체 suite를 재검증한다. 로컬 테스트는 GitHub의 output 전달,
step budget, `needs` 실행 증거가 아니므로 병합 뒤 해당 SHA의 실제 run도 확인한다.
회귀 시 이 통합 변경 전체를 일반 revert해 접수 job·세 의존 경로를 함께 복원한다.

## 근거

- GitHub. (n.d.-a). [*Passing information between jobs*](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/pass-job-outputs). Retrieved September 6, 2026.
- GitHub. (n.d.-b). [*Workflow syntax for GitHub Actions*](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds). Retrieved September 6, 2026. `needs` 실패 전파와 step `timeout-minutes` 계약.
