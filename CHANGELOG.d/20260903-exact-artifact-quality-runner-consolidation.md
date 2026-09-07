## Changed

- Exact Artifact SBOM Attestation 품질 검증의 Python 3.10 compile job과 Python 3.14
  coverage job을 한 exact-head runner로 통합했습니다.
- runner 부팅·harden-runner·checkout을 실행당 2회에서 1회로 줄이고 최소 Python
  호환성, branch coverage 100%, docstring 100% 계약은 보존했습니다.
- PR concurrency를
  `exact-artifact-sbom-attestation-quality-{repository}-{PR번호}`와
  `cancel-in-progress: true`로 고정했습니다.
