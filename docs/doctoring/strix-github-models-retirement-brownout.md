# Strix GitHub Models retirement brownout and NVIDIA NIM budget

## Decision

Required Strix runs on ContextualWisdomLab/.github#930, #934, #941, and
#949 failed closed after the public NVIDIA NIM primary
(`nvidia_nim/nvidia/nemotron-3-super-120b-a12b`) consumed the 90-minute
process budget or later GitHub Models fallbacks returned HTTP 410
`github_models_retirement_brownout`. A commercial buyer reading the
required security dashboard therefore saw red Strix checks that were
provider-family outages, not vulnerability evidence.

This increment:

1. Caps each NVIDIA NIM attempt at 1800 seconds so a second hosted NIM
   candidate still receives test-time compute inside the 5700-second
   total budget (Conductor-style recursive allocation; Zhang et al.,
   2025). The 90-minute hard process cap remains for non-NIM models.
2. Adds `nvidia_nim/nvidia/llama-3.1-nemotron-ultra-253b-v1` before
   Llama-3.3-Nemotron-Super-49B. This preserves the protected-main
   `Super-49B → GitHub Models` smoke contract while still reserving
   another hosted NVIDIA attempt before the GitHub Models family.
3. Classifies a single bounded log line that contains
   `github_models_retirement_brownout`, GitHub Models context, and
   a digit-terminated `Error code: 410` / `HTTP 410` or the phrase
   `retirement brownout` as family-dead provider evidence. Remaining
   `github_models/*` fallbacks are skipped. Application 410s, issue
   `#410`, longer codes such as `4100` / `4104`, and cross-line
   spoofing stay non-retryable (CWE-1288; MITRE, n.d.).
4. Keeps GitHub Models as last-resort fallbacks for github_models and
   openai_direct modes. Vulnerability signals still block neutralization.

Accuracy, not wall-clock speed, is the allocation criterion (Narimani et
al., 2026; Muppidi et al., 2025). One 5401-second hung NIM attempt that
prevents fallbacks produces *less* scan evidence than two bounded NIM
attempts plus a skipped retired family.

CWE-770 forbids allocating a shared resource without an independent
limit (MITRE, 2026). The 1800-second NIM process cap is that limit: one
hung hosted attempt cannot consume the remaining 5700-second scan budget
and starve later NVIDIA candidates or the fail-closed evidence path.

## Trust boundary

The brownout classifier uses the same same-line discipline as the NVIDIA
catalog-404 classifier. Scanner stdout can include target-repository
text; requiring the retirement code, GitHub Models context, and 410 on
one physical line prevents application `410 Gone` pages from skipping
the fallback family. Incomplete scans remain fail-closed until a
distinct model produces complete evidence or the outer workflow sees
backend-unavailable signal with no vulnerability marker.

`NVIDIA_NIM_API_KEY` remains the public-scan credential. Review-agent
secrets and `COPILOT_GITHUB_TOKEN` are unchanged.

## References

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics*
(RFC 9110). Internet Engineering Task Force.
https://doi.org/10.17487/RFC9110

MITRE. (n.d.). *CWE-1288: Improper validation of unsafe equivalence in
input*. Retrieved August 13, 2026, from
https://cwe.mitre.org/data/definitions/1288.html

MITRE. (2026). *CWE-770: Allocation of resources without limits or
throttling*. https://cwe.mitre.org/data/definitions/770.html

Muppidi, S., Jagmohan, A., Vempaty, A., Luss, R., Dognin, P., Riemer,
M., Sattigeri, P., Murugesan, K., Padhi, I., Swaminathan, S., Rawat, A.,
Ganhotra, J., Ganti, R., Ghalwash, M., Baldini, I., Tchrakian, T., Daly,
E., Uceda-Sosa, R., & Varshney, K. R. (2025). *TRINITY: An evolved
foundation model perspective* (arXiv:2512.04695). arXiv.
https://doi.org/10.48550/arXiv.2512.04695

Narimani, H., Salmani, E., Salmani, S., Rezaei, H., & Ramezani, V.
(2026). *Fugu: A language model routing architecture* (arXiv:2606.21228).
arXiv. https://doi.org/10.48550/arXiv.2606.21228

NVIDIA Corporation. (2026). *Llama-3.1-Nemotron-Ultra-253B-v1* [Model
card]. NVIDIA NIM.
https://build.nvidia.com/nvidia/llama-3_1-nemotron-ultra-253b-v1/modelcard

Zhang, X., Chen, H., Liu, Y., & collaborators. (2025). *Conductor:
Recursive test-time compute for multi-agent systems* (arXiv:2512.04388).
arXiv. https://doi.org/10.48550/arXiv.2512.04388
