# Procurement central self-hosted CI

상태: 중앙 PR #2620 소스 게시·로컬 검증·독립 소스 검토 완료 / ACTIVATION HOLD.

## 결과

`ContextualWisdomLab/procurement-workbench`의 비밀 없는 품질 검사를 중앙 `ContextualWisdomLab/.github` reusable workflow로 옮긴다. 모든 제품 코드 실행은 승인된 전용 self-hosted Linux x64 runner에서만 한다. GitHub-hosted fallback은 두지 않는다.

현재 제품 품질 의미를 유지한다.

- Python 3.12와 3.14, `fail-fast: false`, `max-parallel: 1`.
- `uv lock --check`.
- `uv sync --frozen --group dev`.
- 전체 `uv run pytest -q`.
- `uv run ruff check .`.
- `node --check procurement/ui.js`.

## 근거

- 중앙 base: `7554587c2e3106a388998bcad048a3d7121de25e`.
- 제품 workflow: `procurement-workbench/.github/workflows/ci.yml`.
- 제품 [ContextualWisdomLab/procurement-workbench#4](https://github.com/ContextualWisdomLab/procurement-workbench/pull/4)가 caller 파일을 소유한다. 중앙 workflow가 검토·게시되고 runner가 실제 준비되기 전에는 제품 caller를 바꾸지 않는다.
- 중앙 전역 runner 정책은 PR #2565가 소유한다. 이 lane은 그 파일을 수정하지 않는다.
- AI review와 personal LiteLLM `auto` routing은 중앙 issue #2560 소유다. 이 lane은 키를 발급하거나 review workflow를 변경하지 않는다.

## 실패 상태

다음 상태는 성공이 아니다.

- runner group 또는 repository access 미설정.
- runner offline, missing 또는 capability 부족.
- admission 거절.
- matrix leg missing, skipped, cancelled 또는 failed.
- hosted-only producer를 끈 뒤 해당 증거가 unavailable인 상태.
- 로컬 테스트·actionlint만 통과한 상태.
- Noema/OpenCode check가 skipped인 상태.
- GitHub App의 실제 조건부 `APPROVED`가 없는 상태.

## 소유 파일

- `.github/workflows/procurement-workbench-ci.yml`
- `tests/test_procurement_workbench_ci.py`
- `tests/test_procurement_workbench_ci_lifecycle.py`
- `docs/doctoring/procurement-workbench-central-ci.md`
- `docs/doctoring/procurement-workbench-github-contexts.md`
- 이 `GOAL.md`

그 밖의 중앙 workflow, runner policy, actionlint shared config, 제품 caller, branch protection, ruleset, secret, variable, runner ACL은 변경하지 않는다.

## 완료 조건

1. 중앙 workflow와 계약 테스트가 TDD 및 로컬 검증을 통과한다.
2. 독립 리뷰가 정확한 파일 hash에 대해 `APPROVE`한다.
3. 중앙 workflow가 immutable commit SHA로 게시된다.
4. runner operator가 procurement repository access와 전용 격리 runner를 준비하고 canary로 group/name/labels/cleanup을 증명한다.
5. 제품 owner가 thin caller를 immutable 중앙 SHA로 전환한다.
6. 각 Python matrix leg와 모든 품질 명령이 같은 제품 head에서 실제 self-hosted runner로 통과한다.
7. 보호 owner가 실제 check name을 mapping하고 hosted-only 절차를 비활성화한다. 제거된 증거는 unavailable로 남고 병합을 우회하지 않는다.
8. 별도 중앙 #2560 lane에서 `https://litellm.poinnetworks.net`의 제한된 service key, literal model `auto`, 실제 inference, 저자와 다른 Noema/OpenCode GitHub App review와 조건부 `APPROVED`를 입증한다.

## 다음 실행 조각

현재 소스는 게시·검토됐다. 다음 단계는 runner 격리 증거, 실제 중앙 품질 실행, 기존 #2560 경로의 literal `auto`와 정식 App 판정을 확보하는 것이다. 제품 caller 활성화와 정상 병합은 그 조건을 충족한 뒤 진행한다. 완료한 소스 suite를 반복하는 것으로 운영 증거를 대신하지 않는다.
