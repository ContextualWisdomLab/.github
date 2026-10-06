# SBOM Markdown data-integrity boundary

## Incident

The organization SBOM inventory treated repository names, component names,
versions, license expressions, API failure details, and the generation label as
trusted Markdown. Newlines, table delimiters, link brackets, code delimiters,
or raw-HTML delimiters in dependency metadata could therefore create forged
rows, headings, links, or presentation markup in the governance-facing report.
The machine-readable JSON remained structurally valid, but reviewers could be
misled by its human-readable companion.

## Decision

The renderer now passes every externally derived string through one bounded
text encoder before interpolation. It collapses CR/LF line structure and emits
numeric or named character references for ampersands, backslashes, table pipes,
angle brackets, brackets, backticks, URI punctuation, mention markers, and issue
reference markers. Encoding dots, colons, at-signs, and number signs, plus
asterisks, underscores, and tildes, additionally prevents emphasis and
strikethrough presentation. The existing punctuation encoding prevents GFM
bare URLs, email autolinks, GitHub mentions, and issue references
from becoming active while browsers still render the intended text. Counts and
fixed policy labels remain native values. The JSON inventory deliberately
retains the original data so machine consumers and incident investigators do
not lose evidence.

This is a rendering-integrity control, not license verification. A component
with an unknown or policy-relevant license remains flagged by the existing
policy logic after its display text is neutralized.

The report summary also publishes `error_count` and an explicit completeness
state. Missing repository SBOM evidence therefore cannot be interpreted as a
clean zero-finding inventory merely because the unavailable repository has no
components in the roll-up.

Repository unavailability uses `error is not None` in both the JSON summary and
Markdown per-repository rendering. An empty error string is still unavailable
evidence rather than an empty repository, so the human and machine channels
cannot disagree about completeness.

## Test-first evidence

`tests/test_sbom_markdown_integrity.py` first demonstrated that crafted SBOM
metadata produced a second-level heading and a forged table row. A follow-up
RED fixture proved that bare URLs, email addresses, mentions, and issue numbers
remained active without brackets. The accepted contract rejects active row,
heading, link, autolink, mention, issue-reference, and raw-HTML structure while
keeping the corresponding text visibly represented through character
references.

## Failure, recovery, and rollback

Unexpected display text should be compared with `inventory.json`, which is the
lossless evidence channel. Rollback requires an independently reviewed renderer
that proves all externally derived strings remain text in every Markdown
context. Removing the encoder or escaping only table pipes is not acceptable
because headings, links, code spans, and raw HTML are separate parse surfaces.

## APA 7th references

GitHub. (2019). *GitHub Flavored Markdown specification* (Version 0.29-gfm).
https://github.github.com/gfm/

MacFarlane, J. (2024, January 28). *CommonMark specification* (Version 0.31.2).
https://spec.commonmark.org/0.31.2/
