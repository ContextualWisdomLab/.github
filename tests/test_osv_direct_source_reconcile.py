"""Regression tests for provenance-aware OSV direct-source reconciliation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "osv_direct_source_reconcile.py"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security-scan.yml"
OFFICIAL_URL = "https://cdn.sheetjs.com/xlsx-{version}/xlsx-{version}.tgz"
INTEGRITY = "sha512-oLDq3jw7AcLqKWH2AhCpVTZl8mf6X2YReP+Neh0SJUzV/BdZYjth94tG5toiMB1PPrYtxOCfaoUCkvtuH+3AJA=="


def vulnerability(vuln_id: str, affected_range: str | None) -> dict[str, object]:
    """Return a minimal OSV vulnerability record."""

    record: dict[str, object] = {"id": vuln_id, "aliases": []}
    if affected_range is not None:
        record["database_specific"] = {
            "last_known_affected_version_range": affected_range
        }
    return record


def results(version: str, vulnerabilities: list[dict[str, object]]) -> dict[str, object]:
    """Return a minimal OSV Scanner JSON document."""

    return {
        "results": [
            {
                "source": {"path": "pnpm-lock.yaml", "type": "lockfile"},
                "packages": [
                    {
                        "package": {
                            "name": "xlsx",
                            "version": version,
                            "ecosystem": "npm",
                        },
                        "vulnerabilities": vulnerabilities,
                    }
                ],
            }
        ]
    }


def direct_lock(version: str, *, integrity: str | None = INTEGRITY, host: str = "cdn.sheetjs.com") -> str:
    """Return the exact pnpm v9 direct-tarball evidence shape used by Inkspan."""

    url = OFFICIAL_URL.format(version=version).replace("cdn.sheetjs.com", host)
    resolution_parts = []
    if integrity is not None:
        resolution_parts.append(f"integrity: {integrity}")
    resolution_parts.append(f"tarball: {url}")
    resolution = ", ".join(resolution_parts)
    return (
        "lockfileVersion: '9.0'\n\n"
        "packages:\n\n"
        f"  xlsx@{url}:\n"
        f"    resolution: {{{resolution}}}\n"
        f"    version: {version}\n"
    )


def registry_lock(version: str) -> str:
    """Return an ordinary registry-backed pnpm package record."""

    return (
        "lockfileVersion: '9.0'\n\n"
        "packages:\n\n"
        f"  xlsx@{version}:\n"
        f"    resolution: {{integrity: {INTEGRITY}}}\n"
    )


def reconcile(tmp_path: Path, payload: dict[str, object], lock_text: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Run the production reconciler and return its rewritten result and audit."""

    assert SCRIPT.is_file(), "production OSV provenance reconciler is missing"
    result_path = tmp_path / "results.json"
    lock_path = tmp_path / "pnpm-lock.yaml"
    audit_path = tmp_path / "audit.json"
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    lock_path.write_text(lock_text, encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--results",
            str(result_path),
            "--lockfile",
            str(lock_path),
            "--audit",
            str(audit_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return (
        json.loads(result_path.read_text(encoding="utf-8")),
        json.loads(audit_path.read_text(encoding="utf-8")),
    )


def remaining_ids(payload: dict[str, object]) -> list[str]:
    """Return vulnerability IDs retained in a reconciled document."""

    package = payload["results"][0]["packages"][0]  # type: ignore[index]
    return [item["id"] for item in package["vulnerabilities"]]  # type: ignore[index]


class DirectSourceReconcileTests(unittest.TestCase):
    """Exercise exact provenance, affected-range, and fail-closed boundaries."""

    def run_case(
        self, payload: dict[str, object], lock_text: str
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Run one isolated production reconciliation case."""

        with tempfile.TemporaryDirectory() as directory:
            return reconcile(Path(directory), payload, lock_text)

    def test_official_immutable_xlsx_0203_drops_only_metadata_disproven_findings(self) -> None:
        payload = results(
            "0.20.3",
            [
                vulnerability("GHSA-4r6h-8v6p-xvw6", "< 0.19.3"),
                vulnerability("GHSA-5pgg-2g8v-p4x9", "< 0.20.2"),
            ],
        )

        reconciled, audit = self.run_case(payload, direct_lock("0.20.3"))

        self.assertEqual(remaining_ids(reconciled), [])
        self.assertEqual(
            [entry["status"] for entry in audit], ["RECONCILED", "RECONCILED"]
        )
        self.assertTrue(all(entry["integrity"] == INTEGRITY for entry in audit))

    def test_official_but_affected_versions_remain_findings(self) -> None:
        for version, affected_range in (
            ("0.18.5", "< 0.19.3"),
            ("0.19.2", "< 0.19.3"),
            ("0.20.1", "< 0.20.2"),
        ):
            with self.subTest(version=version):
                payload = results(
                    version, [vulnerability("GHSA-control", affected_range)]
                )
                reconciled, audit = self.run_case(payload, direct_lock(version))
                self.assertEqual(remaining_ids(reconciled), ["GHSA-control"])
                self.assertEqual(audit[0]["status"], "AFFECTED")

    def test_registry_package_never_borrows_direct_source_exception(self) -> None:
        payload = results("0.18.5", [vulnerability("GHSA-registry", "< 0.19.3")])
        reconciled, audit = self.run_case(payload, registry_lock("0.18.5"))
        self.assertEqual(remaining_ids(reconciled), ["GHSA-registry"])
        self.assertEqual(audit, [])

    def test_unverifiable_direct_provenance_fails_closed(self) -> None:
        for lock_text in (
            direct_lock("0.20.3", integrity=None),
            direct_lock("0.20.3", host="example.invalid"),
        ):
            with self.subTest(lock_text=lock_text):
                payload = results(
                    "0.20.3",
                    [vulnerability("GHSA-unknown-source", "< 0.20.2")],
                )
                reconciled, audit = self.run_case(payload, lock_text)
                self.assertEqual(remaining_ids(reconciled), ["GHSA-unknown-source"])
                self.assertEqual(audit[0]["status"], "SCANNER_METADATA_CONFLICT")

    def test_missing_authoritative_affected_range_fails_closed(self) -> None:
        payload = results("0.20.3", [vulnerability("GHSA-unknown-range", None)])
        reconciled, audit = self.run_case(payload, direct_lock("0.20.3"))
        self.assertEqual(remaining_ids(reconciled), ["GHSA-unknown-range"])
        self.assertEqual(audit[0]["status"], "SCANNER_METADATA_CONFLICT")

    def test_reusable_security_scan_reconciles_before_reporter_verdict(self) -> None:
        workflow = SECURITY_WORKFLOW.read_text(encoding="utf-8")
        preserve = workflow.index("Preserve base direct-source provenance")
        head_scan = workflow.index("Scan head with OSV")
        policy = workflow.index("Checkout exact central provenance policy")
        reconcile_step = workflow.index("Reconcile immutable direct-source provenance")
        require_output = workflow.index("Require OSV scan output")
        reporter = workflow.index("Report PR-introduced OSV findings")

        self.assertLess(preserve, head_scan)
        self.assertLess(head_scan, policy)
        self.assertLess(policy, reconcile_step)
        self.assertLess(reconcile_step, require_output)
        self.assertLess(require_output, reporter)
        self.assertIn("github.workflow_sha", workflow)
        self.assertIn("osv_direct_source_reconcile.py", workflow)
        self.assertIn("osv-provenance-audit.json", workflow)


if __name__ == "__main__":
    unittest.main()
