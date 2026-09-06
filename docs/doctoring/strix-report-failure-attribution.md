# Strix report 경고의 원인 분류

## 관측과 범위

ContextualWisdomLab/naruon#1244의 run `34039160285`, job `101508385806`,
artifact `9993763655`는 trusted gate `dd0b96feded94f66ecf59b25a5a9b58cfc8b4f69`를 사용했다.
`strix.log:442`의 `web_search invoked without PERPLEXITY_API_KEY configured`
WARNING이 report 실패 패턴에 매칭됐다. 같은 로그의 867–889행은 모델 요청 재시도 뒤
완료를 기록했고, child attempt는 rc0, run.json은 completed/scan_completed=true,
SARIF 결과는 0개였다. 이 완료 기록은 경고 없는 보안 증거를 뜻하지 않는다.

`main@c9052e607e5f3cc76e73207e7786b21500721b79`의 gate는 당시 gate와 동일했다.
기존 #1668 `82b19c4144d10550fb35145b2dc24cdb2db6f27a`는 pool 소진 단정을 이미
제거했다. 이 후속 개발 stack은 그 변경을 복제하지 않고, 남은 report-only 경고의
provider 장애 오표시만 분리한다. 소비자 배포나 미출시 의존성 채택이 아니다.

## 수리 계약

알려진 좁은 경고 예외와 Warn/Fatal/Denied/Timeout 실패 패턴은 바꾸지 않는다.
원래 console 신호와 기존 report-provider 분류기를 먼저 확인하고, 독립된 provider
신호가 없는 report 실패는 `STRIX_REPORT_FAILURE`로 반환한다. gate가 스스로 붙인
실패 문구를 provider 원인 증거로 재사용하지 않는다. 실제 provider 신호가 함께 있으면
기존 provider 실패 경로를 유지한다. 이는 원인 분류이며 report의 안전성 승인도,
모든 provider 오류 형식을 완전히 식별한다는 주장도 아니다.

기존 `test_strix_quick_gate.sh`의 fake Strix harness를 확장했다.
`report-web-search-warning-fails`는 실제 경고 형식, rc0, completed run.json,
빈 SARIF를 만들고도 gate exit 1과 report 진단을 요구한다.
`report-web-search-warning-with-provider-failure`는 같은 report에 RateLimitError를
추가해 provider 진단 보존을 확인한다. 두 경우 모두 호출은 1회이며 원래 경고와
child rc0 기록은 artifact에 남는다. 실제 스캔, API key 추가, 경고 무시, 유료 우회는 없다.

로컬 mock 회귀는 hosted 실행이나 보안 분석 결과의 정확성을 입증하지 않는다.
