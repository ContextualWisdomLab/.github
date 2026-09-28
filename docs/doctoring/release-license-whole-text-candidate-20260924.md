# PR2347 전체 원문 확인 중간 후보

기준은 `48caafec7160dd0cb9bafc58b28a884dc4c35cbb`이다. 원문 제목/부분 문자열만으로 허용하는 P1을 닫는 로컬 후보이며, 전체 의존성 정책 구현 완료나 병합·배포 수용을 뜻하지 않는다.

## 근거와 지원 경계

직접 읽은 저장소 `LICENSE` 전체를 근거로 삼는다. 원시 SHA256은 `08f1fd81fb120bc468b69dc3e58ea0dc23c216305c766e45e107f56c76559e3f`이다. ASCII 공백·탭·CR·LF만 연속 공백 하나로 정규화한 전체 본문 SHA256은 `f5ac0308cf2b3f96a0f49a8c0c9e4a2a02c483afc72a646af8de1f356983de06`이다.

검증 지원은 이 MIT 원문 한 개이며 Copyright 문구까지 포함한다. 다른 저작권자 머리말도 아직 UNKNOWN이다. 임의 머리말·추가 조건·접미사·유니코드 제어 문자를 지우지 않는다. SPDX 선언, 제목, 허용 구절만으로 확인된 원문이 되지 않는다. 이 레지스트리는 새로운 의존성을 라이선스 이름만으로 승인하는 수단이 아니다.

실제 closure에 필요한 BSD, Apache, CC0 및 다른 라이선스 원문·변형 지원은 미완료다. 각 원문과 전체 일치 계약을 독립 검토한 뒤 별도 증분으로 추가해야 한다. 현재 인벤토리 전체 PASS는 불가능하다. 설치 전 도구 의존성 검사는 별도 미해결이다.

`recognize_license_text`의 production caller는 `release_dependency_gate.evaluate_dependency_license`다. CodeGraph는 해당 트리에 index가 없다고 반환하며, 소스 참조를 직접 대조한다. caller가 파일마다 판정하므로 허용 LICENSE와 별도 제한 NOTICE를 함께 넣어도 거부한다.

## 검증

모든 명령은 이 별도 작업 트리에서 실행한다. 환경은 `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, 공통 인자는 `python3 -B -m pytest --noconftest -p no:cacheprovider -o addopts=`다.

1. `tests/test_release_dependency_full_text_contract.py tests/test_spdx_license_policy.py -q`: **68 passed, raw exit 0**. 최초 실행은 새 테스트에서 상수 소유 모듈을 잘못 적어 1 failed/67 passed/exit1이다. `policy.LICENSE_TEXT_DISAGREEMENT`를 실제 소유자 `gate`로 고친 뒤 위 결과를 얻는다.
2. 기존 소형 비교군 `tests/test_release_dependency_license_text_evidence.py tests/test_release_dependency_install_binding.py tests/test_release_dependency_install_ordering.py -q --tb=no`: **18 failed, 27 passed, 1 skipped, raw exit 1**. 기존 fixture는 수정하지 않는다.
3. `git diff --check`: exit0.

새 회귀는 실제 gate의 MIT 추가 상업 제한과 CC0/NonCommercial 반례를 거부하고, 완전한 확인 MIT 원문은 동일 dependency caller에서 통과시킨다. gate 전체의 정상 Python 사례에서도 기존 Cargo Apache fixture가 UNKNOWN으로 남아 전체 통과를 주장하지 않는다. GPL 별도 파일, 추가 NOTICE, 본문 변조·앞뒤 조건·NUL·zero-width suffix도 확인한다.

### 보존하는 기존 실패 분류

- 원문 누락/UNKNOWN/별도 GPL 등 기존 원인 자체는 계속 거부한다. 같은 capture의 Cargo Apache 제목-only fixture가 추가 `LICENSE_TEXT_UNVERIFIED`를 내므로 기존 exact-single-failure 기대와 다르다.
- MIT·Apache·BSD·ISC·MPL·BSL·Unlicense 부분 원문을 정상으로 기대한 사례와 recognizer 직접 호출의 부분 MIT 기대는 더 이상 충족하지 않는다.
- 기존 Apache-vs-MIT 제목-only 불일치는 확인된 Apache가 아니므로 UNKNOWN으로 분류한다. 지원하지 않는 본문에서 라이선스 종류를 확정하지 않는다.
- Cargo-only binding 테스트는 그 Apache fixture 원문의 미확인 때문에 실패한다. lock hash 결속 구현의 변경은 아니다.

실제 gate 분류 재확인: Python 원문 없음은 MISSING + Cargo UNVERIFIED, Python UNKNOWN/부분 MIT/부분 Apache는 각각 Python UNVERIFIED + Cargo UNVERIFIED다. 합성 Cargo를 MIT로 바꿔 실패를 숨기지 않는다.

전체 suite·coverage·hosted CI·Linux capture·원문 수집 완전성·tooldeps 설치 전 검사는 이번 수용 밖이며 HOLD다. 이 후보는 공개 push 없이 다른 reviewer의 검토에 인계한다.
