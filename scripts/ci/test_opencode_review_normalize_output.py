import pytest
import os
import sys

# Ensure scripts/ci can be imported
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from opencode_review_normalize_output import iter_json_objects

def test_iter_json_objects_valid_json():
    text = '{"key": "value"}'
    objects = iter_json_objects(text)
    assert objects == [{"key": "value"}, {"key": "value"}] # Once from loads, once from raw_decode loop

def test_iter_json_objects_multiple_json_with_prose():
    text = 'Here is the output: {"result": "APPROVE"} and another one: {"result": "REQUEST_CHANGES", "findings": []}'
    objects = iter_json_objects(text)
    assert len(objects) == 2
    assert objects[0] == {"result": "APPROVE"}
    assert objects[1] == {"result": "REQUEST_CHANGES", "findings": []}

def test_iter_json_objects_nested_json():
    text = 'some text {"outer": {"inner": "value"}} end'
    objects = iter_json_objects(text)
    assert len(objects) == 2 # "outer" and "inner" dictionaries
    assert objects[0] == {"outer": {"inner": "value"}}
    assert objects[1] == {"inner": "value"}

def test_iter_json_objects_invalid_json_braces():
    text = 'just { some { invalid { braces'
    objects = iter_json_objects(text)
    assert objects == []

def test_iter_json_objects_empty_string():
    text = ''
    objects = iter_json_objects(text)
    assert objects == []

from opencode_review_normalize_output import (
    admits_missing_structural_review,
    mentions_changed_file_evidence,
    valid_control,
)

def test_admits_missing_structural_review():
    assert admits_missing_structural_review("structural exploration was not possible", "summary")
    assert admits_missing_structural_review("reason", "structural exploration not possible")
    assert not admits_missing_structural_review("valid review", "all good")

def test_mentions_changed_file_evidence():
    assert mentions_changed_file_evidence("file changed src/test.py", "summary")
    assert mentions_changed_file_evidence("reason", "changed Makefile")
    assert not mentions_changed_file_evidence("reason", "summary")

def test_valid_control():
    expected_head_sha = "123"
    expected_run_id = "456"
    expected_run_attempt = "1"

    # Not a dict
    assert valid_control("not a dict", expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Missing/wrong head_sha
    assert valid_control({"head_sha": "wrong"}, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Missing/wrong run_id
    assert valid_control({"head_sha": expected_head_sha, "run_id": "wrong"}, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Missing/wrong run_attempt
    assert valid_control({"head_sha": expected_head_sha, "run_id": expected_run_id, "run_attempt": "wrong"}, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Wrong result
    base_valid = {"head_sha": expected_head_sha, "run_id": expected_run_id, "run_attempt": expected_run_attempt, "result": "UNKNOWN", "reason": "reason", "summary": "summary"}
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Missing reason
    base_valid["result"] = "APPROVE"
    base_valid["reason"] = ""
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Missing summary
    base_valid["reason"] = "reason src/test.py"
    base_valid["summary"] = ""
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Valid approve
    base_valid["summary"] = "summary"
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is not None

def test_valid_control_findings():
    expected_head_sha = "123"
    expected_run_id = "456"
    expected_run_attempt = "1"

    base_valid = {
        "head_sha": expected_head_sha,
        "run_id": expected_run_id,
        "run_attempt": expected_run_attempt,
        "reason": "reason src/test.py",
        "summary": "summary"
    }

    # Approve with findings
    base_valid["result"] = "APPROVE"
    base_valid["findings"] = [{"line": 1}]
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Request changes without findings
    base_valid["result"] = "REQUEST_CHANGES"
    base_valid["findings"] = []
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Approve missing structural review
    base_valid["result"] = "APPROVE"
    base_valid["findings"] = []
    base_valid["reason"] = "structural exploration was not possible"
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Approve not mentioning changed file evidence
    base_valid["reason"] = "all looks good"
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Valid Request Changes
    base_valid["result"] = "REQUEST_CHANGES"
    base_valid["findings"] = [{
        "line": 1,
        "path": "path",
        "severity": "high",
        "title": "title",
        "problem": "problem",
        "root_cause": "root_cause",
        "fix_direction": "fix_direction",
        "regression_test_direction": "test_direction",
        "suggested_diff": "diff"
    }]
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is not None

def test_valid_control_invalid_findings():
    expected_head_sha = "123"
    expected_run_id = "456"
    expected_run_attempt = "1"

    base_valid = {
        "head_sha": expected_head_sha,
        "run_id": expected_run_id,
        "run_attempt": expected_run_attempt,
        "result": "REQUEST_CHANGES",
        "reason": "reason src/test.py",
        "summary": "summary"
    }

    # Finding not a dict
    base_valid["findings"] = ["not a dict"]
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Invalid line
    base_valid["findings"] = [{"line": "not an int"}]
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None

    # Missing required field
    base_valid["findings"] = [{"line": 1, "path": "path"}]
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None


from opencode_review_normalize_output import check_structural_approval, main
import tempfile
import pathlib
import json

def test_check_structural_approval():
    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write("invalid json")
        f.close()
        assert check_structural_approval(pathlib.Path(f.name)) == 65

    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write('[]') # Not dict
        f.close()
        assert check_structural_approval(pathlib.Path(f.name)) == 4

    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write(json.dumps({"result": "APPROVE", "reason": "structural exploration was not possible"}))
        f.close()
        assert check_structural_approval(pathlib.Path(f.name)) == 4

    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write(json.dumps({"result": "APPROVE", "reason": "reason without file"}))
        f.close()
        assert check_structural_approval(pathlib.Path(f.name)) == 4

    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write(json.dumps({"result": "APPROVE", "reason": "looks good src/test.py"}))
        f.close()
        assert check_structural_approval(pathlib.Path(f.name)) == 0


def test_main():
    assert main(["script", "--check-structural-approval", "missing_file"]) == 65

    assert main(["script"]) == 64

    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write("test")
        f.close()
        # Invalid content
        assert main(["script", "head", "id", "attempt", f.name]) == 4

    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        control = {
            "head_sha": "head",
            "run_id": "id",
            "run_attempt": "attempt",
            "result": "APPROVE",
            "reason": "good src/test.py",
            "summary": "summary"
        }
        f.write(json.dumps(control))
        f.close()
        assert main(["script", "head", "id", "attempt", f.name]) == 0
        with open(f.name, "r") as f_read:
            output = f_read.read()
            assert "opencode-review-control-v1" in output
            assert "APPROVE" in output

    assert main(["script", "head", "id", "attempt", "missing_file"]) == 65


def test_valid_control_findings_none():
    expected_head_sha = "123"
    expected_run_id = "456"
    expected_run_attempt = "1"

    base_valid = {
        "head_sha": expected_head_sha,
        "run_id": expected_run_id,
        "run_attempt": expected_run_attempt,
        "result": "APPROVE",
        "reason": "reason src/test.py",
        "summary": "summary",
        "findings": None
    }
    # For APPROVE, None findings are allowed and mapped to []
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is not None

def test_main_missing_control():
    # Provide json without any matchable control block
    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write(json.dumps({"unrelated": "json"}))
        f.close()
        assert main(["script", "head", "id", "attempt", f.name]) == 4

def test_valid_control_findings_not_list():
    expected_head_sha = "123"
    expected_run_id = "456"
    expected_run_attempt = "1"

    base_valid = {
        "head_sha": expected_head_sha,
        "run_id": expected_run_id,
        "run_attempt": expected_run_attempt,
        "result": "REQUEST_CHANGES",
        "reason": "reason src/test.py",
        "summary": "summary",
        "findings": "not a list"
    }
    assert valid_control(base_valid, expected_head_sha=expected_head_sha, expected_run_id=expected_run_id, expected_run_attempt=expected_run_attempt) is None
