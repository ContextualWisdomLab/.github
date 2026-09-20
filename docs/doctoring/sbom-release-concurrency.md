# SBOM 릴리스 직렬화 계약

`sbom-generation.yml`은 보호 브랜치 push의 dependency snapshot과
`release: published`의 SPDX·CycloneDX asset 게시를 한 job에서 수행한다.
두 이벤트의 부작용과 취소 정책이 달라 concurrency도 두 단계로 나눈다.

## 확인한 기존 구현

- 저장소에는 release ID, tag, commit을 함께 검증하는 helper가 없었다.
  `repository-metadata-reconcile.yml`과 `sast-semgrep.yml`의 기존 검사는
  checkout 결과와 기대 SHA만 비교하므로 release의 현재 tag를 확인하지 않는다.
- pinned `anchore/sbom-action@e22c3899`는 release payload의 release ID를
  대상으로 같은 이름의 asset을 삭제한 뒤 다시 올린다. 같은 release를
  병렬 실행하면 이 두 호출이 서로 엇갈릴 수 있다.
- pinned `publish-sbom`은 먼저 현재 workflow의 artifact를 찾지만, 이름에
  맞는 artifact가 없으면 release의 `target_commitish`에서 최신 workflow
  run을 찾아 그 run의 artifact로 fallback한다. 하나만 맞아도 그 하나를
  게시하고, 하나도 없으면 warning만 남기고 성공 반환한다. 이 동작은 현재
  run의 두 산출물이 모두 존재한다는 계약과 맞지 않아 사용하지 않는다.

## 선택한 경계

- workflow-level `release.id` 그룹과 `queue: max`가 같은 release의 실행을
  직렬화한다. GitHub의 native queue 상한은 100이며 이를 넘은 실행은
  보존되지 않는다.
- push workflow admission은 run별로 분리하고, 기존 job-level repository/ref
  그룹에서만 `cancel-in-progress: true`를 적용한다.
- release 생성 단계는 현재 checkout에 두 SBOM 파일을 만들고 dependency
  snapshot을 제출하지 않는다. 게시 직전 live release ID·tag와 tag가
  가리키는 commit을 다시 확인한다. 이어 두 로컬 파일이 비어 있지 않은
  일반 파일인지와 SPDX·CycloneDX의 최소 JSON 표식을 확인한 뒤 기존
  `gh release upload --clobber`로 두 파일을 한 호출에서 게시한다. 다른 run의
  artifact를 조회하지 않으며 `actions: read` 권한도 추가하지 않는다.
- tag는 `git check-ref-format refs/tags/...`로 Git ref 문법과 제어문자를
  먼저 거른다. 업로드 명령은 옵션 뒤 `--`를 두어 `-`로 시작하는 tag도
  positional 인자로 고정한다. 검증을 통과한 tag는 성공 로그에 출력하지
  않지만, 이후 GitHub CLI가 반환하는 외부 오류 문구까지 숨긴다는 계약은
  아니다.
- GitHub commits API는 lightweight tag와 annotated tag를 모두 commit으로
  해석하므로 별도 tag-peeling 구현은 두지 않는다.

## 남은 경계

- mutable release에서는 검증 직후 외부 주체가 tag를 다시 바꿀 수 있다.
  live guard와 다음 upload 호출은 원자적이지 않으며, guard 뒤 release나
  asset이 삭제될 수도 있다. 파일 검사와 upload 사이의 로컬 변경도 하나의
  원자 연산이 아니다. 따라서 exact-head 원자성이나 게시 성공을 guard만으로
  보장한다고 주장하지 않는다. immutable release에서는 tag 변경 경로가
  닫히지만, 실제 payload의 `immutable` 값은 증거로만 기록한다.
- 보호 브랜치 push의 snapshot은 계속 같은 correlator를 사용한다. 취소가
  늦거나 이미 제출 단계에 들어간 구형 실행이 최신 실행보다 나중에 API에
  도착하면 GitHub가 구형 snapshot을 latest로 선택할 가능성은 이 변경에서
  해결하지 않는다.
- `queue: max`는 2026-05-07 추가된 GitHub 공식 문법이다. 현재 고정
  actionlint 빌드는 그 이전인 2026-04-19 소스라 이 키를 모른다. upstream
  actionlint의 지원 PR도 아직 열려 있으므로 해당 lint 실패를 숨기거나
  통과로 바꾸지 않는다.

## 근거

- [GitHub Actions concurrency queue](https://docs.github.com/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
- [GitHub release 수정 API](https://docs.github.com/rest/releases/releases#update-a-release)
- [GitHub commit 조회 API](https://docs.github.com/rest/commits/commits#get-a-commit)
- [GitHub dependency submission API](https://docs.github.com/rest/dependency-graph/dependency-submission)
- [pinned Anchore release 게시 구현](https://github.com/anchore/sbom-action/blob/e22c389904149dbc22b58101806040fa8d37a610/src/github/SyftGithubAction.ts#L484-L592)
- [pinned Anchore publisher fallback](https://github.com/anchore/sbom-action/blob/e22c389904149dbc22b58101806040fa8d37a610/src/github/SyftGithubAction.ts#L484-L600)
- [GitHub CLI release upload](https://cli.github.com/manual/gh_release_upload)
- [actionlint queue 지원 추적](https://github.com/rhysd/actionlint/pull/654)
