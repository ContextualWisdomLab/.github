# Agent Protocol — Operating the CWL GitHub Project (read / create / update)

**Any LLM agent (Claude, Codex, Grok, Gemini, …) manages roadmap/work state by DIRECTLY operating the org GitHub Project — not a private memory, not a static file.** GitHub Projects (v2) is the shared, durable, cross-agent source of truth; every agent reads AND writes it with the `gh` CLI (or the GraphQL API). This document is the binding convention for how.

## The Project

| key | value |
|---|---|
| Title | naruon Platform Roadmap |
| Owner | `ContextualWisdomLab` (org) |
| Number | `1` |
| URL | https://github.com/orgs/ContextualWisdomLab/projects/1 |
| Project node id | `PVT_kwDOEZWuYc4BczHJ` |
| Full product spec | `ContextualWisdomLab/naruon` → `docs/planning/naruon-platform-plan.md` (PR #974) |

### Fields (ids are stable; re-discover with `field-list` if a field is added)
| field | id | type | options (name:id) |
|---|---|---|---|
| Status | `PVTSSF_lADOEZWuYc4BczHJzhXZRaw` | single-select | `Todo:f75ad846` · `In Progress:47fc9ee4` · `Done:98236657` |
| Title | `PVTF_lADOEZWuYc4BczHJzhXZRao` | text | — |

## Auth (once)
Needs a token with the `project` scope. `gh auth refresh -s project,read:project` (or a PAT with `project`). Codex/Grok/Gemini invoke the same `gh` binary.

## READ (always do this first — don't guess state)
```bash
# all items with their fields (status, title, linked content) as JSON
gh project item-list 1 --owner ContextualWisdomLab --format json --limit 100
# field definitions + option ids (run if ids above look stale)
gh project field-list 1 --owner ContextualWisdomLab --format json
# a single project's metadata (node id, url)
gh project view 1 --owner ContextualWisdomLab --format json
```

## CREATE a work item
```bash
gh project item-create 1 --owner ContextualWisdomLab \
  --title "<concise imperative title>" \
  --body  "<what/why + acceptance criteria; reference CP-1..CP-5/G6/SEAM disciplines and the spec>"
# to add an EXISTING issue/PR instead of a draft:
gh project item-add 1 --owner ContextualWisdomLab --url <issue-or-pr-url>
```

## UPDATE status (the core operation)
```bash
# item id comes from item-list; field/option ids from the tables above
gh project item-edit \
  --id <ITEM_NODE_ID> \
  --project-id PVT_kwDOEZWuYc4BczHJ \
  --field-id PVTSSF_lADOEZWuYc4BczHJzhXZRaw \
  --single-select-option-id <f75ad846|47fc9ee4|98236657>   # Todo | In Progress | Done
# edit a text field (e.g. Title):
gh project item-edit --id <ITEM_NODE_ID> --project-id PVT_kwDOEZWuYc4BczHJ \
  --field-id PVTF_lADOEZWuYc4BczHJzhXZRao --text "<new title>"
```
GraphQL equivalent (if `gh project` is unavailable): `updateProjectV2ItemFieldValue` mutation with the same project/item/field ids.

## LINK a PR/issue to an item
Add the PR/issue as its own item with `item-add`, or reference the item in the PR body. The "Linked pull requests" field auto-populates for added PRs.

## Conventions (binding)
1. **Read before write.** Always `item-list` first; never assume an item's current status.
2. **Status semantics.** `Todo` = not started / ready. `In Progress` = an agent is actively working it (set it when you start, so other agents don't collide). `Done` = merged/verified. (There is no "Blocked" option yet — prefix a blocked item's title with `BLOCKER:` and keep it `Todo`, or an admin can add a `Blocked` option to the Status field.)
3. **One phase at a time.** Phases P0→P5 are ordered; do NOT move multiple phases to `In Progress` and fan out parallel PRs. Take one phase as a coherent, verified increment on the previous phase's merged foundation. (This is a standing correction — see the roadmap discipline.)
4. **Don't productionize stopgaps.** Build the real target behind a stable extractor/plugin seam; current deterministic extraction / `to_tsvector` FTS / half-built multi-account model are scaffolding, not things to cement.
5. **Decisions & blockers stay visible** as items until resolved; append resolution to the item body and set `Done`.
6. **Collision avoidance (multi-agent).** Before starting an item, set it `In Progress` and put your agent name + timestamp in a body note; if it's already `In Progress` by another agent, pick a different item.
7. **The Project is the truth**, the naruon spec doc is the detail, and (eventually) naruon's own KG dogfoods this. Keep the Project current; do not maintain a competing private list.

## Why (not a static mirror)
Other agents CAN read the Project directly via `gh`/GraphQL — so the right move is a shared operating convention on the LIVE project, not a static markdown copy that goes stale. This file is the convention; the data lives in Project #1.

## Cross-repo references (BINDING)

When referencing an issue or PR that lives in ANOTHER repository, ALWAYS use a linkable form so GitHub creates a real cross-reference (and it shows in the target's timeline):
- `owner/repo#num` — e.g. `ContextualWisdomLab/naruon#974`
- or a full URL — e.g. `https://github.com/ContextualWisdomLab/naruon/pull/974`

NEVER write plain text like `naruon PR #974` — it does NOT link and breaks traceability. A bare `#num` only links within the SAME repo. This applies to issue/PR bodies, comments, commit messages, and Project item bodies. (Same-repo references may use `#num`.)
