# Scheduler Unicode Git refs

## Incident and buyer impact

The merge scheduler rejected GitHub-valid branch names such as
`🎨-palette-ux-improvement-13325911538352561627` because `validate_git_ref`
used an ASCII-only regular expression. International product branches never
reached dispatch.

## Decision

Permit non-ASCII graphic and letter characters. Continue to reject ASCII
shell metacharacters and whitespace; Unicode control, format, and separator
categories; leading dashes; reserved `HEAD`; `@{`; traversal and hidden
components; trailing dots or slashes; and component `.lock` suffixes. All
Git and GitHub calls stay structured argv/API fields.

## References

Chacon, S., & Straub, B. (2014). *Pro Git* (2nd ed.). Apress.
https://git-scm.com/docs/git-check-ref-format

The Unicode Consortium. (2024). *The Unicode Standard* (Version 16.0.0).
https://www.unicode.org/versions/Unicode16.0.0/
