# Law AI Agent 중앙 CI 이관 기록

## 범위와 상태

- 2026-10-05 14:02 KST 사용자 승인. 중앙 소유자는 `ContextualWisdomLab/.github`다.
- 중앙 기준본: `main@37b10243cec3d160ecc9c1be75c71428b160a703`.
- 검증한 소비 기준본: `ContextualWisdomLab/law-ai-agent@301800bd9e2f1c0876ff3466b0de8013474c7d26`.
- 이 변경은 새 workflow, shell helper, 중앙 계약 테스트, 이 기록의 네 파일만 소유한다.
  기존 중앙 control/security/scanner와 소비 source는 수정하지 않는다.
- AGENTS, CLAUDE, master context, product directive, Project protocol, gap baseline,
  `ContextualWisdomLab/naruon#974` spec을 읽었다. Project #1은 조회 당시 503개 항목이었다.
  조회한 앞 100개는 전체 인벤토리가 아니다. 이 작업의 통합 담당자는 Coordinator다.
- 소스 이관과 runner 운영은 다른 증거다. 보호된 병합, GitHub job 성공, 출시를 주장하지 않는다.

## 신뢰 경계

`workflow_call`만 허용한다. 중앙 public PR 이벤트는 private 소비 code를 checkout하지 않는다.
첫 inline admission은 checkout 전에 exact caller repository, 이벤트와 SHA를 검사한다.
허용 이벤트는 같은 저장소의 main 대상 PR, main push, main 수동 실행이다.
Fork, 다른 저장소, `pull_request_target`, mutable 중앙 ref, 잘못된 SHA는 실패한다.
Fork를 성공한 skip으로 처리하지 않는다.

소비 checkout은 이벤트의 PR head 또는 github.sha다. 중앙 helper checkout은
`job.workflow_repository`와 `job.workflow_sha`다. `github.workflow_sha`를 중앙 SHA로 쓰지 않는다.
공식 문서는 job 필드가 “workflow file that defines the current job”을 가리킨다고 설명한다
(GitHub, n.d.-a). 두 checkout의 실제 HEAD를 검사한다. 경로는 `source`와 `central`로 분리한다.
`persist-credentials: false`, `contents: read`, cache 비활성화를 적용한다. 별도 secret과
`secrets: inherit`은 없다. 소비 concurrency prefix와 중앙 `law-ci` prefix는 달라야 한다.

검증한 action 객체:

- checkout commit: `fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09`.
- 소비 setup-uv의 `94527f2e458b27549849d47d273a16bec83a01e9`는 annotated tag 객체다.
  REST git tag 응답에서 commit `37802adc94f370d6bfd71619e3f0bf239e1f3b78`을 확인했다.
  중앙은 이 commit을 pin한다. uv 버전은 0.12.5다.

Runner selector는 group `CWL law CI`, labels `self-hosted/Linux/X64/law-ai-agent-ci`다.
Python 3.12/3.14 matrix는 `max-parallel: 1`, 각 job은 20분이다.
Reusable workflow의 runner 접근과 hosted billing은 caller context를 따른다
(GitHub, n.d.-b). 중앙 소스 이관으로 private caller의 전역 admission 문제가 해결됐다는 주장은 하지 않는다.
격리 runner의 운영 권한·자원·network 검증은 Coordinator의 별도 영수증이 필요하다.

기존 중앙 workflow에는 Harden-Runner가 있다. 이 lane에는 효과가 없는 action을 복사하지 않았다.
공급자 문서는 self-hosted runner에 Enterprise 구독과 runner infrastructure agent가 필요하며,
구독 없이 action만 추가하면 no-op이라고 설명한다 (StepSecurity, n.d.). Egress 강제와
host 격리는 runner provisioning 경계다. 이 기록은 해당 제어의 실제 활성화를 증명하지 않는다.

## 실행 계약

Helper는 BASH_SOURCE로 자기 경로를 찾는다. CWD에 의존하지 않는다.
정확한 consumer commit을 `git archive`로 새 scratch source에 복원한다.
이전 checkout의 dist, venv, cache를 사용하지 않는다.

- native PostgreSQL은 provisioned `pg_config --bindir`에서 찾는다. 런타임 apt/sudo 설치는 없다.
- RUNNER_TEMP의 짧은 `mktemp` immediate-child root, uid 소유권, mode 0700,
  socket 0700, TCP off, test database만 사용한다. 모든 경로 component의 symlink를 거부한다.
- `LAW_AGENT_ROOT`와 소비 안전 코드가 실제 읽는 `LAW_AGENT_POSTGRES_ROOT`는 같은 scratch다.
- 서버와 연결의 statement 10초, lock 2초 제한을 유지한다. 실제 consumer 승인 함수
  `connect(..., test_only=True)`를 사용하여 migration 001/002를 commit한다.
  committed baseline fixture가 suite 앞부분에서 필요하므로 전체 pytest 전에 초기화한다.
- uv locked sync, ruff, format, mypy, 전체 pytest/coverage90/subprocess coverage를 유지한다.
  JUnit의 모든 suite에서 skip/failure/error 0과 test count 양수를 확인한다.
- 새 outdir에서 정확히 wheel 1개와 sdist 1개를 요구한다. uv의 자동 `.gitignore`는
  `--no-create-gitignore`로 막는다 (Astral, n.d.).
- 새 lane-local cache를 online prime한 뒤 다른 새 venv에 실제 offline wheel 설치를 한다.
  source 밖에서 `python -I`로 installed prefix 안의 module, 두 migration resource와 CLI help를 확인한다.
- 생성 직후 trap을 설치한다. 기존 state marker는 덮어쓰거나 삭제하지 않는다.
  child 실패 상태를 보존하고 cleanup 실패를 성공으로 바꾸지 않는다.
  항상 실행하는 workflow cleanup은 private uid/mode와 canonical immediate-child 범위를 다시 검사한다.

Shell은 Python interrogate 대상이 아니다. 모든 shell function 앞의 역할·실패 경계 주석과
모든 embedded Python block의 module docstring을 이 파일의 문서화 계약으로 사용한다.
이는 전체 조직의 100% coverage/docstring gate가 실행됐다는 주장이 아니다.

## 실제 검증

2026-10-05 KST, macOS 로컬의 실제 native PostgreSQL 18.6와 uv 0.12.5에서 실행했다.
소비 source는 위의 정확한 committed SHA다. 소비 작업 중 추가된 미커밋 테스트는 포함하지 않는다.
요청 당시 343개와 달리 현재 기준본의 실제 collection은 **345개**다.

| 실행 | 실제 결과 |
|---|---|
| Python 3.12.14 전체 소비 suite | 345 passed, skipped 0, coverage 98.95% |
| Python 3.14.7 전체 소비 suite | 345 passed, skipped 0, coverage 98.87% |
| 두 Python의 ruff / format / mypy | 통과 |
| 두 Python의 fresh wheel/sdist + offline 새 venv 설치 | 통과 |
| 두 Python의 source 밖 isolated resource / CLI help | 통과 |
| 두 Python의 native cluster stop와 scratch 제거 | 통과 |
| 중앙 admission TDD | 15 RED → 15 GREEN |
| 중앙 helper evidence TDD | 7 RED → 23 GREEN |
| 실행 계약 TDD | 2 RED → 25 GREEN |
| 실제 빌드 `.gitignore` 회귀 | RED 확인 후 수정·두 lane 재실행 통과 |
| 독립 리뷰 cleanup/trap 회귀 | nested/public root와 trap 순서 3 RED → 31 GREEN |

Synthetic tool fixture는 child exit 37의 전파, stop 실패, 재cleanup만 검사한다.
실제 DB 검증으로 계산하지 않는다. 실제 DB 결과는 위의 두 native 실행뿐이다.
독립 리뷰 뒤 강화한 최종 helper bytes는 아래 최종 checkpoint에서 다시 검증한다.

`actionlint 1.7.12`는 공식 `job.workflow_*` 필드를 아직 모른다. 처음 실행은 이 필드와
custom label에서 실패했다. 임시 custom-label config와 이 세 필드의 exact error regex만
ignore한 실행은 통과했다. Workflow expression 검사가 완전히 지원된다는 주장은 하지 않는다.
공식 context 문서와 admission runtime 테스트를 별도 근거로 남긴다.
Shellcheck와 `bash -n`은 통과했다. 중앙 full-suite/100% coverage는 별도 실행 상태를 기록한다.

## 최종 로컬 checkpoint — 14:42 KST

독립 리뷰 수정 뒤 동일 helper bytes를 두 Python에서 다시 실행했다.
3.12.14는 345 passed / skip 0 / 98.95%, 3.14.7은 345 passed / skip 0 / 98.87%다.
양쪽 offline 실설치, prefix/resource/CLI help와 cleanup을 포함하여 exit 0이다.
중앙 subset은 일반 환경과 `GITHUB_ACTIONS=true`에서 각각 **33 passed**다.
Shellcheck, bash 구문, 6개 embedded Python block compile, 제한적 actionlint와 diff check는 통과했다.
중앙 전체 suite와 100% coverage/interrogate는 이 worker에서 실행하지 않았다.

최종 core 파일 SHA-256:

| 파일 | SHA-256 |
|---|---|
| `.github/workflows/law-ai-agent-ci.yml` | `3aac714edfb5438c1f7c0eb6420fcff2f43b39692324cd6d7e86c4c103cfc164` |
| `scripts/ci/law_ai_agent_ci.sh` | `7ee3d7d4f7083d87b921530f4ee3c7ce7dd8041e9611f4429390aa58f9e4e935` |
| `tests/test_law_ai_agent_ci.py` | `8afd78b82f0c2a270375192eb35454735b1bb192b573bc89027d951b50900b35` |

이 문서 자체의 hash는 Coordinator handoff에서 별도로 전달한다.
다른 agent의 runner image/provisioning/review 파일은 shared worktree에 있지만 이 worker는 수정하지 않았다.

## 남은 통합 확인

1. 독립 reviewer에게 final 네 파일 SHA-256을 전달한다.
2. Coordinator가 격리 Linux runner에서 final helper exact bytes를 실행한다.
3. 소비 thin SHA caller의 exact commit과 중앙 protected commit을 연결한다.
4. GitHub current-head required checks, 독립 승인, protected merge를 따로 검증한다.
5. 활성 기존 writer/cron의 재개는 Coordinator가 소유한다. 이 worker는 스케줄을 변경하지 않는다.

## References (APA 7)

Astral. (n.d.). *Commands: uv build*. Retrieved October 5, 2026, from
https://docs.astral.sh/uv/reference/cli/

GitHub. (n.d.-a). *Contexts reference*. Retrieved October 5, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/contexts

GitHub. (n.d.-b). *Reusing workflow configurations*. Retrieved October 5, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations

StepSecurity. (n.d.). *Harden-Runner*. Retrieved October 5, 2026, from
https://github.com/step-security/harden-runner
