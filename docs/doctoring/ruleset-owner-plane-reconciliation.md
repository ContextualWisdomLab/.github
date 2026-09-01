# Ruleset owner-plane reconciliation

Date reviewed: 2026-09-02

## Incident and product impact

Orgmetra's protected `develop` is currently governed by organization ruleset `18156473`, while the central `.github` default branch also has repository ruleset `17921150`. Live reads on 2026-09-02 showed two policy drifts that block a defensible ordinary merge path: the organization ruleset still requires one generic approval even though the current operating model has one human maintainer and it retains `OrganizationAdmin/always`; the `.github` repository ruleset already has approval count zero but still permits rebase and also retains `OrganizationAdmin/always`.

The application connector can read those settings but does not expose ruleset mutation. Administrator bypass is not an acceptable substitute because it would destroy the canary needed to prove the normal path. The owner-plane repair therefore needs reviewed configuration-as-code plus a separately provisioned, narrowly scoped credential rather than an application-side shim.

## Design decision

`config/ruleset-governance.json` binds the reconciler to exactly two existing ruleset identities. `scripts/ci/reconcile_ruleset_governance.py` reads the full live object and refuses to act if the ID, name, source, source type, branch target, or active enforcement state has changed. It then preserves all unrelated conditions and rules while changing only these reviewed governance fields:

- remove routine bypass actors;
- set generic approving-review count to zero;
- keep same-author CODEOWNER review disabled;
- keep last-push approval disabled;
- require no synthetic reviewer identities; and
- allow merge and squash only, removing rebase.

GitHub's current REST contract does not support conditional unsafe REST updates such as `If-Match` on ruleset `PUT`; GitHub's general REST guidance explicitly says conditional unsafe methods are unsupported unless a specific endpoint documents otherwise, and the repository/organization ruleset update endpoints document no such precondition. The second full ruleset read is therefore a drift detector, **not** compare-and-swap. It catches edits visible before the final read but cannot make the final GET-to-PUT interval atomic. A successful HTTP update is also not completion: the reconciler performs a post-write full read and requires the complete editable payload to equal the reviewed update body.

Because the API cannot make that interval atomic, mutation is permitted only during exclusive owner-plane maintenance: a protected `ruleset-governance-maintenance` environment supplies the dedicated credential, the repository variable explicitly enables mutation, and one shared non-PR Actions concurrency group cancels superseded owner-plane runs. The workflow passes its exact protected `main` SHA into the reconciler; live `main` is checked before the final ruleset read, immediately before each PUT, and after convergence. If protected `main` advances, the stale run fails closed. These controls narrow and expose the residual API race rather than falsely claiming atomicity. Human administrators must not edit the two declared rulesets concurrently with an enabled maintenance run; if post-write state does not exactly converge, the run fails and requires a fresh live read before any retry.

Repository-local strengthening is attempted before the organization change so a cross-scope partial failure cannot first weaken the central repository surface.

Pull requests execute only offline manifest validation plus 100% statement/branch/docstring contract tests. Mutation can run only from trusted `main`, in the `ruleset-governance-maintenance` protected environment, when repository variable `CWL_RULESET_RECONCILE_ENABLED=true` is explicitly set, using dedicated secret `CWL_RULESET_ADMIN_TOKEN`. The normal workflow token remains `contents: read`, checkout credentials are not persisted, and API errors never echo subprocess output that could contain sensitive context.

`CWL_RULESET_ADMIN_TOKEN` is intentionally distinct from `CWL_REPOSITORY_METADATA_TOKEN`. GitHub documents organization-ruleset update as requiring organization **Administration (write)** and repository-ruleset update as requiring repository **Administration (write)**. The credential must carry only those permissions needed for the two declared targets; it must not be repurposed as a general development, merge, release, or metadata token. The protected environment secret is bootstrap transport into the `gh` REST client for this owner-plane process; it is not exposed to pull-request code or model processes. The environment and secret must be provisioned independently before `CWL_RULESET_RECONCILE_ENABLED` is set. Source integration alone does not prove that provisioning exists.

## Verification sequence

1. PR validation proves manifest, mutation projection, pre-write drift refusal, stale-protected-main refusal, redacted failures, post-write convergence, exact identity binding, trusted-main workflow gating, and 100% owned statement/branch/docstring coverage.
2. After source reaches protected `main`, provision the protected environment and dedicated credential, then enable the repository variable only for an exclusive owner-plane maintenance interval.
3. Run the reconciler and re-read both complete live ruleset payloads using the independently authorized credential.
4. Require organization ruleset approval count 0, last-push false, code-owner false, empty required reviewers, merge/squash only, no routine bypass, unchanged required workflows/conditions/deletion/non-fast-forward/thread-resolution controls.
5. Require repository ruleset approval count 0, last-push false, code-owner false, empty required reviewers, merge/squash only, no routine bypass, unchanged deletion/non-fast-forward/thread-resolution controls.
6. Revalidate the canonical audit writer and an unchanged downstream deterministic-GREEN canary such as Orgmetra #88; ordinary protected merge must work without self-approval, synthetic approval, or administrator bypass.
7. Keep the reconciler enabled for drift repair only if an explicit owner-plane operating decision accepts the residual lack of conditional PUT. If the API identity or editable schema changes, it fails closed and requires a reviewed source update.

## Standards and research basis

GitHub's current REST documentation makes ruleset mutation an Administration-authorized operation and describes bypass actors as explicit ruleset state; this is why the repair is placed in a separate owner plane instead of expanding the ordinary repository metadata token. GitHub also documents that organization owners or users with the dedicated organization-rules permission manage organization rulesets. Its REST best-practices guidance distinguishes safe conditional `GET` requests from unsafe methods and states that conditional `POST`/`PUT`/`PATCH`/`DELETE` requests are unsupported unless the endpoint explicitly says otherwise; the current ruleset update documentation does not provide a conditional-write precondition. NIST SP 800-53 Rev. 5 AC-6 supports least privilege, while CM-3 and its testing/validation enhancement support controlled, reviewed, verified configuration changes. Recent systematic-review evidence likewise identifies automated security controls, compliance-as-code, continuous feedback, access control, and protected credentials as central DevSecOps practices rather than relying on informal operator steps.

### References (APA 7th)

GitHub. (2026). *Best practices for using the REST API*. GitHub Docs. https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api

GitHub. (2026). *REST API endpoints for rules: Organizations*. GitHub Docs. https://docs.github.com/en/rest/orgs/rules

GitHub. (2026). *REST API endpoints for rules: Repositories*. GitHub Docs. https://docs.github.com/en/rest/repos/rules

GitHub. (2026). *Managing rulesets for repositories in your organization*. GitHub Docs. https://docs.github.com/en/organizations/managing-organization-settings/managing-rulesets-for-repositories-in-your-organization

National Institute of Standards and Technology. (2020). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53 Rev. 5). U.S. Department of Commerce. https://doi.org/10.6028/NIST.SP.800-53r5

Sinan, M., Shahin, M., & Gondal, I. (2025). Integrating security controls in DevSecOps: Challenges, solutions, and future research directions. *Journal of Software: Evolution and Process, 37*, e70029. https://doi.org/10.1002/smr.70029
