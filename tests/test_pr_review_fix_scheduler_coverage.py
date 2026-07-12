import pytest
import scripts.ci.pr_review_fix_scheduler as fix

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
