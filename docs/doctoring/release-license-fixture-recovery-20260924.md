# 기존 18실패의 원문 근거 복원

기준 `4fe66efdcee6bb6b68e5a6c386feea7280ecea8d`에서 새 브랜치 `codex/pr2347-source-fixture-recovery-20260924`를 사용한다. 기존 여섯 원문의 JSON 값과 provenance 첫 여섯 행은 Git blob 대조로 불변을 확인한다.

공통 fixture는 Python MIT→실제 pytest 전체 MIT, Cargo Apache→실제 atheris 전체 Apache로 연결한다. 패키지 자체에 atheris라는 이름을 붙이거나 metadata 누락을 고친다는 주장이 아니라, synthetic gate fixture의 동일 SPDX 본문을 검증 가능한 전체 원문으로 복원한다. Cargo를 MIT로 바꾸지 않는다. 원문 hash는 기존 provenance에 있다.

## 18개 before/after 기대와 근거

아래 이름은 `test_release_dependency_license_text_evidence.py` 기준이다. P=Python 원문, C=Cargo 원문이다. 기존 실패의 별도 C UNVERIFIED는 실제 Apache 전체 원문으로 해소한다. 검사의 핵심 실패 사유를 삭제하지 않는다.

|번호|사례|before expected|after expected 및 변경 근거|
|---|---|---|---|
|1|no_bundled_text|MISSING 1개|동일. C만 전체 Apache로 복원|
|2|unrecognizable[unknown]|UNVERIFIED 1개|동일. UNKNOWN 입력 유지|
|3|unrecognizable[commercial-prohibited]|UNVERIFIED 1개|동일. 상업 금지 입력 유지|
|4|unrecognizable[empty]|UNVERIFIED 1개|동일. 빈 원문 유지|
|5|unrecognizable[pointer]|UNVERIFIED 1개|동일. 링크-only 입력 유지|
|6|unrecognizable[all-rights-reserved]|UNVERIFIED 1개|동일. 권리 유보 입력 유지|
|7|recognized_text_contradicts_declaration|DISAGREEMENT 1개|동일. MIT 선언에 실제 전체 Apache를 넣음|
|8|denied_title_disagreement|DISAGREEMENT 1개|동일. 정상 LICENSE는 실제 MIT, 별도 GPL COPYING 유지|
|9|matching_declaration|실패 없음|동일. 전체 pytest MIT 사용|
|10|permissive_family[Apache]|실패 없음|동일. 전체 atheris Apache 사용|
|11|permissive_family[BSD3]|실패 없음|동일. 전체 colorama BSD3 사용|
|12|permissive_family[ISC]|실패 없음|동일. 전체 libloading ISC 사용|
|13|permissive_family[MPL]|실패 없음|제목-only 원문은 UNVERIFIED. unsupported_title_only[MPL]로 목적을 명시하며 동일 입력을 유지. 실제 hypothesis 복합 적용 범위는 아래 별도 HOLD|
|14|permissive_family[BSL]|실패 없음|제목-only 원문은 UNVERIFIED. unsupported_title_only[BSL]로 목적을 명시하며 동일 입력을 유지. 기존 cache 인벤토리에 BSL 원문 mapping이 없음|
|15|permissive_family[Unlicense]|실패 없음|동일. memchr의 실제 전체 UNLICENSE 사용|
|16|dual_selection_disagreement|DISAGREEMENT 1개|동일. BSD/GPL 선언·BSD 선택에 실제 전체 MIT를 넣어 불일치 유지|
|17|recognizer_positive_half|MIT 포함|동일. 전체 MIT를 사용하고 UNKNOWN 반환 검사는 유지|
|18|install_binding cargo_only_release|실패 없음, lock digest 없음|동일. C에 전체 Apache를 연결. lock/hash 구현은 변경하지 않음|

BSD 선택 양성과 sealed SBOM 선택 rationale 테스트도 동일 colorama BSD3 전체 원문으로 복원한다. 앞 후보의 부분 Apache 거부 테스트는 공통 fixture 변경에 영향받지 않도록 그 테스트에서 부분 Apache를 명시한다. 기존 음성을 정상으로 변경하지 않는다.

## 추가 실제 원문과 보류

memchr2.8.3 `.crate` SHA256 `cf8baf1c55e62ffcace7a9f06f4bd9cd3f0c4beb022d3b367256b91b87513d98`, member `memchr-2.8.3/UNLICENSE`, 원시 `7e12e5df4bae12cb21581ba157ced20e1986a0508dd10d0e8a4ab9a4cf94e85c`, 정규화 `2069c208cba553e43cd0b730df8a0c10bf1b1101b96f661e2f1307c73b9722e3`다. 전체 본문에서 copy/modify/publish/use/compile/sell/distribute, commercial or non-commercial, public-domain dedication 및 면책을 직접 읽는다. 다른 추가 조건을 발견하지 않는다. 이 파일만 registry에 추가하며 crate의 COPYING pointer·MIT/Unlicense 선택 전체를 자동 수용하지 않는다.

hypothesis6.156.6 wheel SHA256 `b4e66aaa7385538a5d617174d47c198ee807f06de99e282a67c6cb724c69340d`, member `hypothesis-6.156.6.dist-info/licenses/LICENSE.txt`, raw `ac89037bac63550644dce8cf32c6765e5fab9dc1a1ce94b89f8a805f341a6750`이다. 전체 1–10절과 Exhibits A/B를 읽는다. 앞부분은 명시된 예외 외 MPL 적용, 다른 프로젝트 코드의 원래 license와 수정 dual license를 설명한다. METADATA의 License-Expression=MPL-2.0/License-File=LICENSE.txt이며, archive의 license/copying/notice 이름 member는 이 파일 하나다. 개별 코드의 다른 원래 라이선스 적용 범위는 이 한 파일로 확정되지 않아 후속 mapping 검토가 필요하다.

1.12절의 GPL/LGPL/AGPL 명칭은 Secondary License 정의다. 그 이름만으로 실제 금지 의존성이나 선택된 copyleft라고 판정하지 않는다. 기존 `scan_license_text`가 이 명칭에서 거부하는 문제는 의미 구분이 없는 별도 한계다. 이번 원문은 `unsupported-hypothesis.json`에 원시 hash와 함께 보존하고 recognizer UNKNOWN을 확인하며, keyword 거부를 실제 GPL 확정 판정으로 승인하지 않는다. 이번 범위에서 scanner 예외를 새로 허용하지 않는다.

## 실행

```
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -B -m pytest --noconftest -p no:cacheprovider -o addopts= tests/test_release_dependency_license_text_evidence.py tests/test_release_dependency_install_binding.py tests/test_release_dependency_install_ordering.py tests/test_release_dependency_full_text_contract.py tests/test_release_dependency_reviewed_artifact_texts.py tests/test_spdx_license_policy.py tests/test_release_dependency_gate.py tests/test_release_dependency_gate_capture_and_seal.py -q --tb=short
280 passed, 1 skipped in 2.94s
raw exit 0
```

최초 실행은 sealed SBOM 사례의 REVIEWED_TEXTS import 누락으로 1 failed/279 passed/1 skipped/exit1이다. 실제 해당 함수 import를 고쳐 위 결과를 얻는다. 기존 skip은 macOS의 GNU find capture 경로이며 새 skip을 추가하지 않는다. 검사 삭제 없이 MPL/BSL 두 parameter를 별도 UNKNOWN 음성으로 유지하고, 실원문과 추가 제한·다중 파일·미선언 거부 회귀를 함께 실행한다. 마지막 unused import 제거는 실행 경로와 무관하다.

`git diff --check` exit0. 기존6개 텍스트/provenance 불변 대조 true. 전체 suite·coverage·hosted·tooldeps·현재 release closure는 이번 소형 성공으로 수용하지 않으며 HOLD다.
