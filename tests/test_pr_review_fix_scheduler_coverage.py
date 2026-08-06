import builtins
import runpy

import scripts.ci.pr_review_fix_scheduler as fix


def test_import_falls_back_to_package_module(monkeypatch):
    """The scheduler remains importable when only the package path is available."""
    real_import = builtins.__import__

    def import_without_script_directory(
        name,
        globals=None,
        locals=None,
        fromlist=(),
        level=0,
    ):
        if name == "pr_review_merge_scheduler":
            raise ModuleNotFoundError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_script_directory)
    namespace = runpy.run_path(
        "scripts/ci/pr_review_fix_scheduler.py",
        run_name="pr_review_fix_scheduler_package_fallback_test",
    )

    assert namespace["fetch_open_prs"] is fix.fetch_open_prs


def test_coverage_process_queue_skips_draft_and_wrong_base_and_external_repo(monkeypatch):
    def make_pr(number=1, **kwargs):
        pr = {
            "number": number,
            "headRefOid": "abc",
            "baseRefName": "main",
            "headRefName": "feature",
            "isDraft": False,
            "headRepository": {"nameWithOwner": "owner/repo"},
        }
        pr.update(kwargs)
        return pr

    args = fix.parse_args(["--repo", "owner/repo", "--base-branch", "main"])

    pr1 = make_pr(number=1, isDraft=True)
    pr2 = make_pr(number=2, baseRefName="other")
    pr3 = make_pr(number=3, headRepository={"nameWithOwner": "fork/repo"})

    monkeypatch.setattr(fix, "fetch_open_prs", lambda repo, max_prs: [pr1, pr2, pr3])
    monkeypatch.setattr(fix, "inspect_pr", lambda repo, pr, args, **kwargs: ("skip", ("skip reason",)))

    assert fix.process_queue(args) == 0


def test_coverage_process_queue_exception_handling(monkeypatch):
    def make_pr(number=1, **kwargs):
        pr = {
            "number": number,
            "headRefOid": "abc",
            "baseRefName": "main",
            "headRefName": "feature",
            "isDraft": False,
            "headRepository": {"nameWithOwner": "owner/repo"},
        }
        pr.update(kwargs)
        return pr

    args = fix.parse_args(["--repo", "owner/repo", "--base-branch", "main"])

    pr1 = make_pr(number=1)
    pr2 = make_pr(number=2)

    monkeypatch.setattr(fix, "fetch_open_prs", lambda repo, max_prs: [pr1, pr2])
    monkeypatch.setattr(fix, "needs_autofix", lambda pr: (True, ("reason",)))

    def raise_error(repo, number):
        raise RuntimeError("boom")

    monkeypatch.setattr(fix, "issue_comments", raise_error)
    monkeypatch.setattr(fix, "inspect_pr", lambda repo, pr, args, **kwargs: ("skip", ("skip reason",)))

    assert fix.process_queue(args) == 0
