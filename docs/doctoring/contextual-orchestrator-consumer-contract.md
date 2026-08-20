# contextual-orchestrator consumer doctoring

운영자는 [normative consumer contract](../standards/contextual-orchestrator-consumer-contract.md)를
먼저 읽고, production 호출이 adaptive `auto`를 사용하며 capability·quality·safety를
신뢰할 수 있는 비용보다 먼저 최적화하는지 확인해야 합니다. 가격이 없거나 잘못된 모델은
무료로 간주하지 않으며, provider-native structured-output passthrough가 일반 경로를
단일 worker로 고정하지 않는지 확인합니다.

검증 결과에는 exact outbound request, 선택된 orchestration mode, 모델 capability·price
metadata, structured-output validation 결과, 그리고 예외 mode의 ADR·회귀 테스트 위치를
기록하십시오. 실패 시 production 배포를 중단하고 consumer contract 테스트와 중앙
operator policy snapshot을 함께 수정한 후 같은 HEAD에서 재검증하십시오.

## APA 7th references

Omidvar, H., & Akhlaghi, V. (2026). *A communication-theoretic framework for LLM agents:
Cost-aware adaptive reliability* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2605.09121

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H., Tymchenko, I.,
Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., & Clanuwat, T. (2026).
*Sakana Fugu technical report* [Technical report]. arXiv.
https://doi.org/10.48550/arXiv.2606.21228

Zhang, S., Yu, Y., Li, Y., Zhao, W., Yang, Y., Zhang, Y., & Liu, T. (2025).
*Conductor: Learning to route multi-agent workflows* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026).
*TRINITY: An evolved LLM coordinator* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04695
