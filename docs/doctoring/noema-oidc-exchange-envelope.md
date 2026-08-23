# Noema OIDC exchange response-envelope contract

검토 기준일: **2026-08-24**

## 문제

중앙 `noema-review.yml`의 OIDC credential 경로는 Noema `/exchange` 성공 응답에서 top-level `.token`을 읽고 있었습니다. 그러나 Noema의 공개 API 안정성 계약은 성공 값을 다음과 같이 `data` object 아래에 둡니다.

```json
{
  "ok": true,
  "data": {
    "token": "ghs_...",
    "repository": "ContextualWisdomLab/example",
    "workflow_ref": "ContextualWisdomLab/.github/.github/workflows/noema-review.yml@refs/heads/main",
    "token_expires_at": "2026-08-07T12:00:00Z"
  },
  "trace_id": "..."
}
```

따라서 provider가 token을 정상 발급해도 consumer가 `.token`을 조회하면 빈 값이 되어 중앙 reviewer가 항상 실패했습니다. 이 결함은 credential이 없는 것처럼 보이지만 실제 원인은 provider/consumer schema 불일치입니다.

## 결정

OIDC consumer는 token field 하나만 permissive하게 조회하지 않고 다음 전체 contract를 fail closed로 검증합니다.

1. top-level `ok`가 정확히 `true`여야 합니다.
2. `data`가 JSON object여야 합니다.
3. `data.token`이 비어 있지 않은 string이어야 합니다.
4. `data.repository`가 요청한 `TARGET_REPOSITORY`와 정확히 같아야 합니다.
5. Actions가 제공한 `GITHUB_WORKFLOW_REF`가 존재하고,
   `data.workflow_ref`가 그 실행 workflow ref와 정확히 같아야 합니다.
6. `data.token_expires_at`가 RFC 3339 UTC timestamp로 해석 가능하고 현재
   시각보다 뒤여야 합니다.
7. top-level `trace_id`가 비어 있지 않은 string이어야 합니다.
8. 검증된 뒤에만 `data.token`을 추출하고 즉시 GitHub Actions mask를 적용합니다.
9. malformed response를 진단할 때 raw response나 token 값을 출력하지 않습니다.

이 변경은 Noema의 reviewer App, PAT fallback, LLM provider,
`NVIDIA_NIM_API_KEY`, repository permission 또는 merge authority를 변경하지
않습니다. OIDC path가 이미 발행된 stable response envelope를 정확히 소비하도록
고치는 interoperability repair입니다. Noema producer는 원래 OIDC assertion의
audience, repository, workflow ref 및 source SHA를 검증하고 제한된 GitHub App
installation token을 발행합니다. 중앙 consumer는 그 assertion을 다시 검증한다고
주장하지 않고, producer가 반환한 repository, workflow ref, expiry 및 trace binding을
검증합니다.

## 표준 근거

RFC 8259는 JSON object를 name/value member의 집합으로 정의하고, member name이 고유할 때 구현 간 mapping agreement가 가능하다고 설명합니다. 또한 networked JSON text는 UTF-8을 사용해야 하며 parser가 size·depth·string length 제한을 둘 수 있음을 명시합니다. 이 변경은 shell의 loose field lookup 대신 object shape와 typed member를 명시적으로 검사하여 producer/consumer가 같은 mapping을 사용하도록 합니다.

NIST SP 800-218 SSDF Version 1.1은 소프트웨어 생산자가 vulnerability의 근본 원인을 줄이고 소비자·구매자와 공통 보안 언어로 소통할 수 있도록 secure-development practices를 SDLC에 통합할 것을 권고합니다. 현재 finalized baseline은 v1.1이며, Rev. 1 / SSDF Version 1.2는 2025년 12월 공개된 initial public draft입니다. 이 변경은 실제 integration failure를 회귀 계약으로 고정하고 permissive fallback 대신 명시적 failure evidence를 남긴다는 점에서 해당 원칙을 적용합니다.

RFC 6749 places an OAuth access token at the top-level `access_token` member
(Hardt, 2012). Noema's public exchange instead wraps the GitHub App token under
`data.token` with repository, workflow, expiry, and trace evidence. NIST SP
800-63C-4 requires relying parties to validate assertion audience and time
windows and to preserve replay resistance (Temoshok et al., 2025). The Noema
producer performs the assertion validation; this consumer accepts the returned
credential only when its stable envelope is bound to this exact repository and
executing workflow and remains unexpired. Reading `.token` as if the response
were RFC 6749 instead treats a schema mismatch as a missing secret and discards
the binding evidence.

## 회귀 계약

- workflow가 `.token // empty`를 사용하지 않습니다.
- `jq -e`가 stable envelope, target repository, exact executing workflow ref,
  future expiry 및 trace identifier를 검증합니다.
- 추출 경로는 `.data.token`입니다.
- malformed envelope는 `response envelope was invalid`로 실패합니다.
- raw response는 diagnostic output으로 반사하지 않습니다.
- token은 output 기록 전에 `::add-mask::` 처리됩니다.

## 롤백과 호환성

롤백은 top-level `.token`으로 되돌리는 것이 아니라, provider의 실제 stable envelope가 변경되었다는 독립적으로 검증된 근거가 있을 때 producer와 consumer 계약을 같은 변경에서 함께 갱신하는 방식으로 수행합니다. 기존 GitHub App 및 PAT credential 경로는 이 OIDC schema repair와 독립적으로 유지되며, standalone product repositories는 중앙 reviewer의 내부 response parsing에 런타임 결합되지 않습니다.

## References (APA 7th)

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange format* (RFC 8259). Internet Engineering Task Force. https://doi.org/10.17487/RFC8259

ContextualWisdomLab. (2026). *Noema API specification* [Computer software
documentation]. GitHub.
https://github.com/ContextualWisdomLab/noema/blob/main/docs/api-spec.md

Hardt, D. (Ed.). (2012). *The OAuth 2.0 authorization framework* (RFC 6749).
Internet Engineering Task Force. https://doi.org/10.17487/RFC6749

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development Framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

National Institute of Standards and Technology. (2025, December 17). *Secure Software Development Framework (SSDF) version 1.2 is available for public comment*. https://www.nist.gov/news-events/news/2025/12/secure-software-development-framework-ssdf-version-12-available-public

Temoshok, D., Richer, J., Choong, Y.-Y., Fenton, J., Lefkovitz, N.,
Regenscheid, A., & Galluzzo, R. (2025). *Digital identity guidelines:
Federation and assertions* (NIST Special Publication 800-63C-4). National
Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-63c-4
