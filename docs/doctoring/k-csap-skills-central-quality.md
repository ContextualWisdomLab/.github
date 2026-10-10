# K-CSAP 중앙 품질 실행 상태

확인일: 2026-10-09 KST. 관련 issue: 중앙 #2612. 이 문서는 실행 성공 또는 출시 승인이 아니다.

## 현재 단계

2026-10-10 admission 수리본의 독립 fresh review는 `CONDITIONAL_SOURCE_ACCEPTANCE`다. 부모가 report SHA-256 `dbc0d58d24a098c68f33268fcd8dc1a6de00f57bfe729aa0dd0272fd4e29ff62` 및 workflow `2b14845ebf761652ca78ecdaac86c6e851ea41dc573312f41ade2695b0a719b7`, test `36bbf733ea0bec7e0cd3b03cb07d6c466cf19fffb578f16114e820a9d69c3737`를 직접 대조했다. 실제 admission shell 35개와 SHA 소비자 4개 사례가 기대대로 동작했고 고정본 계약 테스트 28개가 통과했다. PR head/event SHA 및 state를 분리하며 admission 출력 SHA를 checkout/HEAD 검증이 함께 소비한다. Flatback의 이전 head 독립 재현은 2 FAIL/3 PASS로 보존한다. 이전 아래 해시는 역사 증거이며 새 수리본의 승인으로 재사용하지 않는다.

setup-uv 사설 저장소/checksum 수정은 실제 pinned dist의 macOS arm64 Node24 실행, 잘못된 checksum 거부, cache-disabled post 실행으로 검토했다. report SHA-256 `2159eec4f6343b82250124b78af57ed8925deaa8a63dc007a6f7e15a9670da83`를 대조했으며 admission 변경과 해당 setup/cleanup 블록의 바이트가 동일함을 fresh reviewer가 확인했다. Linux X64/Node20 실제 Actions, Python runtime 무결성, same-UID 공격 및 강제 종료 격리는 미검증이다. job expression 검증은 로컬 합성 입력이며 원격 runner 배정 증거가 아니다. scratch custom-label actionlint는 canonical CI vocabulary 수락을 대체하지 않는다. 새 소스 출판은 허용되지만 Draft 해제·운영 활성화·병합은 아직 수락하지 않았다.

초안의 독립 리뷰가 FAIL이다. 원본 workflow SHA-256은 `1743d6c788606bdbd6caa2006a2de47a22029ed5696d2a9a705085542224fa45`, 테스트는 `29e2d825a666332c6bf8a3272359d72c743856606f5d940c3f6920869e354db6`이다. 리뷰 report SHA-256은 `a67ed03a6136c0bdc98b48201b68720489f10a68c10a7eaa8eaa5e72f5546fd9`이다. 초안의 9개 계약 테스트와 actionlint 통과는 이 FAIL을 대체하지 않는다.

독립 재리뷰는 동일 workflow/test 해시에서 `PASS_WITH_ACTIVATION_LIMITATIONS`를 반환했다. 부모가 report SHA-256 `923b518cf61b072d3fb8ca7e03e5a1825faaca3c248942dd3048d2fbc2a2a378` 및 두 파일 해시를 직접 대조했다. 리뷰의 focused pytest 21개, custom-label actionlint exit 0, 별도 harmless cleanup probe 11/11은 로컬 계약 증거다. 초기 FAIL report는 역사 기록으로 보존한다. setup-uv 도구 상태는 private cleanup 범위 밖이며 외부 action 내부 cleanup, immutable download 무결성, 실제 원격 실행/App 승인은 미검증이다.

현재 수리본은 job-level `if`를 runner 배정 전 gate로 추가하고, repo-scoped `k-csap-isolated` label을 사용한다. 기존 step admission은 checkout 전 방어층으로 유지했다. exact head, protected master ref, 일회용 source path, Python 3.11.14 및 uv/private venv/cache를 좁은 테스트로 검증했다. 초안 FAIL을 역사 기록으로 유지하며 수리본의 독립 재리뷰는 로컬 소스 한정 조건부 통과다. 수리 과정의 위임 writer 2회는 provider transport 실패로 결과 없이 종료했으며 부모가 테스트 RED를 확인하고 직접 수리했다. 수정본 로컬 `pytest` 21개 통과, scratch custom-label actionlint와 `git diff --check` exit 0; workflow SHA-256 `9c4cc914b57f919da06f434527670d34597ac4a8c1fc4c24008ce36440fdc5c9`, 최종 test SHA-256 `64ae572dfee0063e85ec4850969c02018105aceeb237d20abb1dedc7fe68d2c9`, 최종 staged patch SHA-256 `03a8a6260ae18aa887aab3151dcf8848c0fbe2f3c28cd47b6808699bf579968e`다. 이는 실 runner에서의 실행/격리를 입증하지 않는다.

## 리뷰 사실관계 구분

리뷰는 “checkout도 admission 전에 실행된다”고 기록했으나 frozen YAML은 첫 step admission, 다음 step checkout 순서다. 이 서술은 현재 파일로 지지되지 않는다. 반면 job runner 배정은 첫 step보다 앞서므로 **step admission만으로 배정 이전 신뢰 경계가 생기지 않는다는 지적은 유효하다.** 원본 FAIL을 삭제하거나 PASS로 덮어쓰지 않는다. 완료한 재리뷰 `923b518c…`에서 이 두 결론을 구분했다.

PR exact head 검증은 기존 PR #30의 exact-head 증거 계약을 이어받은 의도다. GitHub merge candidate를 검증했다는 주장은 하지 않는다. push/manual 호출은 protected master로 제한하는 수리 계약이다.

## 원격 activation

직접 API 조회 결과:

- 조직 group 13 `CWL CI isolated`는 `visibility=selected`, `restricted_to_workflows=false`이다.
- 허용 repository 목록에 K-CSAP이 없다. 소속 runner `orgmetra-ci-01`, `keyverse-ci-01`, `calendarweave-ci-01`은 모두 offline이다.
- 제품 repo-scoped `k-csap-isolated-linux`는 online/idle이다. 조직 group 13의 runner가 아니다. group 구성원이란 이유 없이 옮기거나 relabel하지 않는다.
- 중앙 global PR #2565의 head는 `ef65b2fdc2036ccaca8d19c1db88dc8075ae9164`, OPEN이다. 기존 owner source는 수정하지 않는다.

중앙 reusable job은 caller에 제공된 repo-scoped runner도 사용할 수 있다는 소유권 교정을 반영했다. group 13 ACL 추가는 이 경로의 선행조건이 아니다. 현재 labels가 맞는 runner의 등록 상태만 확인했고 실제 reusable job 배정과 host isolation은 미검증이다. 동일 UID의 적대적 동시 writer, 잔류 프로세스, 강제 종료와 tool download 무결성은 activation gate에 남는다. 사용자 요구에 따라 hosted fallback은 추가하지 않는다. 실제 execution evidence가 없으면 unavailable로 남긴다.

## AI 리뷰 및 키 경계

중앙 #2560 key/relay custody와 Remora shared review owner를 유지한다. `LLM_GATEWAY_API_KEY` Secret metadata updated `2026-10-09T05:07:41Z`와 `LLM_GATEWAY_MODEL=auto`를 확인했다. 비밀 값은 읽지 않았고 중복 발급/덮어쓰기는 하지 않았다. 사용자가 지정한 `https://litellm.poinnetworks.net`의 실제 authenticated auto inference, private-data route 적격성, author-distinct App의 exact-head APPROVED는 아직 이 lane에서 검증하지 않았다.

## 재현 가능한 테스트 환경

새 전용 테스트 lock `requirements-k-csap-quality-tests-hashes.txt`는 `requirements-k-csap-quality-tests.in`에서 uv 0.12.5의 실제 compile로 생성했다. 공유 manifest/lock은 수정하지 않았다. private scratch CPython 3.11.16 환경에서 hash-required binary-only sync로 pytest 9.1.1, PyYAML 6.0.3 및 4개 전이 의존성을 설치하고 21개 계약 테스트를 실행해 통과했다. YAML 텍스트에서 기대값을 합성하는 대안 parser는 폐기했으며 실제 PyYAML로 구조를 읽는다. `subprocess.run(check=False)`를 명시하여 실패 exit 검증을 유지했다. 최종 delta 재리뷰 report SHA-256 `0d36a3d66c8d6ae435128cfaeda8d0926b3fa0721a50ddc3c7b489e4d157095d`가 이 테스트/lock/문서 범위를 조건부 통과로 바인딩했다. runtime workflow의 Python pin은 3.11.14로 유지되어, 이 실행은 workflow 원격 runtime 실행 증거가 아니다.

## 다음 gate

1. 로컬 소스와 최종 delta 독립 검토 완료. 운영 제한은 미수락이다.
2. 중앙 Draft PR #2615를 출판했다. 초도 head는 `9996a21600b3751491842de20ca4c87e1cc257a8`이며 아직 병합하지 않았다.
3. 실제 required checks와 formal App 검토를 확인하고 제한을 해결한 뒤 일반 병합으로 callee를 보호 브랜치에 출판한다. 소비자 caller에 가짜 SHA나 mutable branch를 넣지 않는다.
4. caller·runner ACL·capacity를 승인된 경계에서 연결하고 run ID와 job.runner_name을 검증한다.
5. 실제 Noema/OpenCode auto inference 및 조건부 App 승인을 별도 확인한다. 단독 개발자에게 가상의 다른 인간 리뷰어를 요구하지 않는다.
6. 현재 head에서 확인한 두 실패는 별개다. CodeQL `Analyze (javascript-typescript)`는 billing account lock 때문에 시작하지 않았다. Noema는 Draft라 model inference를 skip한 뒤 Artifact storage quota로 upload에 실패했다. GraphQL annotations로 원인을 확인했으며 REST log 조회 quota 403은 별도 조회 실패다. `coverage-evidence`/`coverage-source-tree` SUCCESS와 `opencode-review` SKIPPED는 실 모델 승인 증거가 아니다. 필요한 check 실패 및 운영 제한 해결 전 Draft를 유지한다.
