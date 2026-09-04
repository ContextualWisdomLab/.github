from scripts.ci.review_admission_controller import (
    ADMISSION_PERMISSIONS,
    WORKER_BOUNDARIES,
    AdmissionRequest,
    ControllerState,
    complete_dispatch,
    plan_dispatches,
    require_publishable,
)

HEAD_1 = "1" * 40
HEAD_2 = "2" * 40
HEAD_3 = "3" * 40


def request(component: str, head: str = HEAD_2, sequence: int = 2) -> AdmissionRequest:
    return AdmissionRequest.create(
        repository="ContextualWisdomLab/example",
        pull_request=7,
        head_sha=head,
        component=component,
        sequence=sequence,
    )


def test_controller_is_idempotent_bounded_and_rejects_stale_or_out_of_order() -> None:
    state = ControllerState.empty()
    stale = request("opencode", HEAD_1, 1)
    current = request("opencode")
    duplicate = request("opencode")
    noema = request("noema")
    strix = request("strix")

    plan = plan_dispatches(
        state,
        [stale, current, duplicate, noema, strix],
        live_heads={(current.repository, current.pull_request): HEAD_2},
        dispatch_budget=2,
    )

    assert [item.request.component for item in plan.dispatches] == ["opencode", "noema"]
    assert plan.rejections[stale.identity] == "stale_head"
    assert plan.rejections[duplicate.identity] == "duplicate"
    assert plan.state.records[current.identity].status == "dispatched"
    assert plan.state.records[strix.identity].status == "queued"
    assert ControllerState.from_json(plan.state.to_json()) == plan.state

    repeated = plan_dispatches(
        plan.state,
        [current, noema, strix],
        live_heads={(current.repository, current.pull_request): HEAD_2},
        dispatch_budget=2,
    )
    assert [item.request.component for item in repeated.dispatches] == ["strix"]
    assert repeated.rejections[current.identity] == "idempotent"
    assert repeated.rejections[noema.identity] == "idempotent"

    delayed = plan_dispatches(
        repeated.state,
        [request("opencode", HEAD_3, 1)],
        live_heads={(current.repository, current.pull_request): HEAD_2},
        dispatch_budget=1,
    )
    assert delayed.rejections[request("opencode", HEAD_3, 1).identity] == "out_of_order"


def test_worker_boundaries_remain_separate_and_publish_requires_live_head_cas() -> None:
    assert ADMISSION_PERMISSIONS == ("contents: read", "pull-requests: read")
    assert set(WORKER_BOUNDARIES) == {"opencode", "noema", "strix"}
    assert len({boundary.credential for boundary in WORKER_BOUNDARIES.values()}) == 3
    assert (
        len({boundary.concurrency_namespace for boundary in WORKER_BOUNDARIES.values()})
        == 3
    )
    assert all(
        "pull-requests: read" in boundary.permissions
        for boundary in WORKER_BOUNDARIES.values()
    )

    planned = plan_dispatches(
        ControllerState.empty(),
        [request("strix")],
        live_heads={("ContextualWisdomLab/example", 7): HEAD_2},
        dispatch_budget=1,
    )
    item = planned.dispatches[0]
    require_publishable(item, live_head=HEAD_2)
    completed = complete_dispatch(
        planned.state,
        item,
        live_head=HEAD_2,
    )
    assert completed.records[item.request.identity].status == "complete"

    try:
        require_publishable(item, live_head=HEAD_1)
    except ValueError as exc:
        assert str(exc) == "live head changed before publication"
    else:  # pragma: no cover
        raise AssertionError("stale publication was accepted")
