# CWL Master Context — read this first (context-reset reconstruction brief)

> Purpose: a single, durable, agent-readable brief so ANY agent (Claude with a fresh context, Codex, Grok, Gemini) can reconstruct and continue this work WITHOUT the originating conversation. Private assistant memory is NOT the source of truth — this repo is. Keep this file current.
>
> Durable sources of truth (in priority order): (1) **GitHub Project #1** "naruon Platform Roadmap" https://github.com/orgs/ContextualWisdomLab/projects/1 — live work/roadmap; (2) **naruon `docs/planning/naruon-platform-plan.md`** (PR ContextualWisdomLab/naruon#974) — full IA/User-Stories/Use-Cases/Architecture spec; (3) **`docs/agent-github-project-protocol.md`** (this repo, PR #363) — how agents operate the Project + cross-repo-ref convention; (4) this file.

## 1. Mission (Contextual Wisdom Lab / 맥락지혜 연구실)
Turn scattered enterprise context into **judgment-ready structure, then action**. The problem isn't lack of information — it's that the *context to judge is scattered* ("정보 부족이 아니라 판단할 맥락이 흩어져 있다 / 구슬이 서 말이어도 꿰어야 보배"). **Synthesis, not summary.** DIKW as checkpoints: records → contextualize → judgment point → action. Reduce human cognitive load ("사람이 덜 소모"). Judgment stays with the human.

## 2. naruon = the PLATFORM (one platform, many à-la-carte plugins)
`naruon` is an email-first workspace (FastAPI backend + Next.js frontend + a thin WebSocket connector proxying IMAP/SMTP/CalDAV/WebDAV from customer premises) whose core is a **dense two-tier knowledge graph** over Postgres + pgvector. It is a **TRUE plugin platform** ("진정한 plugin처럼 계속 붙일 수 있는"): plugin manifest/contract, extension points (ingest sources, DOM/analysis processors, KG enrichers, work-item types, UI panels, agents, scheduling), plugin registry, versioned API, isolated execution for untrusted plugins (noema quarantine sandbox). **À-la-carte / opt-in**: each capability is a plugin a user enables by need; nothing mandatory; different users run different combos. Every imported component is **standalone AND submodule** ("따로, 또 같이").

## 3. Ecosystem components (product names + roles)
Product renames (repo slug → product name; domains purchased): `cwl-idp`→**keyverse** (keyverse.io), `waf-ids-ai-soc`→**wardnet** (wardnet.io), `cwl-editor`→**inkspan** (inkspan.io). Other domains: cloud-erd.app (pg-erd-cloud), naruon.net / naruon.io (naruon).
- **naruon** — the platform (email/PIM/KG). Verticals + capabilities plug in.
- **bandscope** (BandScope) — a **vertical**: local-first desktop rehearsal app for MUSICIANS (Tauri+React+Python). Its users also use naruon for email → they plug into the platform. (NOT a naruon fork.)
- **wardnet** (was waf-ids-ai-soc) — WAF / IDS / **AI SOC** / software LB / APIM.
- **keyverse** (was cwl-idp) — central passwordless IdP: OIDC/OAuth2.1/FIDO2/SCIM/SAML(ADFS)/LDAP; eliminate passwords; federates external IdPs (incl. the employer ADFS via feelanet-adfs) + account linking / cross-IdP user merge. Built on **Keycloak (Apache-2.0)** — ZITADEL was removed (AGPL-3.0, not permissible). NO admin-console operation — config-as-code / Admin REST API only.
- **inkspan** (was cwl-editor) — commercial-grade Markdown + HTML WYSIWYG editor (TipTap/ProseMirror, MIT) with base64-inline images (LLM-readable) + a standalone base64 converter + bundled offline OFL fonts (Noto Sans KO/EN/JA/ZH/VI for air-gapped use). Feature: compose email in Markdown → HTML on send.
- **clearfolio** — document viewer (à-la-carte plugin).
- **pg-erd-cloud** (cloud-erd.app) — ERD tool for developers / data architects.
- **contextual-orchestrator** — LLM **token-cost optimizer + performance + upstream load balancer + routing hub** (LiteLLM-plus). Multi-dimensional cost review (account/service/upstream_api/model/team/group/company). Controls BATCH routing → **pg-llm-batch**.
- **pg-llm-batch** — standalone Apache-2.0 batch engine (Rust pg_tiktoken token counting + Postgres batch submit/poll/retrieve), extracted from `xtrmLLMBatchPython` (which stays PRIVATE forever — its history has live keys + employer-confidential Hyosung-ITX data; rotate those keys). The orchestrator controls its routing.
- **codec-carver** — STT / omni-modal speech+video codec (audio/video conversion for LLM input); speaker diarization + consented voiceprint; feeds auto meeting minutes.
- **fast-mlsirm** — LLM-as-a-Judge output **calibration** + measurement/evaluation-item quality; incorporate `aFIPC` Fixed-Item Parameter Calibration + `kaefa`-style item-fit optimal-model search (R IRT/psychometrics). GPU = GPGPU in the Rust core (wgpu, single numpy|rust backend axis).
- **semantic-data-portal (SDP)** — the higher **ontology / catalog / governance plane** ABOVE the doc KG (Apache AGE + pgvector). naruon owns the doc KG (content_graph + project_graph in Postgres); SDP is not that store.
- **noema** — agent runtime (Pydantic-AI / Codex-Python): a GitHub Review Agent in CI + a do-anything agent inside naruon + the **lightweight quarantine sandbox**.
- **newsdom-api** — PDF → DOM recognition sidecar (generalized beyond JP newspapers). naruon parses non-PDF formats (html/md/plaintext) into its content_graph.
- **scopeweave** — issue/WBS **management** + ITSM Service Request (two-layer: requester ticket ↔ team issues). Consumes issues naruon extracts from email/conversation/ITSR. (Dev-CODE issues stay in GitHub/GitLab — integrate, don't rebuild GitHub.)
- **appguardrail** — app security guardrails; collects org security/CI failures + Strix findings as issues.
- Forks (fix UPSTREAM via a very detailed PR in the upstream's language): argos, vooster (+v2), and R pkgs. `xtrmLLMBatchPython` PRIVATE.

## 4. Personas + killer demo
- **P1** = the org lead (the user): data architect + data Product Manager + data expert + **AI System Architect**, in an AI business team → needs legal/regulatory (법령) review; uses cloud-erd.app. Expects rigor on data modeling/ERD/schema.
- **P2** = his girlfriend (KILLER demo): works in a **Digital Trust / security team on personal-data-protection (개인정보보호)** AND plays in **N amateur workplace bands** → heavy BandScope + naruon user. She forgets her schedule and double-books band rehearsals over prior commitments (incl. dates) → naruon aggregates calendars + extracts commitments to the KG + detects conflicts + reminds, privacy-preserving. Proves platform+verticals AND security/privacy as first-class.

**Org hierarchy (structural, not flavor — the norm-groups, approval chains, scheduling, and privacy bridge all route through it):** each persona sits in **company → team → under a team lead (팀장)**.
- P1: AI System Architect in an **AI business team (AI사업팀)** at his employer; reports to his team lead; needs legal/regulatory review.
- P2: in a **Digital Trust / security team (보안팀, 개인정보보호)** at her employer; reports to her team lead; ALSO a member of **N bands, each with its own band leader** (each band = a distinct norm-group with a lead).
These give concrete instances of: **norm-groups** (company, team, band×N — CP-3 multi-membership); **approval chains** (leave/travel 전자결재 flows through the team lead → CP-4 anticipatory coordination); **scheduling** (team meetings called by the team lead → RSVP/conflict); **privacy bridge** (a personal fact discloses only its *consequence* — "unavailable" — to the team lead/team, never the reason → CP-5); and **org-affiliation over time** (current vs former employer → content-based classification, CP-5). So the KG models **Person, Company/Org, Team, Role {team_lead | member}, Band(+leader), NormGroup**, with edges member_of / reports_to / leads / active-tenure.


## 5. Cross-cutting disciplines (ACCEPTANCE CRITERIA, bind every feature)
- **CP-1 DIKW spine**: KG is the product, inbox is an ingest edge; synthesis over summary; reduce cognitive load.
- **CP-2 No-ask / dense-KG auto-resolution**: NEVER ask the user a disambiguation question (asking re-imposes the scattered-context load the product removes). A dense, multi-dimensional KG holds the evidence to auto-resolve (e.g. hotel location vs event venue, host=partner vs colleague, commitment status, travel time). Surface the RESOLVED connection + recommended action + evidence + calibrated confidence; the human **corrects by exception**, never answers a question. Even "pick an option" is a residue of asking. Irreversible/external actions (send/book/approve) still terminate at a human approve/hold, delivered as a correction surface. Connecting context IS the mission — never gate it behind a permission question; KG DENSITY replaces the question.
- **CP-3 Ecological-fallacy discipline**: infer at the correct level of analysis; group/norm-group rates are PRIORS updated by individual content to a POSTERIOR; never impute group→individual (or reverse). One person belongs to **N simultaneous OVERLAPPING norm/reference groups** (multi-MEMBERSHIP graph, not a tree); norms are group-relative; resolve the active norm-group(s) before acting. Honest calibrated confidence.
- **CP-4 Commitment-status weighting**: every commitment has status {confirmed | tentative | desired} + RSVP direction {organizer | attendee}. Conflict detection is STATUS-WEIGHTED (confirmed > tentative > desired). A desired item (an RSVP I'm sending) over a confirmed slot (a paid booking) = conflict the confirmed side wins; NEVER silently break a confirmed commitment. e-Approval (전자결재: leave/travel/expense) outcomes are first-class KG events linked to the events they enable (anticipatory coordination). Worked examples in naruon#974 §6 (UC-01..05).
- **CP-5 Privacy: default-segregated + consent minimal-disclosure bridge**: contexts (personal / work→{former employer, current employer} / per-project / per-band) segregated by default, classified by CONTENT not account. A private fact affects another context ONLY via its necessary CONSEQUENCE (e.g. "unavailable Tue–Thu") — NEVER the private reason (e.g. "hospitalized"). NOT a hard wall — a consent-gated, revocable, audited, minimal-disclosure BRIDGE; user controls disclosure level. Multi-account binding (N email accounts → one identity), content-based classification. Email-to-self (from==to) = personal storage/notes → KG reference nodes, not interpersonal communication.
- **G6 Language-agnostic**: extraction/resolution/search consistent across EN/KO/JA/ZH/VI via LLM extraction + multilingual embeddings + cross-lingual structured topic modeling (STM). NO dependency on morphological analyzers (Kiwi/Nori) — they cause performance cliffs (refs 1week.tistory.com/119-122). **FTS language resolution**: naruon's current `to_tsvector` FTS is language-DEPENDENT and fails CJK (tokenizer cliff) — DROP per-language configs; use dense multilingual embeddings (primary) + language-agnostic sparse (pg_trgm/pg_bigm char n-grams, PostgreSQL-licensed, AND/OR learned-sparse SPLADE-style as pgvector sparsevec) fused via RRF; unaccent+NFC for Vietnamese.
- **SEAM Don't productionize stopgaps**: naruon's current deterministic extraction, to_tsvector FTS, and half-built multi-account model are SCAFFOLDING. Build the real target behind a stable extractor/plugin SEAM (orchestrator-routed LLM-based, language-agnostic); current code = reference/fallback, not the thing to cement.

## 6. AI SOC = wardnet + noema quarantine sandbox (see wardnet#38)
A **source-agnostic artifact-analysis service**: `submit(artifact, context) → {verdict, confidence, evidence, IOCs}`. Consumers: naruon email/file attachments (quarantine BEFORE store), platform uploads, connector inputs, API, GitHub issue/PR comments (one trigger). WITHOUT VirusTotal (self-contained): static (YARA(BSD) + capa(Apache) capability→ATT&CK + LIEF/pefile + unzip/macro extract + entropy + context heuristics) + dynamic detonation in a gVisor/Firecracker (Apache) microVM with eBPF behavioral monitoring (Falco/Tetragon, Apache) + network sinkhole + **LLM reasoning (via contextual-orchestrator) over the evidence** + KG/IOC correlation (self-hosted growing reputation). Auto-response per consumer (GitHub → delete comment + block user; email → quarantine + flag; upload → reject + notify). Validated by a real incident 2026-07-08 (user mapasevo21 posted a `sarif_bypass_patch.zip` malware lure on .github#365 + naruon#977 — deleted + blocked manually; this is what the SOC would automate).

## 7. Engineering conventions (BINDING, all agents)
- **Commercial/permissive licenses ONLY** — MIT/Apache-2.0/BSD/ISC/MPL-2.0/PostgreSQL. NO GPL/AGPL/copyleft/non-commercial. Verify via `gh api repos/<o>/<r> --jq .license.spdx_id` before adding. (ZITADEL=AGPL removed; MinerU=Apache OK; ParadeDB pg_search=AGPL avoid; ClamAV=GPL avoid.)
- **DB object names = 2+ word snake_case** (don't rename existing Camel/Pascal).
- **Config/secrets from a KV/credential store, NOT os.getenv** (env only as bootstrap transport).
- **Attach relevant paper PDFs in PRs** (permissive redistribution only).
- **Use CodeGraph maximally** (build an index on a clone, then explore, before grep; cite queries).
- **Do NOT ask the user to decide** — make the call and proceed (full autonomy).
- **Cross-repo references** must be `owner/repo#num` or a full URL (never plain "naruon PR #974", which doesn't link). Same-repo may use `#num`.
- **One phase at a time** — execute ONE coherent verified increment per roadmap phase on the previous phase's MERGED foundation; do NOT fan out all phases as parallel PRs (that scatter saturated the runners). Don't announce phases you then don't execute in order.
- **Durable knowledge lives in the repo / Project / KG (dogfood), NOT in an agent's private memory.**
- Interconnected products are developed **PUBLIC** (after a full-history secret scan; xtrmLLMBatchPython excepted — stays private).

## 8. Roadmap (full detail: naruon#974 §9; live status: Project #1)
- **P0 MVP** — make the dense KG real (behind a stable extractor seam; do NOT productionize the deterministic stopgap; reconcile multi-account model; extend hybrid search to content_segments + project_graph_objects; wire DecisionPointCard).
- **P1 Platform/Plugin SDK** — registry, versioned API, hook bus, manifest/license/signature gate, noema quarantine sandbox, /plugins UI.
- **P2 Dense-KG inference** — LLM-based language-agnostic extraction (orchestrator-routed) + batch embeddings; typed entities (graph_persons/events/commitments, norm_groups + memberships); prior×likelihood posterior; no-ask auto-resolve + correct-by-exception.
- **P3 Scheduling & conflict avoidance** — status-weighted conflict engine; iTIP/iMIP RSVP (organizer vs attendee); free-busy find-time; room booking; anticipatory 전자결재→travel; connector CardDAV + POP3-over-WS.
- **P4 Privacy bridge** — context isolation + content-based classification; consent minimal-disclosure bridge.
- **P5 Verticals** — BandScope, pg-erd-cloud, scopeweave, Inkspan, codec-carver (audio minutes+voiceprint), legal/contract, code-integration — all à-la-carte plugins on the P1 SDK.
- Cross-cutting: OpenTelemetry error tracking across naruon + the connector (self-hosted-runner-style Email/CalDAV/WebDAV/CardDAV proxy); AI-authored Office docs (python-docx/openpyxl/python-pptx); real-time collab (TipTap+Yjs); naruon email signatures; KG-mediated email style correction; project wiki (KG); requirements/RFI/RFP, WBS/estimation, planned-vs-actual gap (early/on-time/delayed/not-performed/skip), Phase/Activity/Task/Duty (=Job/Work/Task/Duty), Waterfall↔Agile (scopeweave).

## 9. How work is tracked (dogfood the traceability)
GitHub **Project #1** is the shared source of truth. Structure: real **Issues** (roadmap/backlog, in owning repos, custom fields Phase P0–P5/Ops/Decision + Component) and real **PRs** (delivered work, native Repository). Native workflows are ON (item added→Todo, PR merged→Done, item closed→Done). Chain: roadmap **Issue** → agent sets In Progress on pickup → implementing **PR** `Closes #N` → merge → auto Done. Operate the Project per `docs/agent-github-project-protocol.md`. Group by Phase / Component / Repository.

## 10. Current state (2026-07-08)
- Renames done (keyverse/wardnet/inkspan). Planning spec = naruon#974. Project #1 populated (68 issues + 60 PRs). Protocol = .github#363.
- **BLOCKER B1**: org GitHub Actions effectively HALTED (~86 queued, ~0 in_progress org-wide) — likely the Actions monthly SPENDING CAP. Blocks ALL PR checks/merges + the Cloudflare DNS run (nameservers). Fix (org-admin): raise the Actions spending limit OR add a self-hosted runner. Nothing merges until then.
- **Decisions pending**: (D1) Code Security enablement vs the CodeQL-only code_scanning ruleset (osv/trivy/scorecard SARIF upload) — a private repo needs GHAS seats; reconcile or make those checks non-required. (D2) trivy `limit-severities-for-sarif: true` (gate only CRITICAL/HIGH) — held pending the user's strict-security preference.
- **Built this session, PR-open, awaiting merge (B1)**: see Project #1 PRs (contextual-orchestrator cost/routing #46 + naruon#973; pg-llm-batch; keyverse Keycloak; inkspan; SBOM #361; opencode auto-retry #360; Strix neutral #349 + emit #358; appguardrail collector #254; auto-rebase #357; noema #359/naruon#970; PDF-DOM naruon#965/newsdom#300; SDP #11; fast-mlsirm GPGPU #109; scopeweave #284/naruon#971; fuzzing 10 PRs (found+fixed 2 real naruon bugs); Cloudflare DNS/Pages #362; this protocol #363; planning #974). Human step: report the mapasevo21 malware file (github user-attachments) to GitHub Abuse; rotate the xtrmLLMBatchPython-leaked keys; the org-admin runner/decisions above.

---
*Keep this current. Update Project #1 as the live tracker; this file is the narrative brief a fresh agent reads to reconstruct the whole picture.*

## Inter-component architecture (UML)

Component / interaction diagram of how the ecosystem connects. `naruon` is the platform core; à-la-carte plugins + verticals attach; `contextual-orchestrator` is the LLM plane; `keyverse` is auth; `wardnet` is the edge + AI SOC.

```mermaid
flowchart TB
  P1["👤 P1 — data / AI System Architect (org lead)"]
  P2["👤 P2 — Digital-Trust musician (killer demo)"]

  subgraph EDGE["Edge & security"]
    WARD["wardnet — WAF / IDS / AI SOC / LB / APIM"]
  end
  subgraph IDENT["Identity (passwordless)"]
    KEY["keyverse — IdP: OIDC/OAuth2.1/FIDO2/SCIM/SAML/LDAP (Keycloak)"]
    ADFS[("feelanet-adfs / external ADFS · LDAP")]
  end

  subgraph PLATFORM["naruon PLATFORM"]
    NAR["naruon — email/PIM + KG (content_graph + project_graph)"]
    CONN["connector — self-hosted Email/CalDAV/WebDAV/CardDAV proxy"]
  end

  subgraph LLM["LLM plane"]
    ORCH["contextual-orchestrator — cost/routing/LB gateway"]
    BATCH["pg-llm-batch — batch engine (Rust pg_tiktoken)"]
    UP[("upstream LLM providers")]
    FM["fast-mlsirm — LLM-as-Judge calibration (aFIPC/kaefa)"]
  end

  subgraph DATA["Knowledge / data"]
    SDP["semantic-data-portal — ontology/catalog plane"]
    NEWS["newsdom-api — PDF → DOM"]
    PG[("Postgres + pgvector + Apache AGE")]
  end

  subgraph PLUGINS["À-la-carte plugins & verticals (opt-in)"]
    INK["inkspan — Markdown/HTML editor (+base64, OFL fonts)"]
    CLR["clearfolio — document viewer"]
    ERD["pg-erd-cloud — ERD tool"]
    SCOPE["scopeweave — issues / WBS / ITSM"]
    CODEC["codec-carver — STT / audio→minutes (+voiceprint)"]
    BAND["bandscope — musicians' rehearsal vertical"]
    NOEMA["noema — agent runtime + quarantine sandbox"]
  end

  subgraph INFRA["Infra / governance"]
    CF[("Cloudflare — Pages/Workers/DNS")]
    GH[(".github — governance + Project #1")]
  end

  P1 --> WARD
  P2 --> WARD
  WARD --> NAR
  P1 -. "auth" .-> KEY
  P2 -. "auth" .-> KEY
  NAR -. "authn/z (OIDC)" .-> KEY
  KEY -. "federates in" .-> ADFS

  CONN -->|"ingest mail/cal/files"| NAR
  NEWS -->|"PDF DOM"| NAR
  NAR --> PG
  NAR --> SDP
  SDP --> PG

  NAR -->|"LLM: extract / embed / reason"| ORCH
  NOEMA --> ORCH
  WARD -->|"SOC: LLM reasoning on evidence"| ORCH
  ORCH --> UP
  ORCH -->|"batch routing"| BATCH
  BATCH --> PG
  FM -. "calibrates judge outputs" .-> ORCH

  NAR --> INK
  NAR --> CLR
  NAR --> ERD
  NAR -->|"extracted issues → manage"| SCOPE
  CODEC -->|"diarize + minutes"| NAR
  NAR --> NOEMA
  WARD -->|"quarantine detonation"| NOEMA
  BAND -->|"musicians also use email"| NAR
  BAND -. "rehearsal app" .-> P2

  NAR -. "OpenTelemetry" .-> GH
  CONN -. "OpenTelemetry" .-> GH
  NAR --> CF

  classDef core fill:#1f6feb,stroke:#0b3d91,color:#fff;
  classDef plane fill:#6e40c9,stroke:#3d1f7a,color:#fff;
  class NAR core;
  class ORCH,KEY,WARD plane;
```

**Reading it:** users hit `wardnet` (edge/SOC) → `naruon` (platform); everything authenticates via `keyverse` (which federates external ADFS/LDAP). `naruon` ingests via the `connector` + `newsdom-api`, builds the KG in Postgres, uses `semantic-data-portal` for the ontology plane, and routes ALL LLM work through `contextual-orchestrator` (which load-balances upstreams and routes batch to `pg-llm-batch`). `noema` is the shared agent runtime + quarantine sandbox (used by naruon, the GitHub review agent, and wardnet's AI SOC). Plugins/verticals (`inkspan`, `clearfolio`, `pg-erd-cloud`, `scopeweave`, `codec-carver`, `bandscope`) attach à-la-carte; `fast-mlsirm` calibrates LLM-as-Judge quality. Hosting = Cloudflare; governance + Project #1 live in `.github`.
