## 성능 및 워크플로우 최적화
* `grep -Fqi -- "$needle" <<<"$review_text"`와 같은 서브프로세스 호출은 `while` 루프 내에서 수천 번 실행될 경우 심각한 성능 저하를 야기함.
* 이를 해결하기 위해 Bash 내장 문자열 패턴 매칭 `[[ "$string" == *"$needle"* ]]`을 사용하고 `shopt -s nocasematch` 옵션으로 대소문자 무시를 구현함. (테스트 결과 약 2000개의 체크 항목에 대해 8초 이상 걸리던 소요 시간이 2.9초로 단축됨)
* 쉘 옵션 수정 후 원래 상태로 복구하는 방어적인 코드(`local was_nocasematch=0; if shopt -q nocasematch; then was_nocasematch=1; fi; ... if [ "$was_nocasematch" -eq 0 ]; then shopt -u nocasematch; fi`) 작성이 중요함.
* `set -e`가 켜져 있을 때 명령 실패 시 스크립트가 종료되는 것을 방지하기 위해 `local result=1; if ... then result=0; fi; return "$result"` 형식으로 종료 코드를 반환하도록 구현함.
