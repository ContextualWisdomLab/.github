# README authoring template and delivery contract

## Problem

The README mission requests a reusable writing template, but the existing standard
at `bd56a9cc599e60be1b5d2a9729dea36b0e215e9f` explicitly excluded a template.
It also described a remaining external blocker as an alternative completion
condition. A checklist was useful, but neither sentence satisfied the requested
writing-and-integration outcome.

## Decision

Keep the existing standard and its product-owned language, provenance, licensing,
and ordinary-merge controls. Add `docs/templates/repository-readme-template.md`
as an adaptable authoring scaffold. Require command working-directory, runtime,
lock, result, side-effect and stop/recovery evidence. An unexecuted example must
be identified as such; an external blocker leaves delivery incomplete.

The scaffold supplies a title/promise, task-oriented introduction, quick start,
example, integration context, status/verification, document navigation, support
and license section. It supplies no real package, command, endpoint, badge,
benchmark, source license or customer claim. Authors replace placeholders only
from repository evidence and omit irrelevant sections. Nothing automatically
copies the template into product repositories or changes their runtime contracts.

## Alternatives and risks

A checklist alone was rejected because it leaves the requested reusable writing
structure absent. A mass README generator was rejected because repository-specific
product authority, release state and third-party obligations are not interchangeable.
A blocked PR must retain its ownership and valid delta rather than be reported
complete or closed on a title/ancestry match.

The main misuse risk is publishing the scaffold literally or interpreting static
template tests as proof of a product's runtime behavior or license rights. The
instructions prohibit both. Real command execution, visual review when relevant,
source/provenance assessment, and exact-head integration evidence remain separate.

## Verification

The pre-change standard bytes matched Git blob
`3d3d5895ead0b4dfc8a94d7b651d6d7de68bb427`. The new unittest module was exercised
against that standard before the repair: template presence, discoverability,
execution fields and incomplete-blocker assertions failed. After the documentation
change, all four test methods pass locally under Python 3.13.5:

```sh
python -m unittest discover -s tests -p test_readme_template_contract.py -v
```

This is structural documentation evidence, not full repository CI, semantic
review, release evidence, or a sibling-product conformance claim. Protected
integration still requires the unchanged current head's applicable checks and
reviews. The existing `.github` MIT source grant is unchanged; this work adds no
third-party source, dependency, asset, or license exception.

## References

GitHub. (n.d.). *About READMEs*. GitHub Docs. Retrieved September 12, 2026, from
https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes

GitHub. (n.d.). *Licensing a repository*. GitHub Docs. Retrieved September 12,
2026, from
https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository

GitHub's README guidance supports purpose, getting-started, help and maintainer
navigation. Its licensing guidance supports keeping a real source grant distinct
from repository visibility. The stronger commercial-intake, exact-head and
complete-delta-delivery requirements here come from the repository owner's
explicit CWL mission, not an assertion that GitHub requires those policies.
