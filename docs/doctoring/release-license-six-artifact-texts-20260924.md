# 실제 artifact 원문 여섯 개의 증분 인식

이 후보는 `4329ebb84ddac1752e5c4149fd3c94731b262f2e` 뒤에 여섯 전체 원문 hash를 추가한다. 일반적인 라이선스 판별기나 전체 배포 closure 승인으로 확대하지 않는다. production 변경은 기존 `_VERIFIED_LICENSE_TEXT_DIGESTS` 추가뿐이다.

## 출처와 직접 읽은 범위

자료는 기존 로컬 FMLS license evidence archive다. artifact filename/SHA256, 내부 member, 원시 SHA256, 정규화 SHA256, SPDX 대응은 `tests/fixtures/release_license_texts/provenance.json`에 기록한다. 원문은 기억에서 재작성하지 않고 archive member를 UTF-8로 읽는다. 전체 본문을 줄 생략 없이 확인한다. `texts.json`의 각 문자열을 UTF-8로 인코딩한 바이트가 원시 member hash와 일치하는지 테스트한다. `fixture` 필드는 이 JSON 안의 키다. 끝 개행이 없는 원문도 그대로 보존한다.

|실제 원문|읽은 허용·조건과 경계|
|---|---|
|pytest9.1.1 LICENSE / MIT|전체 grant에 use/copy/modify/merge/publish/distribute/sublicense/sell과 without restriction이 있다. copyright·permission notice 보존 및 보증 면책을 읽는다. 정확한 Holger Krekel 머리말도 hash에 포함한다. 다른 MIT 머리말을 자동 인정하지 않는다.|
|atheris3.1.0 LICENSE / Apache-2.0|1–9절과 적용 부록 전체다. 2절 copyright grant, 3절 patent grant·소송 종료조건, 4절 재배포·수정·고지, 5절 contribution, 6절 trademark, 7–9절 보증·책임을 읽는다. 별도 NC/학술 전용 부속문구는 없다. 이는 파일의 인식이며 실제 atheris의 metadata 선언 누락은 계속 HOLD다.|
|Rust numpy0.29.0 LICENSE / BSD-2-Clause|source·binary 재배포 허용, 두 고지 보존 조건, 전체 면책을 읽는다. PyPI NumPy 복합 원문과 다른 파일이다.|
|colorama0.4.6 LICENSE.txt / BSD-3-Clause|source·binary 재배포 허용, 고지 보존 두 조건, 이름을 허가 없이 endorsement에 사용하지 않는 세 번째 조건과 면책을 읽는다. 추가 상업 이용 금지는 없다.|
|libloading0.8.9 LICENSE / ISC|any purpose with or without fee의 use/copy/modify/distribute 허용, copyright·permission notice 보존, 전체 면책을 읽는다. Simonas Kazlauskas 머리말을 포함한다.|
|foldhash0.2.0 LICENSE / Zlib|any purpose including commercial applications, alter/redistribute 허용과 출처 오인 금지·변형 표시·고지 제거 금지 세 조건을 읽는다. 전체 면책도 포함한다.|

모두 저장된 실제 소스에 대한 인식 지원이다. 상용 제품의 모든 법적 의무 충족을 확정하는 판단이 아니다. 선택된 OR의 pointer 문서, PyPI NumPy의 GPL/LGPL 복합 원문, upstream 16개, 다른 copyright/원문 변형, 수집 누락은 별도 HOLD다. 추가 파일마다 기존 consumer의 검사가 계속 적용된다.

## 검사와 실패 보존

명령 공통 환경: `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -B -m pytest --noconftest -p no:cacheprovider -o addopts=`.

- `tests/test_release_dependency_reviewed_artifact_texts.py tests/test_release_dependency_full_text_contract.py tests/test_spdx_license_policy.py -q`: 99 passed, raw exit0. 여섯 실제 원문의 hash·정상 consumer, 앞/뒤/중간 추가 조건, 별도 NOTICE 제한, atheris 선언 누락 유지가 포함된다.
- 첫 fixture 생성은 끝 개행을 추가해 원시 hash 6건이 실패(6 failed/93 passed)하고, 첫 보정은 개행 없는 2개 파일 끝 문자를 훼손해 4 failed/95 passed다. 원문 문자열을 JSON에 그대로 보존하는 방식으로 보정하고 모든 원시 hash를 다시 확인한다. 정규화 hash만 일치한다는 이유로 이 실패를 무시하지 않는다.
- 기존 비교군 `test_release_dependency_license_text_evidence.py`, `test_release_dependency_install_binding.py`, `test_release_dependency_install_ordering.py`: 18 failed/27 passed/1 skipped, raw exit1. 이전과 같은 미지원 부분 원문 기대값 실패를 보존한다. 기존 fixture 수정은 없다.

이전18건 중 잘못된 양성 기대는 짧은 MIT/Apache/BSD/ISC/MPL/BSL/Unlicense 제목·일부 grant를 완전 원문으로 취급하는 부분이다. 정상 corpus를 바꾸려면 그 라이선스의 실제 전체 자료와 hash를 같은 SPDX로 연결하는 별도 diff가 필요하다. Cargo Apache 제목-only fixture도 Apache 전체 원문으로 복원해야 하며, MIT로 바꾸는 방식은 허용하지 않는다. 이번 변경은 그 기대값을 편의상 고치지 않는다.

전체 suite·coverage·hosted·tooldeps 검사와 publish는 미실행·HOLD다. 여섯 원문 추가로 범위 전체를 수용하지 않는다.
