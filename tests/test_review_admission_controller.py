import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.ci.review_admission_controller import (
    ADMISSION_PERMISSIONS,
    WORKER_BOUNDARIES,
    AdmissionRequest,
    ControllerState,
    DispatchLease,
    RequestRecord,
    WorkerBoundary,
    _atomic_write,
    _open_regular_nofollow,
    _read_state,
    complete_dispatch,
    load_state_file,
    plan_dispatches,
    require_publishable,
    update_state_file,
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

    completed_state = complete_dispatch(
        complete_dispatch(plan.state, plan.dispatches[0], live_head=HEAD_2),
        plan.dispatches[1],
        live_head=HEAD_2,
    )
    repeated = plan_dispatches(
        completed_state,
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
    assert all(boundary.cancel_in_progress for boundary in WORKER_BOUNDARIES.values())
    assert WORKER_BOUNDARIES["strix"].concurrency_group(request("strix")) == (
        "strix-security-scan-ContextualWisdomLab/example-7"
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

    forged = DispatchLease(
        item.request,
        WorkerBoundary("wrong", ("contents: write",), "shared"),
    )
    with pytest.raises(ValueError, match="worker boundary"):
        require_publishable(forged, live_head=HEAD_2)


def test_state_file_is_atomic_recovers_and_serializes_concurrent_writers(tmp_path) -> None:
    state_path = tmp_path / "controller.json"
    barrier = threading.Barrier(8)

    def writer(sequence: int) -> None:
        barrier.wait()

        def add(state: ControllerState) -> ControllerState:
            item = AdmissionRequest.create(
                repository=f"ContextualWisdomLab/repo-{sequence}",
                pull_request=sequence,
                head_sha=f"{sequence:x}" * 40,
                component="opencode",
                sequence=1,
            )
            records = dict(state.records)
            records[item.identity] = RequestRecord(item, "queued")
            latest = dict(state.latest_sequences)
            latest[item.stream] = 1
            return ControllerState(records, latest)

        update_state_file(state_path, add)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(writer, range(1, 9)))

    persisted = load_state_file(state_path)
    assert len(persisted.records) == 8
    assert state_path.stat().st_mode & 0o777 == 0o600
    state_path.write_text("{truncated", encoding="utf-8")
    assert load_state_file(state_path) == persisted
    state_path.unlink()
    assert load_state_file(state_path) == persisted


def test_state_rejects_unsafe_paths_shapes_and_secret_fields(tmp_path) -> None:
    target = tmp_path / "target.json"
    target.write_text(ControllerState.empty().to_json(), encoding="utf-8")
    link = tmp_path / "state.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        load_state_file(link)
    with pytest.raises(ValueError, match="symlink"):
        update_state_file(link, lambda state: state)

    with pytest.raises(ValueError, match="outside ContextualWisdomLab"):
        AdmissionRequest.create(
            repository="ContextualWisdomLab/../../secrets",
            pull_request=1,
            head_sha=HEAD_1,
            component="opencode",
            sequence=1,
        )
    with pytest.raises(ValueError, match="unknown review component"):
        request("../../worker")
    with pytest.raises(TypeError, match="integer"):
        AdmissionRequest.create(
            repository="ContextualWisdomLab/example",
            pull_request=True,
            head_sha=HEAD_1,
            component="opencode",
            sequence=1,
        )

    payload = json.loads(ControllerState.empty().to_json())
    payload["credential"] = "should-never-persist"
    with pytest.raises(ValueError, match="unknown fields"):
        ControllerState.from_json(json.dumps(payload))

    poisoned = json.loads(ControllerState.empty().to_json())
    poisoned["latest_sequences"]["ContextualWisdomLab/example#7:opencode"] = 999
    with pytest.raises(ValueError, match="unknown streams"):
        ControllerState.from_json(json.dumps(poisoned))


def test_budget_counts_active_leases_and_stale_heads_cannot_poison_sequence() -> None:
    current = request("opencode", HEAD_2, 2)
    first = plan_dispatches(
        ControllerState.empty(),
        [current],
        live_heads={(current.repository, current.pull_request): HEAD_2},
        dispatch_budget=1,
    )
    noema = request("noema", HEAD_2, 2)
    saturated = plan_dispatches(
        first.state,
        [noema],
        live_heads={(current.repository, current.pull_request): HEAD_2},
        dispatch_budget=1,
    )
    assert saturated.dispatches == ()
    assert saturated.state.records[noema.identity].status == "queued"

    stale = request("strix", HEAD_3, 99)
    stale_plan = plan_dispatches(
        ControllerState.empty(),
        [stale],
        live_heads={(stale.repository, stale.pull_request): HEAD_2},
        dispatch_budget=1,
    )
    assert stale.stream not in stale_plan.state.latest_sequences
    assert ControllerState.from_json(stale_plan.state.to_json()) == stale_plan.state
    valid = request("strix", HEAD_2, 1)
    recovered = plan_dispatches(
        stale_plan.state,
        [valid],
        live_heads={(valid.repository, valid.pull_request): HEAD_2},
        dispatch_budget=1,
    )
    assert recovered.dispatches[0].request == valid

    retry_state = ControllerState(
        {valid.identity: RequestRecord(valid, "stale")},
        {},
    )
    retried = plan_dispatches(
        retry_state,
        [request("strix", HEAD_2, 2)],
        live_heads={(valid.repository, valid.pull_request): HEAD_2},
        dispatch_budget=1,
    )
    assert retried.dispatches[0].request.sequence == 2


def test_admission_request_rejects_each_invalid_field() -> None:
    with pytest.raises(TypeError, match="sequence must be an integer"):
        AdmissionRequest.create(
            repository="ContextualWisdomLab/example",
            pull_request=1,
            head_sha=HEAD_1,
            component="opencode",
            sequence=True,
        )
    with pytest.raises(ValueError, match="pull request must be positive"):
        AdmissionRequest.create(
            repository="ContextualWisdomLab/example",
            pull_request=0,
            head_sha=HEAD_1,
            component="opencode",
            sequence=1,
        )
    with pytest.raises(ValueError, match="head must be a full Git SHA"):
        AdmissionRequest.create(
            repository="ContextualWisdomLab/example",
            pull_request=1,
            head_sha="not-a-sha",
            component="opencode",
            sequence=1,
        )
    with pytest.raises(ValueError, match="sequence must be positive"):
        AdmissionRequest.create(
            repository="ContextualWisdomLab/example",
            pull_request=1,
            head_sha=HEAD_1,
            component="opencode",
            sequence=0,
        )


def test_controller_state_from_json_rejects_each_malformed_shape() -> None:
    with pytest.raises(TypeError, match="must be an object"):
        ControllerState.from_json("[]")
    with pytest.raises(TypeError, match="invalid collections"):
        ControllerState.from_json(json.dumps({"records": [], "latest_sequences": {}}))
    with pytest.raises(TypeError, match="invalid shape"):
        ControllerState.from_json(
            json.dumps({"records": {"x": "not-a-dict"}, "latest_sequences": {}})
        )
    with pytest.raises(ValueError, match="invalid durable admission record"):
        ControllerState.from_json(
            json.dumps(
                {"records": {"x": {"request": {}, "status": "queued", "extra": 1}}, "latest_sequences": {}}
            )
        )
    valid_request = {
        "repository": "ContextualWisdomLab/example",
        "pull_request": 7,
        "head_sha": HEAD_1,
        "component": "opencode",
        "sequence": 1,
    }
    with pytest.raises(ValueError, match="invalid durable admission request"):
        ControllerState.from_json(
            json.dumps(
                {
                    "records": {
                        "x": {"request": {**valid_request, "extra": 1}, "status": "queued"}
                    },
                    "latest_sequences": {},
                }
            )
        )
    real_identity = AdmissionRequest.create(**valid_request).identity
    with pytest.raises(ValueError, match="invalid durable admission record"):
        ControllerState.from_json(
            json.dumps(
                {
                    "records": {
                        real_identity: {"request": valid_request, "status": "not-a-real-status"}
                    },
                    "latest_sequences": {},
                }
            )
        )
    with pytest.raises(ValueError, match="invalid durable admission sequence"):
        ControllerState.from_json(
            json.dumps({"records": {}, "latest_sequences": {"stream": 0}})
        )
    with pytest.raises(ValueError, match="sequence regressed"):
        ControllerState.from_json(
            json.dumps(
                {
                    "records": {
                        real_identity: {"request": valid_request, "status": "queued"}
                    },
                    "latest_sequences": {},
                }
            )
        )
    with pytest.raises(ValueError, match="sequence is inconsistent"):
        ControllerState.from_json(
            json.dumps(
                {
                    "records": {
                        real_identity: {"request": valid_request, "status": "queued"}
                    },
                    "latest_sequences": {
                        AdmissionRequest.create(**valid_request).stream: 99
                    },
                }
            )
        )


def test_open_regular_nofollow_rejects_a_non_regular_file(tmp_path) -> None:
    directory = tmp_path / "not-a-file"
    directory.mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        _open_regular_nofollow(directory, os.O_RDONLY)


def test_read_state_rejects_non_utf8_content(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(ValueError, match="not UTF-8"):
        _read_state(path)


def test_load_state_file_rejects_symlinked_backup_and_surfaces_corruption(tmp_path) -> None:
    path = tmp_path / "state.json"
    backup = tmp_path / "state.json.bak"
    other = tmp_path / "other.json"
    other.write_text(ControllerState.empty().to_json(), encoding="utf-8")
    backup.symlink_to(other)
    path.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="backup must not be a symlink"):
        load_state_file(path)

    backup.unlink()
    path.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt and has no backup"):
        load_state_file(path)


def test_atomic_write_rejects_a_symlinked_destination(tmp_path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "state.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="must not be a symlink"):
        _atomic_write(link, "{}")


def test_update_state_file_rejects_symlinked_lock_and_non_state_return(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    lock_path = tmp_path / "state.json.lock"
    lock_path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="lock must not be a symlink"):
        update_state_file(state_path, lambda state: state)

    lock_path.unlink()
    with pytest.raises(TypeError, match="must return ControllerState"):
        update_state_file(state_path, lambda state: None)


def test_plan_dispatches_rejects_negative_budget() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        plan_dispatches(
            ControllerState.empty(), [], live_heads={}, dispatch_budget=-1
        )


def test_plan_dispatches_retires_a_sibling_queued_for_an_older_head() -> None:
    older = request("opencode", HEAD_1, 1)
    first = plan_dispatches(
        ControllerState.empty(),
        [older],
        live_heads={(older.repository, older.pull_request): HEAD_1},
        dispatch_budget=0,
    )
    assert first.state.records[older.identity].status == "queued"

    newer = request("opencode", HEAD_2, 2)
    second = plan_dispatches(
        first.state,
        [newer],
        live_heads={(newer.repository, newer.pull_request): HEAD_2},
        dispatch_budget=0,
    )
    assert second.state.records[older.identity].status == "stale"
    assert second.state.records[newer.identity].status == "queued"


def test_plan_dispatches_retires_a_queued_lease_whose_head_went_stale_before_dispatch() -> None:
    queued = request("opencode", HEAD_2, 1)
    intake = plan_dispatches(
        ControllerState.empty(),
        [queued],
        live_heads={(queued.repository, queued.pull_request): HEAD_2},
        dispatch_budget=0,
    )
    assert intake.state.records[queued.identity].status == "queued"

    dispatch_attempt = plan_dispatches(
        intake.state,
        [],
        live_heads={(queued.repository, queued.pull_request): HEAD_3},
        dispatch_budget=1,
    )
    assert dispatch_attempt.dispatches == ()
    assert dispatch_attempt.rejections[queued.identity] == "stale_head"
    assert dispatch_attempt.state.records[queued.identity].status == "stale"


def test_complete_dispatch_rejects_a_request_without_an_active_lease() -> None:
    current = request("opencode", HEAD_2, 1)
    planned = plan_dispatches(
        ControllerState.empty(),
        [current],
        live_heads={(current.repository, current.pull_request): HEAD_2},
        dispatch_budget=1,
    )
    lease = planned.dispatches[0]
    completed = complete_dispatch(planned.state, lease, live_head=HEAD_2)

    with pytest.raises(ValueError, match="does not hold an active dispatch lease"):
        complete_dispatch(completed, lease, live_head=HEAD_2)
