# Health Evidence 중앙 self-hosted 품질 검사

기준: 2026-10-08. 사용자 요청은 실행 가능한 검사를 중앙 `.github`에 모으고 GitHub-hosted 필수 기능을 끄는 것이다. 이 단위는 private `ContextualWisdomLab/health-evidence`의 기존 품질 검사 세 개를 중앙 reusable workflow로 이전한다. 다른 제품의 scanner 또는 runner 소유권은 변경하지 않는다.

## 계약과 소유권

- Producer: `.github/workflows/health-quality.yml`, `workflow_call` 전용. 입력은 고정 gate enum `documentation|rust|pwa`뿐이다. caller가 임의 shell, runner, repository, ref를 주입할 수 없다.
- Consumer: Health `.github/workflows/quality.yml`은 기존 push/pull_request/workflow_dispatch와 concurrency를 유지하고 세 job에서 중앙 파일의 실제 reviewed full SHA를 호출한다. 중앙 commit이 존재하기 전 caller를 활성화하지 않는다.
- 실행 그룹: `CWL health CI`, labels `self-hosted, Linux, X64, cwlab`. public 저장소·외부 fork·pull_request_target 및 알 수 없는 gate는 checkout 전에 명시적으로 실패한다. hosted fallback은 없다.
- 중앙 repository의 코드를 이 그룹에서 임의 실행하지 않는다. reusable job은 허용된 private Health caller의 이벤트 문맥과 SHA를 사용한다. 그룹10은 Health private repository만 허용한다. 중앙 public repository에 runner 접근을 추가하지 않는다.
- token 권한은 contents:read. checkout persist-credentials=false. secrets inherit, 운영 설정·건강 자료·Docker socket·LAN 권한은 추가하지 않는다.
- workflow call 전환 후 check 표시 이름은 호출 job과 reusable job의 조합으로 바뀔 수 있다. 현재 Health branchProtectionRules 및 inherited rulesets GraphQL 조회는 빈 목록이다. publication 후 실제 check 이름을 다시 확인하고 보호 규칙을 완화하지 않는다.

## 보존한 gate

| Gate | 동일 실행 계약 |
|---|---|
| documentation | verify-docs.py, PyYAML6.0.3을 쓰는 Actions policy unittest |
| rust | Rust1.98.0, fmt --all --check, test --workspace --locked, clippy --workspace --locked --all-targets -- -D warnings |
| pwa | Node24.21.0, model.test.mjs와 client.test.mjs의 기존 node --test |

PyYAML entry는 기존 `requirements-bandit-ci-hashes.txt`의 생성된6.0.3 hash block을 재사용한다. 별도 임시 venv에서 --require-hashes와 --only-binary로 설치한다. lock파일은 수정하지 않는다. Cargo build jobs는1이다.

기존 CI는 PostgreSQL ignored 시험, 물리 GPU 및 Chromium/Safari를 실행하지 않는다. 이 이관은 해당 미실행 gate를 통과라고 주장하지 않는다. 별도 product acceptance는 필요한 실제 환경에서 유지한다. 이 저장소의 기존3job은 모두 self-hosted이므로 이 파일에 끌 hosted job은0개다. 다른 중앙 workflow의 hosted-only 기능 inventory·중지 여부는 해당 owner가 별도 수행한다.

## 2026-10-10 admission 수리 후보

- PR2600 기준 head는 `076a71caa3947b1ea4e1af099ea06ec3f3ea7eee`다. 현재 두 소스 파일의 미커밋 수리는 원격 실행이나 병합 완료가 아니다.
- 실제 기존 shell에서 missing PR head SHA, closed PR, `refs/pull/0/merge`를 성공으로 수용하는 RED를 확인했다. 수리 후 같은 저장소의 open PR, 소문자 40자리 head/event SHA와 양수 번호 merge ref를 모두 검사한다. head SHA로 merge 후보를 대신하지 않는다.
- push/manual은 유효한 branch ref와 event SHA를 검사한다. 모든 shell 검사가 끝난 뒤에만 `expected_sha`와 `admitted=true`를 출력하며 checkout과 실제 HEAD assertion이 같은 출력에 결합된다.
- runner 배정 전 job 조건은 고정 private repository, gate, 이벤트와 PR 상태·번호·동일 저장소·번호에 맞는 merge ref를 확인한다. 이 조건의 skip은 실행된 quality 증거가 아니다. shell의 엄격한 SHA/ref 검사와 구분한다.
- 부모의 추가 job guard RED는 기존 prefix/suffix 조건이 정확한 PR 번호 일치를 검사하지 않음을 보여준다. 수리 후 focused **10 tests / 62 subtests passed**, Ruff E9/F/I 및 format, diff-check exit0이다. actionlint 기본 실행은 기존 `cwlab` vocabulary 부재로 exit1이며, 해당 label만 선언한 scratch config 실행은 exit0이다. canonical 공유 vocabulary 수용으로 확대하지 않는다.
- full repository gate, 현재 head의 self-hosted execution과 qualifying App review는 미완료다. 기존 persistent `health-source` checkout 경계는 이 admission 수리로 해결되지 않는다. startup_failure/account admission도 해결됐다고 주장하지 않는다.
- 증거: `/Users/seonghobae/.hermes/health-evidence-runs/20261010-2220-central-resume/producer-admission/`. 아래 최초 구현 이력은 역사적 결과로 보존한다.

## TDD와 검증

- 새 계약 시험을 먼저 실행: 중앙 producer 파일 없음으로3 errors, exit1. 기능 부재 RED다.
- producer 구현 후 최초3 tests passed. 추가 TDD로 policy venv 초기화와 admission 성공 후 cleanup만 허용하도록 수리했다. 최종6 tests passed. 실제 admission Bash를8개 허용/거부 문맥에서 실행했고, 합성 interpreter로 policy shell을 두 번 실행하여 오래된 파일 삭제·다른 파일 보존·시험 실패 exit7 전파를 확인했다. 실제 hash-locked PyYAML 설치와 Health baseline 정책2개도 별도 exit0이다. 최초 kernel의 yaml import 실패는 harness 실패로 보존하고 실제 terminal Python3.14.5로 검증했다.
- 최초 actionlint는 custom cwlab label 미등록으로 exit1. product label을 바꾸지 않고 private verifier config에서 실제 label을 선언한 뒤 actionlint exit0.
- actionlint 및 정적/로컬 계약은 원격 runner 실행 성공이 아니다. 그룹10 runner1134185가 online/idle이라는 조회도 CI 성공이 아니다.
- 아직 독립 검토·발행·정상 병합·Health exact-head run 증거는 필요하다. 기존 startup_failure jobs0와 billing/API-quota 관찰은 구분한다. runner selector 이동으로 계정 admission을 고쳤다고 주장하지 않는다.

## 출처

GitHub Docs. Reuse workflows. https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows (2026-10-08 확인). 외부 workflow는 job-level uses와 full commit SHA로 참조하며 caller 문맥에서 실행한다.

GitHub Docs. Using self-hosted runners in a workflow. https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow (2026-10-08 확인). group와 labels를 함께 적용한다.

독립 검토 전 개인 건강 자료나 설정 secret은 이 문서·public 중앙 commit에 포함하지 않는다. publication은 검토된 producer만 먼저, consumer는 실제 producer SHA로 이후 연결한다.
