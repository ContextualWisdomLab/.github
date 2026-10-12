# Supersession check: ContextualWisdomLab/.github#2247 vs #2249 / #2252 / main

- **Date:** 2026-09-18
- **Verdict:** KEEP OPEN — unique residual remains. Do **not** close as superseded.
- **Merge:** neither #2247 nor #2249 merged (no `reviewDecision=APPROVED` + SUCCESS).

## Three-dot vs `origin/main`

| PR | Head | Three-dot paths |
|---|---|---|
| #2247 | `1c01a7265e188134ead05fef0fa0e64423631c3e` | `docs/doctoring/schedule-queue-post-2242-admission-levers-20260917.md` (+117) |
| #2249 | `9f0378252e0bf12490d9bbe260b1d399fc982a53` | coalesce fail-open doctoring + workflow/core/tests (different scope) |
| #2252 | `f4f7299455616308838e66806bf541a8ebd75ccf` | `docs/doctoring/actions-queue-wait-24h-remeasure-post-2244-20260917.md` (+173) |

Commands:

```bash
git fetch origin main
git diff --stat origin/main...1c01a7265e188134ead05fef0fa0e64423631c3e
git show origin/main:docs/doctoring/schedule-queue-post-2242-admission-levers-20260917.md
# → fatal: path does not exist in 'origin/main'
```

## Carryover search (absent ⇒ residual)

Unique #2247 strings absent from `origin/main`, #2249 head, and #2252 head:

- path `docs/doctoring/schedule-queue-post-2242-admission-levers-20260917.md`
- `Dedicated / alternate hosted`
- `Relabeling does not create`
- run ids `35249946503`, `35225408296`, `35258328418`
- `investigated levers do not open`

```bash
git grep -lF "35249946503" origin/main --   # empty
git grep -lF "35249946503" 9f0378252e0bf12490d9bbe260b1d399fc982a53 --  # empty
git grep -lF "35249946503" f4f7299455616308838e66806bf541a8ebd75ccf --  # empty
```

## What successors do (not supersession)

- **#2249** *cites* `#2247` / the admission-levers filename for the ~97m delivery-lag figure and grounds fail-open N=600; it does **not** add the doctoring file or the lever-rejection table / schedule-run samples.
- **#2252** notes that no separate `schedule-queue-post-2242-admission-levers*` file existed at its measurement time and has a thinner coalesce/admission residual table; it does **not** carry #2247's lever verdicts or rebase/SBOM/metadata run samples.

## Residual (keep #2247 for)

1. Full doctoring record with live schedule-queue samples (PR Auto Rebase `35249946503`, SBOM `35225408296`, metadata `35258328418`) at `18:31Z`.
2. Explicit **rejected** levers: dedicated hosted labels, new concurrency, re-introducing step-scoped gate.
3. Audit trail that #2249's N=600 argument cites as primary evidence for the ~97m gap.

Redundancy of *topic* (schedule saturation / coalesce) is not complete successor carryover per `AGENTS.md`.
