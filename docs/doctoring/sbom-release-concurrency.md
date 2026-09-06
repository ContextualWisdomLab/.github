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
- 같은 action의 `package-lock.json`은 `@actions/artifact` 6.2.1을 고정한다.
  `listArtifacts()`와 `getArtifact()`는 별도 `findBy`가 없으면
  `ACTIONS_RUNTIME_TOKEN`에서 현재 workflow-run·job-run backend ID를 꺼내
  내부 artifact API에 보낸다. 따라서 이름 정규식은 현재 job의 artifact
  안에서만 SPDX와 CycloneDX를 고르며 다른 run의 artifact를 섞지 않는다.
  이 경로는 별도 `actions: read` 권한을 요구하지 않아 기존 권한을 늘리지
  않았다.

## 선택한 경계

- workflow-level `release.id` 그룹과 `queue: max`가 같은 release의 실행을
  직렬화한다. GitHub의 native queue 상한은 100이며 이를 넘은 실행은
  보존되지 않는다.
- push workflow admission은 run별로 분리하고, 기존 job-level repository/ref
  그룹에서만 `cancel-in-progress: true`를 적용한다.
- release 생성 단계는 현재 run의 artifact만 만들고 dependency snapshot을
  제출하지 않는다. 게시 직전 live release ID·tag와 tag가 가리키는 commit을
  다시 확인한 뒤 pinned `publish-sbom` 경로를 한 번 호출한다.
- GitHub commits API는 lightweight tag와 annotated tag를 모두 commit으로
  해석하므로 별도 tag-peeling 구현은 두지 않는다.

## 남은 경계

- mutable release에서는 검증 직후 외부 주체가 tag를 다시 바꿀 수 있다.
  live guard와 다음 publish 호출은 원자적이지 않으므로 exact-head 원자성을
  보장한다고 주장하지 않는다. immutable release에서는 이 변경 경로가
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
- [pinned Anchore artifact client](https://github.com/anchore/sbom-action/blob/e22c389904149dbc22b58101806040fa8d37a610/src/github/GithubClient.ts#L112-L144)
- [actionlint queue 지원 추적](https://github.com/rhysd/actionlint/pull/654)
