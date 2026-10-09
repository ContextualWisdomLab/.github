# Goal — K-CSAP 중앙 self-hosted 품질 실행

갱신: 2026-10-09 KST. 사용자 직접 지시를 따른다.

## 결과

`ContextualWisdomLab/k-csap-skills`의 일반 품질 검증을 조직 `ContextualWisdomLab/.github`의 중앙 reusable workflow로 이동한다. GitHub-hosted fallback을 두지 않는다. 현재 제품 저장소의 `ubuntu-latest` workflow는 중앙 workflow의 immutable commit을 호출하는 얇은 caller로 교체한다.

이 Goal은 Noema/OpenCode 공유 모델·App reviewer나 LiteLLM key를 구현하지 않는다. 그 파일과 key custody는 기존 #2560, PR #2565 및 Remora worktree 소유다. 이 increment는 중앙 품질 실행의 disjoint additive callee와 소비자 caller 계약만 소유한다.

## 검증된 현재 상태

- 중앙 protected base: `7554587c2e3106a388998bcad048a3d7121de25e`.
- 제품 protected master: `0c66aec00f9f501cbbd530d8f74141d633928dc2`.
- 제품 `.github/workflows/ci.yml`은 `ubuntu-latest`를 직접 사용한다.
- 제품 repo-scoped runner `k-csap-isolated-linux` is online. Labels allow routing; its current group/ACL, running service and ID do not by themselves prove caller-context reusable-workflow admission or worktree isolation. Live check is #2560 / salmon ownership; keep group ACL changes with its operator.
- Group 13 is not the route for this candidate and all three members are offline; do not substitute the privileged control group.
- 제품 저장소는 비공개다. 2026-10-09 23:53 KST GraphQL `isPrivate=true`를 직접 확인했다. 앞선 공개 저장소 서술은 철회한다. fork 여부와 무관하게 same-repository open PR, protected master push/manual만 허용한다.
- OpenCode target allowlist와 auto LiteLLM route도 K-CSAP에 활성화되지 않았다. 품질 workflow 성공과 AI review/App approval은 별도다.
- 중앙 `LLM_GATEWAY_API_KEY` Secret metadata와 `LLM_GATEWAY_MODEL=auto`는 확인했다. 값은 읽지 않았고 새 키를 발급하거나 덮어쓰지 않는다. Secret/variable 존재는 실제 inference 또는 허용된 route의 증거가 아니다.

## 소유 파일

- `.github/workflows/k-csap-skills-quality.yml`
- `tests/test_k_csap_skills_quality_workflow_contract.py`
- `requirements-k-csap-quality-tests.in`
- `requirements-k-csap-quality-tests-hashes.txt`
- `docs/doctoring/k-csap-skills-central-quality.md`
- 이 `GOAL.md`

공유 Noema/OpenCode/runner migration workflow·relay·key·ACL은 변경하지 않는다.

## 계약

- `on: workflow_call`만 사용. 실행 입력과 inherited secret 없음.
- job 이름 `k-csap-skills-quality`.
- 제품 repo-scoped labels `self-hosted`, `Linux`, `X64`, `k-csap-isolated`만 사용. hosted fallback 금지.
- first inline step가 checkout 전에 fixed caller repository, event, ref/head를 거부한다. k-csap repository의 same-repo pull_request/push/workflow_dispatch 호출만 admit한다. **첫 step는 runner 배정 이전의 방어책이 아니다.** caller job-level gate가 실행 이전 제한이고 skip은 검증 성공으로 간주하지 않는다. repo-scoped runner는 조직 group 13의 workflow allowlist에 속하지 않는다.
- PR은 exact head SHA를 검사한다. merge candidate 통합 검증은 별도 필요하며 head 통과로 대체하지 않는다.
- checkout은 중앙 source를 불변 workflow SHA에서 읽어 실행하지 않고, caller repository의 검증 대상 SHA를 credentials 비보존으로 checkout한다.
- 권한은 contents:read, timeout과 caller-owned concurrency를 명시. callee에는 동일 concurrency group을 두지 않는다.
- uv/Python 3.11 lock 기반으로 `ruff`, `pytest`, `scripts/validate.py`, `git diff --check`를 실행한다. source corpus·secret 없음.

### 운영 수락표

| 환경 | 현재 runner에서 확인된 값 | 활성화 전 필요 조건 |
|---|---|---|
| source tree | uid 1001, cap-drop ALL, no-new-privileges, mounts 없음 | same-UID 격리는 아직 미증명. persistent shared checkout을 쓰지 않고 새 workspace 격리를 검증한다. |
| Python/uv | Python 3.12.3, uv 미설치 (salmon 보고) | locked uv/Python을 ephemeral runtime에 준비하고 버전과 package origin을 run receipt에 묶는다. |
| Group 13 | K-CSAP 접근 없음, 구성원 세 runner offline | 이 후보에서 사용하지 않는다. |
| repo runner id 2 | GitHub API online/idle | label, 별도 SSH gate, 또는 중앙 workflow 호출만으로 caller admission·network isolation이 증명되지 않는다. 실제 호출 job이 필요하다. |

### 중앙 reusable 실행격리

| 영역 | 구현 계약 | 상태 |
|---|---|---|
| runner 접근 | product repo runner id 2만 허용. group 13/privileged control fallback 없음. ACL/group 변경은 owner 전용 | 실행 전 admission 확인 필요 |
| 동시 작업 | shared host/container를 사용하는 한 same-UID untrusted 동시 job이 없음을 증명하거나, 운영자가 보장하는 상호배제 lease 사용 | 미증명; host process scan은 원자적 lease 대체 아님 |
| source/runtime | stale checkout reuse 금지; run-id/attempt 전용 source path, private runtime/cache, exact SHA checkout | workflow `9c4cc914…` 로컬 lifecycle 통과; hostile 동시 writer/강제 종료 격리는 미검증 |
| cleanup | 실제 격리·exclusive lease의 운영 수락이 필요 | 소스 재리뷰 PASS_WITH_ACTIVATION_LIMITATIONS; 원격 activation 미수락 |
| network | 허용/거부 egress 경계를 실제 workflow runner에서 확인 | NOT_RUN |
| toolchain | uv 없음이 보고됨. pinned uv와 Python 3.11을 job 내부 설치, locked sync, 실제 버전/모듈 origin 기록 | 중앙 job 미실행 |
| admission | caller repository/event/ref/head, fork 거부, checkout 전 trusted caller gate | 실제 Actions 미검증 |

## 수락 단계

1. 계약 테스트 RED→GREEN, YAML parse, actionlint.
2. 정확 파일 diff 독립 리뷰.
3. 중앙 PR merge 및 immutable commit 획득.
4. 제품 caller에서 중앙 commit pin과 기존 hosted workflow 제거.
5. 제품 repo-scoped `k-csap-isolated-linux`에서 exact-head job 실행.
6. 실행 ID, runner_name, step exits를 확인. 그 전에는 configured/proposed 상태다.
7. AI review는 #2560/Remora를 통해 literal auto actual inference와 author-distinct App review를 별도 확인한다.

## Hosted-only retirement

K-CSAP 일반 품질 검증은 hosted-only가 아니다. 중앙 self-hosted가 실제 활성화되면 제품의 hosted 실행 경로를 제거한다. group access/runner가 준비되지 않은 동안 old hosted workflow를 먼저 끄고 성공으로 표시하지 않는다. 새 중앙 gate가 실제 실행되지 않으면 unavailable evidence로 남는다.
