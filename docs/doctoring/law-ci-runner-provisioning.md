# Law CI 전용 runner 제공 기록

## 목표와 책임

ContextualWisdomLab/law-ai-agent#1의 품질 실행을 중앙 reusable workflow로 옮긴다.
중앙 issue는 ContextualWisdomLab/.github#2580, GitHub Project #1은 In Progress다.
사용자는 2026-10-05 KST에 중앙 .github 이관과 self-hosted 전환을 명시했다.
제품 source와 source 기록은 private consumer에 유지한다. 중앙 public repo에 원문을 복사하지 않는다.

## 2026-10-05 14:25 KST 실측

- 새 group 11, `CWL law CI`: selected repository는 `ContextualWisdomLab/law-ai-agent` (1404539192) 하나.
- public repository 허용 false, 기존 control/security/signing/GPU/health group 변경 0.
- 새 runner 1134186 `law-ai-agent-ci-isolated-20261005`: Linux X64, label `law-ai-agent-ci`, online, busy false.
- 별도 컨테이너: non-root UID1001, mounts [], cap-drop ALL, no-new-privileges, memory2147483648, nanoCPUs2000000000, pids512.
- host Docker socket, host home/credential, production database volume, published port, host network 사용 0.
- 컨테이너에서 sudo는 no-new-privileges 때문에 거부된다. 이는 helper에 sudo install이 없다는 전제와 일치한다.
- immutable base: `ghcr.io/actions/actions-runner@sha256:e5496277be5d09bc968b3d64911b74e219ac4a3f2edce956a3ecf9271bea1ef4`.
- 로컬 제공 image SHA256 `7eef6dcf639e556ab28c8970978f30b668dc9d21099b8c8d206d3c8d863f7068`.
- `.github/runner-images/law-ai-agent/Dockerfile`의 SHA256 `17596881141c761c5e1a55a81d1b2b76559f6fac3aa8b66e1b705f4990808694`.
- native PostgreSQL 16.15와 pg_config bindir `/usr/lib/postgresql/16/bin`를 직접 확인했다.
- runner 2.337.0과 `Listening for Jobs`를 확인했다. GitHub job 성공 증거는 아니다.
- 이미지 apt 해석 결과는 위 image에 고정돼 있다. Dockerfile의 apt package는 재빌드 시 바뀔 수 있다. registry 배포/이미지 서명은 수행하지 않았다.

## 재현 운영 계약

이미지 build는 provisioning 때만 수행한다. CI job에서 sudo/apt 설치하지 않는다.
전용 image는 DB 바이너리를 제공하고 workflow가 uv0.12.5와 Python matrix를 제공한다.
각 runner는 `--ephemeral --disableupdate --runnergroup 'CWL law CI' --labels law-ai-agent-ci`로 등록한다.
단일 job 종료 후 등록이 해제된다. 다음 matrix job은 새 컨테이너와 새 등록이 필요하다.
등록 token은 승인된 GitHub API로 구하고 stdin으로 config.sh에 전달한다.
`ACTIONS_RUNNER_INPUT_TOKEN`은 등록 child에만 적용하며 stdout·로그·파일·명령 인자에 직접 넣지 않는다.
서버 .credentials 등의 generated credential 파일은 컨테이너 내부에만 존재한다. 컨테이너 제거 시 함께 회수한다.

컨테이너 생성 옵션은 `--restart=no --cap-drop ALL --security-opt no-new-privileges --memory=2g --cpus=2 --pids-limit=512`다.
이미지 writable layer는 job 전용이다. host mount를 추가하거나 host 네트워크로 전환하지 않는다.
같은 명칭의 busy runner는 제거하지 않는다. API의 id/name/group/busy와 컨테이너 owner label을 대조한 뒤 owned idle resource만 회수한다.
초기 detached stdin 전달은 대기 상태로 남았다. 원인은 detached container의 stdin attachment였다.
owned unregistered container를 제거하고 `docker exec -i` 등록 → 별도 `docker exec -d` 실행으로 수리했다.
등록 성공, online, workflow 해석, job 시작, source checkout, 품질 verdict를 별도 확인한다.

## 신뢰 한계와 실제 다음 gate

이 개발용 컨테이너를 VM 수준 격리 또는 hostile workload 보안 인증으로 표현하지 않는다.
network는 GitHub/toolchain 접근을 위해 존재한다. host private network에 대한 별도 egress 방화벽은 이 기록에서 검증하지 않았다.
일반 CI가 signing/security runner나 운영 자격을 공유하지 않도록 repo별 group을 사용한다.
reusable workflow의 runner access와 billing은 caller context다. 중앙 파일 이관은 caller의 계정 admission을 자동 해결하지 않는다.
issue ContextualWisdomLab/law-ai-agent#2의 정책 정상화 증거와 실제 runner-bound job가 있어야 ordinary merge를 승인한다.
공급된 runner만으로 성과를 만들지 않는다. 실제 Linux helper/full-suite 기록과 exact-head GitHub job receipt를 별도로 남긴다.

## 공식 근거 (APA 7)

GitHub. (2026, September 3). *GitHub Actions: Early September 2026 updates*. GitHub Changelog. https://github.blog/changelog/2026-09-03-github-actions-early-september-2026-updates/

GitHub. (n.d.). *Reusing workflow configurations*. GitHub Docs. Retrieved October 5, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations

GitHub. (n.d.). *Reuse workflows*. GitHub Docs. Retrieved October 5, 2026, from https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows
