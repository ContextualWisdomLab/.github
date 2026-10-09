# 중앙 self-hosted 검증·AI 리뷰 목표

기준: 2026-10-09 사용자 직접 지시. 상태: 구현·운영 담당 연결, 원인 조사 진행 중.

## 목표

k-csap-skills의 코드 검증을 중앙 ContextualWisdomLab/.github에서 self-hosted로 실행한다.
Noema/OpenCode는 개인 LiteLLM gateway의 literal `auto`로 실질 독립 리뷰를 수행하고,
결함이 없을 때만 exact-head에 조건부 APPROVED를 게시한다. 작성자 본인 승인을 만들지 않는다.
Hosted 전용 절차는 대체 가능 여부를 확인하고 담당자가 중지하며, 미실행 증거는 NOT_RUN으로 남긴다.

## 담당

- salmon: 별도 중앙 worktree의 k-csap-quality.yml 및 계약 테스트. 현재 구현·독립 리뷰 진행은 peer 화면으로 관찰했다. 통과/게시/실행은 미확인.
- oscar: 기존 consumer ci.yml caller와 repo runner 운영. 중앙 immutable SHA 확인 후 연결.
- Remora / 중앙 Issue #2560: 기존 LiteLLM service-key·relay·Noema/OpenCode auto/App wiring. 중복 키 발급 금지.
- anchovy: PR #23/#29 exact-head 코드 검증 소비, runner/auto route 원인 조사와 담당자 연결. 위 소유 파일에 경쟁 writer를 만들지 않는다.

## 직접 확인한 운영 증거

- 중앙 main 7554587c2e3106a388998bcad048a3d7121de25e.
- LLM_GATEWAY_API_KEY Secret metadata updated 2026-10-09T05:07:41Z. 값은 읽지 않았다.
- LLM_GATEWAY_MODEL variable auto updated 2026-10-08T09:34:52Z.
- protected main의 실제 Noema/OpenCode 호출은 orchestrator/free 고정. 변수 존재만으로 auto 전환 완료 아님.
- 중앙 OpenCode group5 runner cwlab-s1-04는 API offline. systemd active와 불일치. RCA worker 배치 deleg_60b4cef4.
- k-csap repo runner k-csap-isolated-linux id2는 API online/idle.
- 기존 s1 k-csap-isolated-runner 컨테이너는 2CPU/2GiB/PID512, user1001, cap-dropALL, no-new-privileges, k-csap-ci network, mounts 없음. Docker socket 없음. 컨테이너의 uv는 미설치.
- org isolated group13에는 k-csap ACL이 없고 조회 runner는 offline. privileged control runner로 대체하지 않았다.

## 단계와 수용 조건

1. 담당자 소유권·경로·current hash 확인. 기존 key/relay/runner 재사용.
2. 중앙 reusable 계약: fixed caller/event/head 사전검사, secrets 없는 test lane, locked uv3.11/Ruff/fullpytest/scaffold/diff, 전용 격리 runner, mutable main 없는 소비 SHA.
3. runner API online뿐 아니라 실제 job runner identity/steps/logs/cleanup 확인.
4. 중앙 #2560 구현에서 TLS gateway·literal auto·키 model scope/budget/private retention을 확인. API/모델 실패를 APPROVE로 변경하지 않는다.
5. 실제 PR #23/#29 exact base/head에 author-distinct App review 게시를 확인.
6. oscar가 consumer caller를 pin하고 Hosted-only 경로를 중지. 필요한 미지원 증거는 미실행으로 남긴다.
7. 기존 통합 정책 및 검증 증거에 따라 병합. 데이터 권리·Stage 승인·설치는 별도다.

## 현재 코드 상태

PR #23 head ff32a0dbff9c1eb144a401f72f06a4aad31d71b1 OPEN.
PR #29 head66923f12e266e193d7d8f17466780fa2f881c784 OPEN, base PR23.
스냅샷 수리는 독립 보안·계약 리뷰 PASS와 Python3.11/3.14 각각202tests가 있다.
이 결과는 self-hosted actual job, auto inference, GitHub App 승인, merge, release를 뜻하지 않는다.

## 2026-10-09 조사 후 갱신

- runner RCA 보고서를 읽었다. 부모가 기존 service unit과 /proc의 monitor 구성 여부를 재확인했다.
  cwlab-s1-04는 QEMU active이지만 guest SSH 배너가 없으며, 구성된 QMP/monitor가 없다.
  serial I/O 7건은 모두 fd0 floppy이고 virtio 디스크 손상의 증거가 아니다. 원인은 미확정이다.
- 기존 auto writer는 dot-github/litellm-review-auto-20261008과 PR #2607로 좁혀졌다.
  PR #2607 OPEN/head0975955d1bae39d634cc52e4e776c1c95b4f14d3를 부모 GraphQL로 확인했다.
  미추적 route helper는 아직 호출 경로에 연결되지 않았다. 별도 키 발급 대신 #2560에 exact-hunk 통합을 요청했다.
- gh auth status의 invalid 표시는 전체 API 불가 증거가 아니다. 같은 시점 GraphQL viewer/PR 조회와
  일부 REST runner endpoint는 성공하고 다른 REST endpoint는 rate-limit403이다. endpoint별 증거를 구분한다.
- 실제 PR #23/#29 formal review는 0이다. 독립 로컬 리뷰 PASS를 App 승인으로 승격하지 않는다.
- salmon의 cleanup 경쟁 결함 수리가 진행 중이라는 peer 화면을 관찰했다. 아직 중앙 품질 완료로 세지 않는다.

## 미실행·금지

키 재발급/Secret 덮어쓰기, runner 이동/ACL 완화, 다른 worktree 수정,
작성자 self-approve, 보호 gate 우회, 원문·민감 증적 업로드, 대체없는 가짜 CI success 없음.
실제 auto 추론·formal approval·central activation·Hosted shutdown·merge·배포는 아직 미확인/미실행이다.
