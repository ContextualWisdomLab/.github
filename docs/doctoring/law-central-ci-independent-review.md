# Law central CI — independent bounded review

검토일: 2026-10-05 KST. 담당 dispatch: `ctx_03ac2f3ed053`.

## 판정

**BOUNDED PASS — writer 완료 뒤 frozen 6파일 bytes와 전달 SHA256이 일치했다. 원격 gate, 소비 caller pin과 출시의 PASS가 아니다.**

Coordinator는 writer_done `msg_87a489827bae`, outcome succeeded와 14:44 KST byte freeze를 확인했다. 검토자는 freeze SHA256 6개를 현재 파일에서 직접 다시 계산하고 일치시켰다. 조기 발견한 root 경계와 trap-before-marker 결함은 final helper에서 수정됐다. 현재 승인된 source/design 검토 범위에서 미해결 blocking 결함은 발견하지 않았다.

검토 대상은 중앙 신규 reusable workflow, shell helper, 계약 테스트와 운영 설명이다. 제품 원문을 중앙에 복사하지 않는다. 검토자는 제품 소스, 자격 증명, 다른 private 자료를 읽지 않았다. 소스 수정, Git 변경, 빌드, 전체 테스트, 컨테이너 실행과 등록을 하지 않았다. 이 문서만 검토자가 소유한다.

## 조기 발견 — 수정 중인 bytes 기준

1. **Cleanup 경로 경계** — 최초 helper의 `cleanup_root`는 최종 root의 디렉터리/비-symlink 여부와 basename만 검사했다. `cleanup_state`는 marker의 regular/non-symlink 여부와 lexical prefix만 검사했다. marker/root owner, mode, 정규화된 즉시 자식과 parent symlink 검증이 없었다. 삭제를 실행하지 않고 Bash 조건만 평가했다. `/scope/lawci.parent/lawci.child`와 `/scope/lawci.parent/../lawci.child` 모두 lexical prefix 조건에 통과했다. 기존 정리 경계 안에서 owner/mode와 canonical direct-child 경계를 확인하는 수정을 coordinator에 전달했다.
2. **Marker 생성 이전 실패** — 최초 helper는 `mktemp` 이후 state 부재 검사와 state 쓰기를 완료한 다음 EXIT trap을 설치했다. state 충돌/쓰기 실패 시 새 scratch 정리가 실행되지 않는다. 기존 marker와 이번 실행 marker의 소유 여부를 구분하면서 trap을 일찍 설치하는 좁은 수정이 필요하다.
3. **실행 증거의 강도** — 최초 helper는 PostgreSQL 도구 존재를 검사하나 16.15 runtime version을 검사하지 않았다. matrix Python은 uv 선택값이며 실행 interpreter version 검사가 없었다. 설치 wheel의 import는 source 밖임만 확인하고 이번 installed prefix 안임은 확인하지 않았다. image/runtime 영수증과 최종 수정 확인이 필요하다. 재현 없이 실제 image가 잘못됐다고 주장하지 않는다.

## 현재 직접 관측

- 14:31 KST GitHub API: runner group `11`, `CWL law CI`, visibility `selected`, `allows_public_repositories=false`, 선택 repository ID는 `[1404539192]` 한 개다. workflow restriction은 설정되지 않았다. 이것은 선택된 private 저장소의 접근 범위이며 특정 중앙 workflow만 허용하는 ACL은 아니다.
- 같은 조회: runner `1134186`, Linux, `online`, `busy=false`; labels는 `self-hosted`, `Linux`, `X64`, `law-ai-agent-ci`다. 재등록, 영구 재사용 또는 컨테이너 폐기의 증거는 아니다.
- 최초 workflow는 `workflow_call`만 받는다. contents 권한은 read다. 두 checkout은 persist-credentials=false이며 consumer head와 called workflow SHA를 따로 검증한다. admission은 owned same-repository PR, main push, main dispatch만 인정하고 fork와 pull_request_target을 거부한다.
- `bash -n scripts/ci/law_ai_agent_ci.sh`는 exit 0이었다. 검토 Python은 `/Users/seonghobae/.pyenv/versions/3.14.5/bin/python3`, version `3.14.5`였다. 이것은 runner Python 3.12/3.14 실행 증거가 아니다.
- 중앙 기존 tracked 파일 수정은 최초 `git status --short`에 없었다. 신규 workflow/helper/test 3개가 untracked였다. 다른 writer가 작업 중이므로 이 관측을 최종 상태로 재사용하지 않는다.

## 공식 설계 근거

- GitHub 2026-09-03 Changelog, “GitHub Actions: Early September 2026 updates”: `job.workflow_ref`, `job.workflow_sha`, `job.workflow_repository`, `job.workflow_file_path`가 해당 job을 정의한 workflow의 identity를 제공한다. github.workflow_*와 달리 reusable called workflow를 가리킨다. GitHub Enterprise Server에는 제공되지 않는다.
- GitHub Docs, “Contexts reference”, job context: 위 called-workflow identity 의미가 현재 reference에도 있다.
- GitHub Docs, “Reusing workflow configurations”, access/runner behavior: private caller는 public reusable workflow를 사용할 수 있다. Actions 허용 설정은 별도 전제다. 같은 조직 called workflow는 caller에게 제공된 조직 self-hosted runner를 사용할 수 있다. GitHub-hosted runner 배정과 billing은 caller context다. 중앙 이전을 billing 또는 현재 StartupFailure 해소로 판정하지 않는다.

공식 페이지는 검토 세션에서 직접 검색했다. 운영 API 관측은 문서 일반론과 구분한다.

## 중간 수정 확인 — 14:37 KST, 아직 freeze 전

- `validate_owned_root`가 marker/root uid와 0600/0700 mode, immediate-child, parent symlink 검증을 추가했다. 기존 lexical-only 문제는 읽은 revised bytes에서 해소됐다.
- trap이 marker 생성보다 먼저 설치되고 `state_owned`가 이전 marker 삭제를 막는다. 조기 lifecycle 문제는 읽은 revised bytes에서 해소됐다.
- source Python major/minor runtime 검사와 wheel import의 `sys.prefix` 내부 검사가 추가됐다. PostgreSQL 16.15는 여전히 Dockerfile의 major-only 패키지 지정과 실제 image receipt를 구분해야 한다.
- 4번째 파일은 `.github/runner-images/law-ai-agent/Dockerfile`이다. 공식 base digest는 dispatch와 일치한다. build 중 root는 apt 설치에만 사용하고 최종 USER는 runner다. 실제 배포 image와 final Dockerfile bytes 동일성은 미확인이다.

## 소비 계약 테스트 — 명시적으로 승인된 한 파일

Coordinator가 `/Users/seonghobae/orca/projects/law-ai-agent-pg-moa/tests/test_central_ci_caller.py`만 읽도록 추가 승인했다. 42줄의 해당 파일만 읽었다. private product source와 실제 caller workflow는 읽지 않았다.

- immutable 40-hex 중앙 참조 1개, 중앙 실행 중복 금지, contents read, events와 concurrency literal을 검사한다.
- 테스트 보강 권고: YAML 구조로 `uses`가 job-level인지, push와 pull_request 양쪽 branch 범위가 main인지 확인한다. 현재 branch literal 한 번만 있으면 통과한다. 이는 실제 caller 결함 판정이 아니라 테스트의 증명 범위다.
- consumer test의 현재 RED3/pass1은 coordinator 관측이며 검토자가 실행하지 않았다. 중앙 SHA pin을 쓰기 전 결과를 최종 gate로 주장하지 않는다.

## 최종 frozen bytes와 직접 bounded probe

14:44–14:46 KST, 다음 SHA256을 full bytes에서 계산했다. 모두 Coordinator freeze receipt와 일치했다.

| 파일 | SHA256 |
|---|---|
| `.github/workflows/law-ai-agent-ci.yml` | `3aac714edfb5438c1f7c0eb6420fcff2f43b39692324cd6d7e86c4c103cfc164` |
| `scripts/ci/law_ai_agent_ci.sh` | `7ee3d7d4f7083d87b921530f4ee3c7ce7dd8041e9611f4429390aa58f9e4e935` |
| `tests/test_law_ai_agent_ci.py` | `8afd78b82f0c2a270375192eb35454735b1bb192b573bc89027d951b50900b35` |
| `docs/doctoring/law-ai-agent-central-ci.md` | `08f02306e9aee3d9ca2a4d5ada6b0cc50a492831de08e4712479eec13772e6e5` |
| `.github/runner-images/law-ai-agent/Dockerfile` | `17596881141c761c5e1a55a81d1b2b76559f6fac3aa8b66e1b705f4990808694` |
| `docs/doctoring/law-ci-runner-provisioning.md` | `c798d85cc1db6b92113b2463dbbdb9b12b7115c23dbdf02f7fc0937f041af281` |

직접 실행 결과:

- 실제 workflow admission parsed Python body: 정상 main push 허용, mutable 중앙 ref/target event/중앙 caller/uppercase SHA 거부, **5개 PASS**.
- 실제 helper의 root validator parsed Python body: owned direct-child 허용, nested root/symlink root/0644 marker 거부, **4개 PASS**. validator만 실행했고 stop/remove는 실행하지 않았다.
- embedded Python **6개 compile PASS**, `bash -n` exit **0**.
- 승인된 소비 테스트 44줄을 다시 읽었다. Coordinator가 event별 main branch와 job-level uses regex를 추가했음을 확인했다. 실제 caller는 중앙 commit 전이므로 별도 후속 검토다.

## 실행 증거의 경계와 다음 단계

- writer 문서의 macOS native 두 lane/33 central tests 성공은 writer 관측이다. 검토자가 재실행하지 않았다.
- Coordinator는 final helper `7ee3d7d…`와 consumer baseline `301800bd…`를 사용한 Linux 격리 image에서 3.12.3: 345 pass, skip 0, coverage 98.95%; 3.14.7: 345 pass, skip 0, coverage 98.87%, full quality/offline wheel/cleanup exit 0을 직접 확인했다고 전달했다. 이는 producer 관측이며 검토자 자신의 실행과 구분한다.
- image SHA, container limits/mounts와 sudo 거부는 provisioning 문서와 Coordinator producer 영수증이다. 문서는 egress 방화벽 미검증, VM 수준 격리 아님, apt 재빌드 결과 가변, ephemeral 이후 새 등록 필요를 명확히 기록했다. 현재 source 검토가 이를 보안 인증으로 확대하지 않는다.
- inherited PGOPTIONS는 helper에서 제거된다. native server timeout 10s/2s를 유지한다. 단일 job 20분은 품질 lane이며 중앙 모델 검토 timeout 변경이 아니다.
- 실제 소비 thin SHA caller, 원격 current-head required checks, ordinary protected merge/publish가 남았다. 중앙 기존 review/security gate는 변경하지 않았다. 중앙 이관은 billing/permission gate 우회가 아니다.
