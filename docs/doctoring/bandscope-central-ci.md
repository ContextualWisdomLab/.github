# BandScope Linux reusable CI — staged producer

작성일: 2026-10-08 KST. 상태: **NO ACTIVATION / staging-not-runnable**.
이 문서는 승인이나 runner attestation이 아니다. 로컬 계약 테스트 성공을 운영 성공으로
바꾸지 않는다. 새 caller, runner 등록/온라인화, ACL 변경, commit/push는 이 변경에 없다.

## 소유권과 근거

중앙 base `7554587c2e3106a388998bcad048a3d7121de25e`, branch
`feat/bandscope-central-ci`에서 다음 세 파일만 추가한다.

- `.github/workflows/bandscope-ci.yml`
- `tests/test_bandscope_ci_contract.py`
- `docs/doctoring/bandscope-central-ci.md`

독립 source는 BandScope의 `.github/workflows/ci.yml`이다. 읽은 checkout HEAD는
`a00da6afa10b1cc5147af4031cafebb393b8cdeb`, workflow Git blob은
`6e743c2ff666372ba88410b29105c1612f422dad`, SHA-256은
`64211c7d5a9ff4efa1567e0169cef5e7eadb8fbe6e13fd34f3f2748f594caa76`이다.
원본 `lock-validation`, `verify` 두 Linux job만 대상으로 한다. 이 producer는 전체
16개 job의 이전 완료 증거가 아니며 나머지 Linux, Windows/macOS gate를 대체하지 않는다.
중앙 기존 workflow/schema/helper, PR2565 소유 migration 파일과 pin은 변경하지 않는다.

읽은 중앙 규칙: `AGENTS.md`, `docs/CWL-MASTER-CONTEXT.md`,
`docs/product-goal-directive.md`, `SECURITY.md`, dependency-review workflow/contract와
`docs/doctoring/dependency-review-fail-closed.md`. 마지막 문서의 의도와 현재 workflow의
403/404 skip 구현은 서로 다르다. 이 작업은 그 기존 차이를 수정하거나 승인하지 않는다.
BandScope의 dependency 및 cross-platform build 정책도 적용한다.

## 고정 계약

`workflow_call`만 선언한다. 필수 문자열 input `gate`의 유효 값은 정확히
`lock-validation|verify`이며 default, command/path/runner/ref input은 없다.
알 수 없는 값이나 빈 값은 실제 admission shell에서 실패한다. gate 값을 job-level
`if`에 넣어 unknown 호출을 성공처럼 skip시키지 않는다.

- 저장소는 대소문자까지 정확히 `ContextualWisdomLab/bandscope`.
- push는 `refs/heads/main`, `refs/heads/develop`만 허용한다.
- PR은 head/base repository가 모두 같은 저장소이고 base가 `main|develop`일 때만 허용한다.
  admission은 양의 PR 번호와 `refs/pull/<number>/merge`도 검사한다.
- 수동 호출은 필요하지 않아 허용하지 않는다. `pull_request_target`, fork, schedule,
  dispatch, feature push, tag는 거부한다.
- job-level context filter와 checkout 이전 env-driven shell을 함께 둔다.
  context/input 값은 shell 문자열로 삽입하지 않고 env로만 운반하며 재해석하지 않는다.
- checkout repository/path는 고정이고 ref는 현재 caller의 `${{ github.sha }}`이다.
  PR head SHA로 바꾸지 않는다. `persist-credentials: false`, `clean: true`를 사용한다.
- 기본 shell working-directory는 `bandscope-source`; admission만 아직 checkout이 없는
  `${{ github.workspace }}`에서 실행한다.
- PR concurrency는 저장소/PR 번호/gate별로 이전 실행을 coalesce한다. SHA를 key에
  넣지 않는다. non-PR은 run ID로 분리한다. 미래 caller는 producer와 같은 concurrency
  group을 쓰지 않아야 한다.[1]

### 명령 및 버전 보존

Node `22.22.3`, npm `10.9.9`, uv `0.8.6`, maturin `1.9.6`과 source의 세 action
full-SHA pin을 그대로 사용한다. 새로운 의존성이나 lock 변경은 없다.

공통: `corepack enable npm`, exact npm version 확인, `npm run check:npm-runtime`.

`lock-validation`: `npm ci --ignore-scripts --no-audit --no-fund`,
`git diff --exit-code -- package.json package-lock.json`.

`verify`: `npm ci`, `uv sync --project services/analysis-engine --group dev --frozen`,
`rustup toolchain install stable --profile minimal`, numeric maturin release build/install,
`./scripts/harness/quickcheck.sh`를 원래 순서로 실행한다. 원본의 mutable Rust `stable`은
이 단계의 parity 범위에서 보존했으며 immutable Rust toolchain 증거라고 주장하지 않는다.

numeric wheel output만 stale reuse 방지를 위해 변경한다. `RUNNER_TEMP` 아래 `mktemp -d`로
현재 step 소유 디렉터리를 만들고 정확히 한 개의 regular non-symlink wheel만 설치한다.
`services/analysis-engine/rust/dist/*.whl`이나 다른 job/sibling output을 검색하지 않는다.
EXIT trap은 그 새 디렉터리만 제거한다. build/install 실패 exit는 보존한다.

## 활성화 전 필수 조건

**NO ACTIVATION**: 전달된 candidate group `CWL CI isolated`는 아직 BandScope용으로
admitted되지 않았고 offline이라는 작업 전제다. live API 관측이나 승인이라고 주장하지
않는다. group과 labels는 고정이다: `self-hosted`, `Linux`, `X64`,
`cwlab-ci-isolated`, `bandscope-ci`. `Default`, control group, broad label,
GitHub-hosted fallback은 금지한다.

1. `ContextualWisdomLab/linux-cluster-ops#326` 운영 담당자와
   `ContextualWisdomLab/quarantine-sandbox-runtime#136` attestation 담당자가
   public BandScope hostile-source 실행을 위한 격리/폐기/네트워크/credential
   경계와 runner canary를 입증해야 한다. 해당 Issue가 존재한다는 사실은 운영
   승인이나 격리 증거가 아니다. 승인 artifact가 없으면 활성화하지 않는다.
   이 문서는 승인 실행파일, receipt path, 임의의 guard 명령을 만들지 않는다.
2. **actual caller ACL**을 확인한다. reusable workflow는 caller context의 runner만
   사용하며 중앙 `.github`의 runner 접근권을 BandScope로 옮겨 주지 않는다.[1]
   runner group의 selected repository/workflow 접근 제약, public repository 접근 정책,
   정확한 SHA-pinned producer 경로와 실제 caller ref를 확인해야 한다.[2]
3. supported pre-lease guard가 증거와 함께 확정되어야 한다. 현재 이 파일에는 검증된
   attestation guard가 없다. 따라서 **staging-not-runnable** 규칙으로 caller 추가와
   group admission을 금지한다. 문서 규칙은 기술적 enforcement가 아니다.
   누군가 ACL/caller를 별도로 바꾸면 producer의 shell만으로 lease를 막을 수 없다.
4. runner에서 실제 Node/Corepack/npm, uv/Python, rustup/compiler/linker, Linux build
   시스템 의존성, 권한/디스크/TMPDIR, checkout clean 및 teardown을 canary로 확인한다.
   tool installation 실패는 환경 수용 실패로 기록하며 fake success나 hosted fallback을 쓰지 않는다.
5. 독립 exact-byte review 후 별도 caller PR에서 두 job을 각각 고정 gate로 호출한다.
   `verify` caller는 기존처럼 `needs: lock-validation`을 보존해야 한다. producer에 이
   cross-invocation dependency가 자동 생기는 것은 아니다. caller는 full commit SHA에 pin하고
   `contents: read`를 명시하며 **secrets: inherit 금지** 및 별도 secrets 전달 금지를 적용한다.

현재 trigger는 `workflow_call`뿐이고 caller 추가가 없다. producer를 중앙에 merge하는
것만으로 workflow가 실행되지 않는다. 이는 미래 caller/ACL 변경의 안전성 증명이 아니다.

## Check name 및 기존 보안 gate

원래 두 check는 `gate / ci / npm-lock-validation`, `ci / build-and-test`다.
재사용 호출 뒤의 prefix와 job `linux`가 실제 check 이름을 바꿀 수 있다. **live-canary**의
실제 check-run 이름/결과, caller job ID/name, source SHA와 producer SHA를 수집하여
`main`과 `develop`의 ruleset mapping을 별도 승인으로 이행한다. 문서상의 예상 이름이나
**synthetic success** status를 만들어 required check를 만족시키면 안 된다. skipped/queued
job도 실제 gate 성공으로 취급하지 않는다. canary 전 기존 required check를 제거하지 않는다.

Windows/macOS 네 native architecture는 그대로 필수다: `gate / build / windows`,
`gate / build / macos`를 낮추지 않는다. Security Scan의 OSV, diff dependency review,
repo-wide Trivy 결과 및 CodeQL, audit, secret scan, Dependabot baseline도 그대로 남는다.
원본 SBOM workflow와 artifact retention은 이 producer 범위 밖이다. baseline 형식
`CycloneDX JSON`, `supply-chain/supplemental-component-inventory.json` 및 release checksum
연결도 대체하지 않는다. 이 변경은 live ruleset/Dependabot/SBOM 보존 상태를 재검증하지
않았으며 공급망 전체 enforced 판정을 내리지 않는다.

## Security Notes

- **Hostile PR / pre-lease:** same-repository PR도 안전하지 않다. `npm ci` lifecycle,
  Python/native build hooks, Rust build와 quickcheck는 공격자가 바꾼 코드를 실행한다.
  read-only token과 SHA pin만으로 host/network 격리가 생기지 않는다. public repository
  self-hosted runner의 악성 실행 위험을 먼저 통제해야 한다.[3]
- **in-job boundary:** 첫 shell은 checkout 전에 잘못된 context와 gate를 거부하지만 이미
  runner lease 이후다. job-level 조건도 runner attestation, authorized workflow ACL,
  ephemeral single-job host 또는 pre-lease admission 증거를 대신하지 않는다.
- **Forbidden fork / secret boundary:** fork, PR target 및 dispatch는 지원하지 않는다.
  producer는 secrets를 선언/참조하지 않고 write/OIDC/package/deployment 권한을 요청하지
  않는다. GitHub의 자동 token 자체가 사라지는 것은 아니다.[1] checkout 및 action
  runtime의 자동 read-token 접근은 남으며 run step 전역 env에는 token을 넣지 않는다. 미래 caller에서
  secrets inherit를 금지하고 runner 자체에 장기 credential, production mount, control
  socket이나 공유 신뢰 캐시가 없다는 것을 별도로 입증해야 한다.
- **Cleanup:** checkout clean은 OS teardown이 아니다. numeric output의 EXIT cleanup만
  로컬 테스트했다. hard kill/cancellation 시 trap 실행을 보장하지 않는다. stale venv,
  npm/Rust cache, hook 오염, descendant/sibling 작업 공간에 대한 전체 정리는 승인된
  ephemeral runner lifecycle로 처리해야 하며 이 producer가 broad `rm`을 실행하지 않는다.
- **Artifacts / privacy:** 새로운 artifact upload/download, SBOM publication, 장기 wheel
  보존을 추가하지 않는다. numeric wheel은 현재 step만 소비하고 제거한다. admission
  오류는 고정 메시지만 출력한다. 임의 repository/ref/input, 환경 전체, secret, 모델
  응답을 로그에 출력하지 않는다. 일반 build/test 로그는 untrusted output이며 후속
  privileged consumer에 신뢰 데이터로 반입하지 않는다.
- **Name implications / tests:** YAML의 실제 `run` bytes를 bash로 실행해 fork/wrong repo,
  injection, empty/unknown gate, 보호 ref 및 PR merge identity를 검사한다. synthetic tool
  doubles는 새 wheel 디렉터리/한 개 output/cleanup/실패 전파만 검사하며 실제 wheel,
  Rust 성능, runner canary 또는 attestation이 아니다.

## 로컬 검증 기록과 남은 수용

새 test에서 absent producer로 RED(`1 failed`, exit 1)를 먼저 확인했다. call-only 최소
구현 뒤 GREEN(`1 passed`, exit 0), admission slice RED(`37 failed, 1 passed`, exit 1)
뒤 GREEN(`38 passed`, exit 0), command/numeric slice RED(`6 failed, 38 passed`, exit 1)
뒤 GREEN(`44 passed`, exit 0)를 확인했다. staging 문서 부재도 별도 RED(exit 1)로 확인했다.
raw 로그는 승인된 scratch의 `bandscope-ci-red1.log`부터 `bandscope-ci-red4.log` 및
`bandscope-ci-green3.log`에 남긴다.

초기 actionlint `1.7.12`는 사용자 정의 두 runner label의 catalog 부재로 exit 1이었다.
원래 YAML/label을 바꾸지 않고 scratch-only `bandscope-ci-actionlint.yaml`에 두 label을
명시한 뒤 actionlint가 exit 0이었다. 이 config는 parser의 label 선언이며 runner 존재나
admission 증거가 아니다. 새 package 설치 없이 현행 Python/pytest/PyYAML과 설치된
lint 도구만 사용했다. 초기 실패 로그도 그대로 보존한다.

관련 기존 계약을 포함한 로컬 실행은 **185 passed**(새 BandScope 45개 포함, exit 0)였다.
`GITHUB_ACTIONS=true`로 같은 관련 계약을 실행한 결과도 **185 passed**(exit 0)였다.
실제 로컬 interpreter는 Python `3.14.5`, pytest `9.0.3`, PyYAML `6.0.3`였다.
전체 중앙 suite는 **5204 passed, 4 skipped, 6 failed, 40 subtests passed**(exit 1)였다.
실패 6개를 exact base archive `7554587c2e3106a388998bcad048a3d7121de25e`의 scratch
복사에서 같은 home-contained TMPDIR 조건으로 재실행하여 **6 failed**(exit 1)를 확인했다.
`test_audit_org_codeql_coverage.py` 1개(예상 exit 0과 실제 exit 1 차이)와
`test_sandboxed_web_e2e.py` 5개(host-home path 거부/기대값 차이)다. baseline에서도
동일하게 실패했으므로 이 patch가 유발한 회귀로 보고하지 않지만 전체 suite GREEN도
아니다. 기존 파일은 고치지 않았다. 실제 XML과 raw log는 `bandscope-ci-related.*`,
`bandscope-ci-full.*`, `bandscope-ci-base-failures.*`로 scratch에 남는다.

인용 provenance 정정: 초기 작성자와 부모가 실제 조회 전에 작성한 조회 완료
주장은 근거로 사용하지 않는다. 기존 초안과 로그는 scratch에 보존했다.
2026-10-08 부모의 실제 `web.run` 응답으로 Sources의 GitHub 공식 문서 세 개를
확인했다. 호출자의 runner 접근권, 권한 비확대와 public self-hosted 위험을
대조했다. 이 후속 조회는 이전 작성 시점의 증거를 소급하지 않는다.

세 파일의 최종 hash는 별도 실제 실행 handoff로 제공한다.
전체 BandScope dependency installation, quickcheck, 실제 maturin/Rust wheel, GitHub
caller 실행, runner canary, ACL, #326/#136 approval, native four-architecture build,
required check mapping과 protected integration은 **NOT RUN / 미수용**이다.

## References

GitHub. (n.d.). *Reusing workflow configurations*. GitHub Docs. Retrieved October 8, 2026.[1]

GitHub. (n.d.). *Managing access to self-hosted runners using groups*. GitHub Docs.
Retrieved October 8, 2026.[2]

GitHub. (n.d.). *Secure use reference*. GitHub Docs. Retrieved October 8, 2026.[3]

## Sources

[1] https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations
[2] https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access
[3] https://docs.github.com/en/actions/reference/security/secure-use
