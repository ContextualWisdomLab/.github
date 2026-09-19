# Repository README authoring template

Use this scaffold with the [README quality standard](../repository-readme-quality-standard.md).
It is an authoring aid, not finished customer copy or an organization-wide generator.
Keep each product's language, ownership, supported workflow, and license evidence.
Remove irrelevant sections rather than publishing empty headings.

## Before adapting

Choose one truthful starting path: a verified released package, an evaluated source
worktree, or a design/contract foundation. Do not give all three equal prominence
when only one exists. For a source path, state the working directory, actual
runtime prerequisite, lock/install command, and expected next action. For a
foundation, replace install commands with a real contract/validation entry point.

Replace every `{{...}}` field from current evidence. Do not publish the scaffold,
these instructions, placeholder links, or guessed output. The text-fenced fields
below are intentionally not executable. Promote them to a language-tagged code
example only after the repository's actual command has been checked and, where
possible, run safely. Record an unexecuted example as unverified in the PR rather
than inventing a successful run. No badge, license, benchmark, or support channel
is selected by this template.

## Copyable scaffold

<!-- readme-template:start -->
````markdown
# {{product_name}}

**{{one_sentence_user_outcome}}**

{{who_this_helps_and_the_problem_it_solves}}

[Get started](#get-started) · [Documentation](#documentation) · [Support](#support-and-contributing)

## What you can do

{{two_or_three_current_user_jobs_with_concrete_results}}

{{important_limitation_that_changes_a_users_next_action}}

## Get started

{{release_or_source_or_foundation_status_and_prerequisites}}

```text
{{verified_working_directory_and_setup_commands}}
```

{{observed_result_and_next_action}}

{{network_data_permission_cost_and_stop_or_cleanup_notes}}

## Example

{{one_representative_task_and_its_input_requirements}}

```text
{{verified_public_api_or_cli_example}}
```

{{bounded_expected_result_and_failure_recovery}}

## How it fits

{{short_data_flow_and_optional_integrations_in_user_language}}

{{what_this_product_owns_and_what_remains_with_the_host_or_source_system}}

## Status and verification

{{current_maturity_and_link_to_actual_release_or_verification_evidence}}

```text
{{repository_supported_verification_commands}}
```

{{tested_scope_and_remaining_limits_without_global_quality_claims}}

## Documentation

| I need to... | Start here |
| --- | --- |
| {{first_reader_job}} | [{{document_title}}]({{existing_document_path}}) |
| {{second_reader_job}} | [{{reference_title}}]({{existing_reference_path}}) |

## Support and contributing

{{existing_support_and_private_security_reporting_routes_or_their_explicit_limits}}

{{smallest_contributor_verification_contract_and_link_to_details}}

## License

{{verified_license_statement}}

{{third_party_notice_links_and_relevant_distribution_limits}}
````
<!-- readme-template:end -->

## Presentation choices

Use a clear title, one strong opening sentence, short paragraphs, and a compact
navigation line. Keep badges few and relevant, and link each to real evidence.
Avoid walls of logos, decorative shields, HTML layout tables, unsupported
superlatives, and embedded internal incident dashboards. Long tables and exhaustive
CLI flags belong in linked references. Check heading navigation and code wrapping
at a narrow viewport as well as on desktop.

A screenshot can establish what a real interface looks like, not that every
feature works. Include only an actual, reviewed product view with useful alt text,
no personal data or secrets, and an identifiable source revision in its retained
evidence. Omit screenshots when the product has no visual interface.

## Adaptation and handoff record

Keep the record in the PR or doctoring, not in the customer README. Bind each
material claim to its owning source and exact revision. For quick start, record
working directory, runtime/lock identity, command, observed result, side effects,
and stop/recovery. For a claim you could not execute, say **Not executed** and
state the missing capability. For licensing, separate first-party grant from
inherited source, dependencies, assets and service terms; metadata is inventory,
not rights approval. Retain required attribution rather than hiding an intake
conflict.

Validate relative links against the proposed tree and the actual publishing root.
Generated READMEs require updating their authoring source and checking generated
output. Keep the existing authoritative PR and prove every valid delta survives
any consolidation. A queued check, external blocker, or saved draft is not delivery.
