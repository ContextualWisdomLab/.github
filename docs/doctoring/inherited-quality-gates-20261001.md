# 상속된 coverage·docstring 게이트 복구

## 원인과 범위

PR #2261의 정확한 base `7900ba4c4d68c378023592252f2579646fad9aaa`를 별도 clean worktree에서 검증했다. 전체 테스트는 5,182개 통과했지만 coverage는 99%(미측정 statement 181개), docstring은 97.1%였다. PR head `0852d3044a09a5c751589c3d2024293cb99b6ff8`의 공유 77개 모듈별 coverage 결과는 base와 같았다. 원인 귀속을 분리하는 근거이며, 실패한 게이트를 면제하는 근거는 아니다.

누락은 세 가지가 섞인 결과였다. 일부 테스트는 coverage가 시작되지 않은 child Python에서 CLI를 실행했다. 다른 테스트는 CLI·오류 경로를 호출하지 않았다. 선행 검증이 이미 강제한 불변식을 마지막에 다시 검사하는 중복 조건도 있었다.

기존 테스트에 실제 CLI 결과, 잘못된 입력의 거부, 오류의 원인 보존, 자원 정리, queued-only 변경 경계를 검증하는 assertion을 추가했다. 기존 subprocess smoke는 유지하며 in-process 검증을 보충했다. 누락된 docstring은 현재 함수의 입력·출력·실패 계약에 맞춰 복구했다. Coverage 설정·threshold·dependency pin은 바꾸지 않았다.

## 보안 경계

- Runtime archive prescreen은 정확한 primary 13개·Intel variant 3개 대상 집합을 파일 및 native 검사 전에 확인한다. 누락·중복·대체 대상·잘못된 variant는 `SCOPE_UNVERIFIABLE`로 거부한다. 각 archive의 비어 있지 않음, byte identity와 inventory 검증은 유지했다.
- Maturin 다운로드는 응답을 얻은 뒤에만 정리 블록에 들어가며 응답을 반드시 닫는다. HTTP/OSError의 취득·읽기 실패, non-200 응답, size 초과의 결과와 자원 정리를 검증했다. Proxy 차단, exact redirect, 허용 asset, 크기 제한은 유지했다.
- Pingora에서는 앞선 encoding 검사에 지배되는 중복 조건만 제거했다. 기존 encoding·content·raw transport 실패 검증은 유지했다.
- Cargo의 `file://` fixture는 두 dependency가 package-only 로컬 Git crate라는 것을 검증한다. 해당 lockfile 생성 호출에만 `CARGO_NET_OFFLINE=false`를 적용하며 이후 vendor·build는 offline 상태를 유지한다. 원격 registry 접근을 허용하는 변경이 아니다.

Air 담당 5개 파일과 선행 #2531의 원격 branch는 변경하지 않았다. 기존 repair 커밋의 테스트·docstring만 선택적으로 재사용했으며 parser dependency 변경이나 완전성 검사의 단순 삭제는 승계하지 않았다. Python 3.10용 선택적 `tomli` 테스트의 기존 `importorskip` 계약도 보존했다.

## 실제 검증

최초 offline 전체 실행은 5,258 passed와 1 failed였다. 전역 offline 설정이 최초 로컬 Git fetch도 차단한 fixture 실패이며 성공으로 재기록하지 않았다.

Base와 첫 수리 `4743e7f8c`의 측정은 5,274 passed, 4 skipped, 40 subtests passed였다. Statement 18,256개·branch 7,500개에서 누락 및 partial 0, coverage 100%, docstring 100%를 확인했다. 이 결과는 PR #2261의 최종 combined HEAD나 hosted acceptance를 증명하지 않는다. 결합 후 전체 게이트를 다시 실행하고 정확한 현재 HEAD의 필수 검사와 비작성자 formal approval을 확인해야 한다.

실행 명령:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 GITHUB_ACTIONS=true CARGO_NET_OFFLINE=true \
  python3 -m coverage run -m pytest tests -q
python3 -m coverage report --show-missing
python3 -m interrogate
```

독립 검토·현재 HEAD의 hosted 검사·선행 PR의 보호 main 통합·정식 head-guarded 병합이 완료되기 전에는 릴리즈 수용이나 merge authorization으로 취급하지 않는다.

## 2026-10-02 후속 오류 정리 검증

정적 검토에서 Maturin의 `read()`가 별도 HTTP 오류 stream을 만든 뒤 정상 response의 `close()`도 `OSError`를 내는 조합이 제기됐다. Production 발생을 확인한 것은 아니지만, 해당 조합의 합성 테스트는 실제로 stream이 열려 있음을 확인하며 실패했다. HTTP 오류 stream을 먼저 정리한 뒤 response 정리를 수행하도록 순서를 보강했다. 최종 cleanup 오류는 숨기지 않으며 원 HTTP 오류를 exception context에 보존한다.

새 회귀를 포함한 Maturin 테스트 24개, 해당 모듈의 statement·branch coverage 및 docstring 100%를 확인했다. 변경된 combined HEAD의 전체 재측정과 hosted 검증은 별도 진행한다.
