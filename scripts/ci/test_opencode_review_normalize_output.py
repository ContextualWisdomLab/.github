#!/usr/bin/env python3
import unittest
import sys
from pathlib import Path
from typing import Any

# Add the directory to sys.path so we can import the module
sys.path.insert(0, str(Path(__file__).parent))
from opencode_review_normalize_output import valid_control

class TestValidControl(unittest.TestCase):
    def setUp(self) -> None:
        self.default_kwargs = {
            "expected_head_sha": "test_sha",
            "expected_run_id": "test_id",
            "expected_run_attempt": "1",
        }
        self.valid_approve = {
            "head_sha": "test_sha",
            "run_id": "test_id",
            "run_attempt": "1",
            "result": "APPROVE",
            "reason": "Everything looks good.",
            "summary": "Reviewed changed files like index.js.",
            "findings": []
        }
        self.valid_request_changes = {
            "head_sha": "test_sha",
            "run_id": "test_id",
            "run_attempt": "1",
            "result": "REQUEST_CHANGES",
            "reason": "There are issues.",
            "summary": "Some files need fixes.",
            "findings": [
                {
                    "path": "test.py",
                    "line": 10,
                    "severity": "ERROR",
                    "title": "Bug",
                    "problem": "Bad code",
                    "root_cause": "Typo",
                    "fix_direction": "Fix it",
                    "regression_test_direction": "Test it",
                    "suggested_diff": "- bad\n+ good"
                }
            ]
        }

    def test_not_dict(self) -> None:
        self.assertIsNone(valid_control(None, **self.default_kwargs))
        self.assertIsNone(valid_control("string", **self.default_kwargs))
        self.assertIsNone(valid_control([], **self.default_kwargs))

    def test_mismatched_metadata(self) -> None:
        # Wrong SHA
        data = dict(self.valid_approve, head_sha="wrong")
        self.assertIsNone(valid_control(data, **self.default_kwargs))

        # Wrong Run ID
        data = dict(self.valid_approve, run_id="wrong")
        self.assertIsNone(valid_control(data, **self.default_kwargs))

        # Wrong Run Attempt
        data = dict(self.valid_approve, run_attempt="wrong")
        self.assertIsNone(valid_control(data, **self.default_kwargs))

    def test_invalid_result(self) -> None:
        data = dict(self.valid_approve, result="UNKNOWN")
        self.assertIsNone(valid_control(data, **self.default_kwargs))

        data = dict(self.valid_approve, result=None)
        self.assertIsNone(valid_control(data, **self.default_kwargs))

    def test_missing_or_empty_reason_summary(self) -> None:
        for field in ["reason", "summary"]:
            # Empty string
            data = dict(self.valid_approve)
            data[field] = "   "
            self.assertIsNone(valid_control(data, **self.default_kwargs))

            # Missing completely
            data = dict(self.valid_approve)
            del data[field]
            self.assertIsNone(valid_control(data, **self.default_kwargs))

    def test_approve_with_findings_fails(self) -> None:
        data = dict(self.valid_approve, findings=self.valid_request_changes["findings"])
        self.assertIsNone(valid_control(data, **self.default_kwargs))

    def test_request_changes_without_findings_fails(self) -> None:
        data = dict(self.valid_request_changes, findings=[])
        self.assertIsNone(valid_control(data, **self.default_kwargs))

        data = dict(self.valid_request_changes, findings=None)
        self.assertIsNone(valid_control(data, **self.default_kwargs))

    def test_approve_missing_structural_review_fails(self) -> None:
        data = dict(self.valid_approve, reason="structural exploration was not possible")
        self.assertIsNone(valid_control(data, **self.default_kwargs))

    def test_approve_no_concrete_changed_file_fails(self) -> None:
        data = dict(self.valid_approve, summary="No file names here")
        self.assertIsNone(valid_control(data, **self.default_kwargs))

    def test_invalid_finding_format(self) -> None:
        # Not a dict finding
        data = dict(self.valid_request_changes, findings=["not a dict"])
        self.assertIsNone(valid_control(data, **self.default_kwargs))

        # Missing required field
        invalid_finding = dict(self.valid_request_changes["findings"][0])
        del invalid_finding["severity"]
        data = dict(self.valid_request_changes, findings=[invalid_finding])
        self.assertIsNone(valid_control(data, **self.default_kwargs))

        # Invalid line number
        invalid_finding = dict(self.valid_request_changes["findings"][0])
        invalid_finding["line"] = 0
        data = dict(self.valid_request_changes, findings=[invalid_finding])
        self.assertIsNone(valid_control(data, **self.default_kwargs))

        invalid_finding["line"] = "10" # not int
        data = dict(self.valid_request_changes, findings=[invalid_finding])
        self.assertIsNone(valid_control(data, **self.default_kwargs))

    def test_valid_approve_success(self) -> None:
        result = valid_control(self.valid_approve, **self.default_kwargs)
        self.assertEqual(result, self.valid_approve)

    def test_valid_request_changes_success(self) -> None:
        result = valid_control(self.valid_request_changes, **self.default_kwargs)
        self.assertEqual(result, self.valid_request_changes)

    def test_approve_none_findings_converted_to_empty_list(self) -> None:
        data = dict(self.valid_approve, findings=None)
        result = valid_control(data, **self.default_kwargs)
        self.assertIsNotNone(result)
        self.assertEqual(result["findings"], [])

if __name__ == '__main__':
    unittest.main()
