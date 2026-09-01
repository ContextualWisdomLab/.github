import base64

from scripts.ci import repository_metadata_reconciler as reconciler


class FakeApi:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, payload=None, allow_status=()):
        self.calls.append((method, path, payload, tuple(allow_status)))
        return self.responses.pop(0)


def _desired():
    return {
        "description": "Calendar resource infrastructure for iCalendar, CalDAV, revisions, and interoperable scheduling.",
        "topics": ["calendar", "caldav"],
        "deepwiki": True,
        "pages": {"enabled": False},
    }


def test_disabled_pages_deletes_an_existing_site():
    desired = _desired()
    live = {
        "description": desired["description"],
        "topics": desired["topics"],
        "has_pages": True,
        "pages": {"source": {"branch": "main", "path": "/docs"}, "build_type": "legacy"},
    }
    assert reconciler.plan_operations("CalendarWeave", live, desired) == [
        ("pages_delete", {})
    ]


def test_disabled_pages_is_noop_when_site_is_absent():
    desired = _desired()
    live = {
        "description": desired["description"],
        "topics": desired["topics"],
        "has_pages": False,
    }
    assert reconciler.plan_operations("CalendarWeave", live, desired) == []


def test_pages_delete_uses_github_pages_delete_endpoint_without_body():
    api = FakeApi([{}])
    reconciler.apply_operations(
        api,
        "ContextualWisdomLab",
        "CalendarWeave",
        [("pages_delete", {})],
    )
    assert api.calls == [
        ("DELETE", "/repos/ContextualWisdomLab/CalendarWeave/pages", None, ())
    ]


def test_deepwiki_audit_recognizes_only_the_canonical_badge():
    markdown = reconciler.deepwiki_markdown("ContextualWisdomLab", "CalendarWeave")
    api = FakeApi([
        {"content": base64.b64encode(("# CalendarWeave\n\n" + markdown + "\n").encode()).decode()}
    ])
    assert reconciler.deepwiki_badge_present(api, "ContextualWisdomLab", "CalendarWeave") is True
    assert api.calls[0][0:2] == (
        "GET",
        "/repos/ContextualWisdomLab/CalendarWeave/readme",
    )


def test_deepwiki_audit_reports_missing_readme_or_wrong_target():
    missing = FakeApi([None])
    assert reconciler.deepwiki_badge_present(
        missing, "ContextualWisdomLab", "CalendarWeave"
    ) is False
    assert missing.calls[0][3] == (404,)

    wrong = FakeApi([
        {
            "content": base64.b64encode(
                b"[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/other/repo)"
            ).decode()
        }
    ])
    assert reconciler.deepwiki_badge_present(
        wrong, "ContextualWisdomLab", "CalendarWeave"
    ) is False


def test_deepwiki_audit_fails_closed_on_malformed_readme_payload():
    malformed = FakeApi([{"content": "%%%not-base64%%%"}])
    assert reconciler.deepwiki_badge_present(
        malformed, "ContextualWisdomLab", "CalendarWeave"
    ) is False
