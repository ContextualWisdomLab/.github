# OpenCode private source의 artifact 수신 경계

## 요구와 근거

private PR source archive를 공개 review 저장소의 Actions artifact로 발행하지 않는다. GitHub 공식 안내는 workflow artifact의 다운로드 권한을 해당 저장소의 read access에 결속한다. private 원본 저장소의 ACL이나 `retention-days: 1`은 공개 수신 저장소의 다운로드 권한을 제한하지 않는다.

- GitHub. (2026). *Downloading workflow artifacts*. https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts (확인: 2026-10-14).
- 근거 소스: `acb8b34f9e7b8649fa1478139fa21c2217bdfbc7`의 `.github/workflows/opencode-review-dispatch.yml`.

## 좁은 수리

검증된 `steps.validate.outputs.is_private`와 기존 `github.event.repository.private`를 비교한다. private source의 artifact 수신 저장소가 정확히 private가 아니면 coverage 전용 token exchange, source fetch, archive, upload 전에 nonzero로 거부한다. source visibility가 미확인이어도 거부한다. 새 허가 Boolean이나 정책 variable은 추가하지 않는다.

public source의 credential-free, artifact-free 경로는 유지한다. private 수신 저장소의 기존 artifact 경로와 1일 보존값도 유지한다. 이 수리는 공개 중앙 저장소로의 private archive 전달을 금지하는 경계이며, 암호화 전송 구현이나 private 실행 활성화가 아니다. 실제 private 데이터 전송이나 과거 유출이 있었다고 주장하지 않는다.

## 검증과 남은 조건

실제 YAML의 guard 위치·환경 binding을 검사하고 inline Bash를 합성 visibility 입력으로 실행한다. 정상 public 및 private destination을 별도 양성 대조로 유지한다. 원본 artifact-free helper의 실제 로컬 Git 회귀도 함께 실행한다. `tests/test_opencode_public_source_transport.py`는 기존 quality CI의 실행 목록에 포함되어 있다.

모델 비용·retention admission, 실제 source transport, 독립 App의 exact-head 리뷰, 원격 Actions 및 병합은 별도 gate다. private target의 나머지 경로를 이 guard만으로 모두 안전하다고 선언하지 않는다. guard를 우회하거나 정책 attestation을 조작해 실행하지 않는다.
