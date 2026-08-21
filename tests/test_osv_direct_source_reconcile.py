"""Regression tests for provenance-aware OSV direct-source reconciliation."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "osv_direct_source_reconcile.py"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security-scan.yml"
OFFICIAL_URL = "https://cdn.sheetjs.com/xlsx-{version}/xlsx-{version}.tgz"
INTEGRITY = "sha512-oLDq3jw7AcLqKWH2AhCpVTZl8mf6X2YReP+Neh0SJUzV/BdZYjth94tG5toiMB1PPrYtxOCfaoUCkvtuH+3AJA=="

SPEC = importlib.util.spec_from_file_location("osv_direct_source_reconcile", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
OSV = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OSV
SPEC.loader.exec_module(OSV)


def vulnerability(vuln_id: str, affected_range: str | None) -> dict[str, object]:
    """Return a minimal OSV vulnerability record."""

    record: dict[str, object] = {"id": vuln_id, "aliases": []}
    if affected_range is not None:
        record["affected"] = [
            {
                "database_specific": {
                    "last_known_affected_version_range": affected_range,
                    "source": (
                        "https://github.com/github/advisory-database/blob/main/"
                        f"advisories/github-reviewed/2026/08/{vuln_id}/{vuln_id}.json"
                    ),
                },
                "package": {"ecosystem": "npm", "name": "xlsx"},
                "ranges": [
                    {
                        "events": [{"introduced": "0"}],
                        "type": "SEMVER",
                    }
                ],
            }
        ]
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
    with mock.patch.object(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--results",
            str(result_path),
            "--lockfile",
            str(lock_path),
            "--audit",
            str(audit_path),
        ],
    ):
        with unittest.TestCase().assertRaises(SystemExit) as exit_context:
            runpy.run_path(str(SCRIPT), run_name="__main__")
        assert exit_context.exception.code == 0
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
        """Drop only advisories disproven by the exact immutable release evidence."""
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

    def test_registry_finding_from_another_lockfile_cannot_borrow_direct_source_provenance(
        self,
    ) -> None:
        """Bind reconciliation to the exact scanner source that supplied the lock evidence."""
        payload = results(
            "0.20.3", [vulnerability("GHSA-4r6h-8v6p-xvw6", "< 0.19.3")]
        )
        payload["results"][0]["source"]["path"] = (  # type: ignore[index]
            "/github/workspace/packages/registry/pnpm-lock.yaml"
        )

        reconciled, audit = OSV.reconcile_payload(
            payload,
            direct_lock("0.20.3"),
            label="head",
            source_path="pnpm-lock.yaml",
        )

        self.assertEqual(remaining_ids(reconciled), ["GHSA-4r6h-8v6p-xvw6"])
        self.assertEqual(audit[0]["status"], "SCANNER_METADATA_CONFLICT")
        self.assertIn("does not match governed lockfile", audit[0]["reason"])

    def test_container_workspace_path_matches_governed_root_lockfile(self) -> None:
        """Accept OSV's pinned container mount path for the exact root lockfile."""
        payload = results(
            "0.20.3", [vulnerability("GHSA-4r6h-8v6p-xvw6", "< 0.19.3")]
        )
        payload["results"][0]["source"]["path"] = (  # type: ignore[index]
            "/github/workspace/pnpm-lock.yaml"
        )

        reconciled, audit = OSV.reconcile_payload(
            payload,
            direct_lock("0.20.3"),
            label="head",
            source_path="pnpm-lock.yaml",
        )

        self.assertEqual(remaining_ids(reconciled), [])
        self.assertEqual(audit[0]["status"], "RECONCILED")

    def test_source_binding_helpers_and_malformed_cross_source_evidence_fail_closed(
        self,
    ) -> None:
        """Cover normalized-path validation and cross-source malformed evidence."""
        payload = results("0.20.3", [])
        self.assertEqual(len(list(OSV.iter_packages(payload))), 1)
        for invalid in ("", "/pnpm-lock.yaml", r"nested\pnpm-lock.yaml", "../pnpm-lock.yaml"):
            with self.subTest(source_path=invalid), self.assertRaisesRegex(
                ValueError, "normalized relative path"
            ):
                OSV.validate_source_path(invalid)

        unrelated = results("1.0.0", [])
        unrelated["results"][0]["source"]["path"] = "other-lock.json"  # type: ignore[index]
        unrelated["results"][0]["packages"][0]["package"]["name"] = "react"  # type: ignore[index]
        reconciled, audit = OSV.reconcile_payload(
            unrelated, direct_lock("0.20.3"), label="head"
        )
        self.assertEqual(reconciled, unrelated)
        self.assertEqual(audit, [])

        malformed = results("0.20.3", [])
        malformed["results"][0]["source"]["path"] = "other-lock.json"  # type: ignore[index]
        malformed["results"][0]["packages"][0]["vulnerabilities"] = ["bad"]  # type: ignore[index]
        with self.assertRaisesRegex(TypeError, "vulnerability entries"):
            OSV.reconcile_payload(
                malformed, direct_lock("0.20.3"), label="head"
            )

    def test_official_but_affected_versions_remain_findings(self) -> None:
        """Keep versions inside their authoritative affected range."""
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
        """Never apply a direct-source exception to a registry-backed package."""
        payload = results("0.18.5", [vulnerability("GHSA-registry", "< 0.19.3")])
        reconciled, audit = self.run_case(payload, registry_lock("0.18.5"))
        self.assertEqual(remaining_ids(reconciled), ["GHSA-registry"])
        self.assertEqual(audit[0]["status"], "SCANNER_METADATA_CONFLICT")

        payload["results"][0]["packages"][0]["package"]["name"] = "other"
        reconciled, audit = OSV.reconcile_payload(
            payload, registry_lock("0.18.5"), label="other"
        )
        self.assertEqual(audit, [])
        self.assertEqual(
            reconciled["results"][0]["packages"][0]["vulnerabilities"],
            [vulnerability("GHSA-registry", "< 0.19.3")],
        )

    def test_unverifiable_direct_provenance_fails_closed(self) -> None:
        """Retain findings when direct URL or integrity provenance is unverifiable."""
        for lock_text in (
            direct_lock("0.20.3", integrity=None),
            direct_lock("0.20.3", host="example.invalid"),
            direct_lock("0.20.3").replace(
                "tarball: https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz",
                "tarball: https://cdn.sheetjs.com/xlsx-0.20.2/xlsx-0.20.2.tgz",
            ),
        ):
            with self.subTest(lock_text=lock_text):
                payload = results(
                    "0.20.3",
                    [vulnerability("GHSA-unknown-source", "< 0.20.2")],
                )
                reconciled, audit = self.run_case(payload, lock_text)
                self.assertEqual(remaining_ids(reconciled), ["GHSA-unknown-source"])
                self.assertEqual(audit[0]["status"], "SCANNER_METADATA_CONFLICT")

    def test_only_exact_sheetjs_exception_version_can_reconcile(self) -> None:
        """Restrict reconciliation to the one explicitly governed SheetJS version."""
        for version in ("0.20.2", "0.20.4", "1.0.0"):
            with self.subTest(version=version):
                payload = results(
                    version, [vulnerability("GHSA-version-control", "< 0.20.2")]
                )
                reconciled, audit = self.run_case(
                    payload, direct_lock(version)
                )
                self.assertEqual(
                    remaining_ids(reconciled), ["GHSA-version-control"]
                )
                self.assertEqual(audit[0]["status"], "SCANNER_METADATA_CONFLICT")

    def test_conflicting_duplicate_direct_sources_fail_closed(self) -> None:
        """Reject duplicate direct-source records and malformed vulnerability entries."""
        payload = results(
            "0.20.3", [vulnerability("GHSA-duplicate-source", "< 0.20.2")]
        )
        lock_text = direct_lock("0.20.3") + direct_lock(
            "0.20.3", host="example.invalid"
        )
        reconciled, audit = self.run_case(payload, lock_text)
        self.assertEqual(remaining_ids(reconciled), ["GHSA-duplicate-source"])
        self.assertEqual(audit[0]["status"], "SCANNER_METADATA_CONFLICT")
        self.assertIn("multiple direct-source", audit[0]["reason"])

        payload["results"][0]["packages"][0]["vulnerabilities"] = ["bad"]
        with self.assertRaises(TypeError):
            OSV.reconcile_payload(payload, lock_text, label="bad")

    def test_exact_exception_version_inside_range_remains_affected(self) -> None:
        """Retain the exception version when the advisory range still includes it."""
        payload = results(
            "0.20.3", [vulnerability("GHSA-affected-exception", "< 0.20.4")]
        )
        reconciled, audit = self.run_case(payload, direct_lock("0.20.3"))
        self.assertEqual(
            remaining_ids(reconciled), ["GHSA-affected-exception"]
        )
        self.assertEqual(audit[0]["status"], "AFFECTED")

    def test_inclusive_affected_bound_is_respected(self) -> None:
        """Treat an OSV ``<=`` upper bound as affected at the boundary."""
        for affected_range, expected_ids, expected_status in (
            ("<= 0.20.3", ["GHSA-inclusive"], "AFFECTED"),
            ("<= 0.20.2", [], "RECONCILED"),
        ):
            with self.subTest(affected_range=affected_range):
                payload = results(
                    "0.20.3", [vulnerability("GHSA-inclusive", affected_range)]
                )
                reconciled, audit = self.run_case(payload, direct_lock("0.20.3"))
                self.assertEqual(remaining_ids(reconciled), expected_ids)
                self.assertEqual(audit[0]["status"], expected_status)

    def test_low_level_semver_integrity_and_source_validation_boundaries(self) -> None:
        """Exercise malformed SemVer, digest, URL, and package-source boundaries."""
        self.assertEqual(OSV.parse_semver("0.20.3"), (0, 20, 3))
        self.assertIsNone(OSV.parse_semver("01.20.3"))
        self.assertFalse(OSV.valid_sha512_integrity("sha256-deadbeef"))
        self.assertFalse(OSV.valid_sha512_integrity("sha512-%%%"))
        self.assertFalse(OSV.valid_sha512_integrity("sha512-YQ=="))
        valid_url = OFFICIAL_URL.format(version="0.20.3")
        cases = (
            ("other", valid_url, valid_url, "0.20.3", INTEGRITY),
            ("xlsx", "https://cdn.sheetjs.com:bad/x.xlsx", "", "0.20.3", INTEGRITY),
            ("xlsx", valid_url.replace("https://", "http://"), valid_url, "0.20.3", INTEGRITY),
            ("xlsx", valid_url.replace("cdn.sheetjs.com", "example.invalid"), valid_url, "0.20.3", INTEGRITY),
            ("xlsx", valid_url.replace("cdn.sheetjs.com", "cdn.sheetjs.com:443"), valid_url, "0.20.3", INTEGRITY),
            ("xlsx", valid_url.replace("cdn.sheetjs.com", "user@cdn.sheetjs.com"), valid_url, "0.20.3", INTEGRITY),
            ("xlsx", valid_url.replace("cdn.sheetjs.com", "user:pass@cdn.sheetjs.com"), valid_url, "0.20.3", INTEGRITY),
            ("xlsx", valid_url + "?download=1", valid_url, "0.20.3", INTEGRITY),
            ("xlsx", valid_url + "#fragment", valid_url, "0.20.3", INTEGRITY),
            ("xlsx", "https://cdn.sheetjs.com/not-xlsx.tgz", "", "0.20.3", INTEGRITY),
            ("xlsx", valid_url, valid_url, "0.20.2", INTEGRITY),
            ("xlsx", valid_url, valid_url.replace("0.20.3", "0.20.2"), "0.20.3", INTEGRITY),
            ("xlsx", valid_url, valid_url, "0.20.3", "missing"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assertFalse(OSV.validate_sheetjs_source(*arguments)[0])
        self.assertTrue(
            OSV.validate_sheetjs_source("xlsx", valid_url, valid_url, "0.20.3", INTEGRITY)[0]
        )

    def test_direct_source_parser_handles_boundaries_and_missing_fields(self) -> None:
        """Parse adjacent lockfile records without trusting incomplete resolutions."""
        valid_url = OFFICIAL_URL.format(version="0.20.3")
        lock = (
            "packages:\n\n"
            f"  xlsx@{valid_url}:\n"
            "    resolution: {}\n"
            "  other@https://example.invalid/other.tgz:\n"
            "    resolution: {tarball: https://example.invalid/other.tgz}\n"
        )
        sources = OSV.parse_direct_sources(lock)
        self.assertEqual(len(sources), 2)
        self.assertFalse(sources[0].valid)
        self.assertFalse(sources[1].valid)

    def test_direct_source_parser_ignores_pnpm_snapshot_duplicates(self) -> None:
        """Read one package provenance record when pnpm repeats it in snapshots."""
        valid_url = OFFICIAL_URL.format(version="0.20.3")
        lock = direct_lock("0.20.3") + (
            "\nsnapshots:\n\n"
            f"  xlsx@{valid_url}:\n"
            "    dependencies: {}\n"
        )
        sources = OSV.parse_direct_sources(lock)
        self.assertEqual(len(sources), 1)
        self.assertTrue(sources[0].valid)
        payload = results("0.20.3", [vulnerability("GHSA-snapshot", "< 0.20.2")])
        reconciled, audit = OSV.reconcile_payload(payload, lock, label="snapshot")
        self.assertEqual(remaining_ids(reconciled), [])
        self.assertEqual(audit[0]["status"], "RECONCILED")

    def test_malformed_osv_container_evidence_fails_closed(self) -> None:
        """Reject malformed OSV containers while accepting an empty result set."""
        malformed = (
            {},
            {"results": ["bad"]},
            {"results": [{"packages": "bad"}]},
            {"results": [{"packages": ["bad"]}]},
        )
        for payload in malformed:
            with self.subTest(payload=payload), self.assertRaises(TypeError):
                list(OSV.iter_packages(payload))
        self.assertEqual(list(OSV.iter_packages({"results": [{"packages": []}]})), [])

    def test_authoritative_range_rejects_every_ambiguous_shape(self) -> None:
        """Reject advisory shapes that cannot prove one authoritative affected range."""
        valid = vulnerability("GHSA-shape", "< 0.20.2")
        self.assertEqual(OSV.authoritative_affected_range(valid, "xlsx"), "< 0.20.2")
        malformed = [
            {},
            {"id": 1, "affected": []},
            {"id": "GHSA-shape", "affected": "bad"},
            {"id": "GHSA-shape", "affected": [None]},
        ]
        item_mutations = (
            ("package", None),
            ("package", {"ecosystem": "PyPI", "name": "xlsx"}),
            ("package", {"ecosystem": "npm", "name": "other"}),
            ("database_specific", None),
            ("ranges", None),
        )
        for key, value in item_mutations:
            candidate = copy.deepcopy(valid)
            candidate["affected"][0][key] = value
            malformed.append(candidate)
        database_mutations = (
            ("last_known_affected_version_range", None),
            ("source", None),
            ("source", "https://example.invalid/advisory.json"),
            ("source", "https://github.com/github/advisory-database/blob/main/wrong.json"),
        )
        for key, value in database_mutations:
            candidate = copy.deepcopy(valid)
            candidate["affected"][0]["database_specific"][key] = value
            malformed.append(candidate)
        for ranges in (
            [],
            [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}],
            [
                {"type": "SEMVER", "events": [{"introduced": "0"}]},
                {"type": "SEMVER", "events": [{"introduced": "0"}]},
            ],
            [{"type": "SEMVER", "events": [{"introduced": "1.0.0"}]}],
            [None],
        ):
            candidate = copy.deepcopy(valid)
            candidate["affected"][0]["ranges"] = ranges
            malformed.append(candidate)
        conflicting = copy.deepcopy(valid)
        second = copy.deepcopy(conflicting["affected"][0])
        second["database_specific"]["last_known_affected_version_range"] = "< 0.19.3"
        conflicting["affected"].append(second)
        malformed.append(conflicting)
        duplicate = copy.deepcopy(valid)
        duplicate["affected"].append(copy.deepcopy(duplicate["affected"][0]))
        self.assertEqual(OSV.authoritative_affected_range(duplicate, "xlsx"), "< 0.20.2")
        for candidate in malformed:
            with self.subTest(candidate=candidate):
                self.assertIsNone(OSV.authoritative_affected_range(candidate, "xlsx"))

    def test_reconcile_rejects_malformed_packages_and_vulnerabilities(self) -> None:
        """Reject malformed package and vulnerability records before rewriting results."""
        bad_packages = (
            {"results": [{"packages": [{"package": None, "vulnerabilities": []}]}]},
            {"results": [{"packages": [{"package": {}, "vulnerabilities": "bad"}]}]},
        )
        for payload in bad_packages:
            with self.subTest(payload=payload), self.assertRaises(TypeError):
                OSV.reconcile_payload(payload, direct_lock("0.20.3"), label="bad")
        bad_vulnerability = results("0.20.3", [])
        bad_vulnerability["results"][0]["packages"][0]["vulnerabilities"] = ["bad"]
        with self.assertRaises(TypeError):
            OSV.reconcile_payload(bad_vulnerability, direct_lock("0.20.3"), label="bad")
        untouched, audit = OSV.reconcile_payload(
            results("0.20.3", [vulnerability("GHSA-registry", "< 0.20.2")]),
            registry_lock("0.20.3"),
            label="registry",
        )
        self.assertEqual(remaining_ids(untouched), ["GHSA-registry"])
        self.assertEqual(audit[0]["status"], "SCANNER_METADATA_CONFLICT")

    def test_io_and_existing_audit_boundaries_fail_closed(self) -> None:
        """Exercise regular-file, UTF-8, audit, and atomic-write failure boundaries."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.json"
            with self.assertRaises(ValueError):
                OSV.load_json_object(missing)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            linked = root / "linked.json"
            linked.symlink_to(target)
            with self.assertRaises(ValueError):
                OSV.load_json_object(linked)
            with mock.patch.object(OSV.os, "O_NOFOLLOW", None), self.assertRaises(ValueError):
                OSV.read_utf8_text(target, "required JSON input")
            directory = root / "directory"
            directory.mkdir()
            with self.assertRaises(ValueError):
                OSV.read_utf8_text(directory, "required JSON input")
            array_path = root / "array.json"
            array_path.write_text("[]", encoding="utf-8")
            with self.assertRaises(TypeError):
                OSV.load_json_object(array_path)
            destination = root / "atomic.json"
            with mock.patch.object(
                OSV.os, "replace", side_effect=OSError("replace failed")
            ), self.assertRaises(OSError):
                OSV.atomic_json_write(destination, {})

            results_path = root / "results.json"
            lock_path = root / "pnpm-lock.yaml"
            audit_path = root / "audit.json"
            results_path.write_text(json.dumps({"results": []}), encoding="utf-8")
            lock_path.write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            audit_path.write_text('[{"status":"prior"}]', encoding="utf-8")
            argv = [
                str(SCRIPT), "--results", str(results_path), "--lockfile", str(lock_path),
                "--audit", str(audit_path), "--label", "head",
            ]
            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(OSV.main(), 0)
            self.assertEqual(json.loads(audit_path.read_text(encoding="utf-8")), [{"status": "prior"}])

            lock_path.write_bytes(b"lockfileVersion: '9.0'\n\xc0\xc0")
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(OSV.sys, "stderr", new_callable=io.StringIO) as stderr,
            ):
                self.assertEqual(OSV.main(), 1)
            self.assertIn("pnpm lock provenance input is not valid UTF-8", stderr.getvalue())

            lock_path.write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            audit_path.write_text("{}", encoding="utf-8")
            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(OSV.main(), 1)
            audit_path.unlink()
            audit_target = root / "audit-target.json"
            audit_target.write_text("[]", encoding="utf-8")
            audit_path.symlink_to(audit_target)
            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(OSV.main(), 1)
            lock_path.unlink()
            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(OSV.main(), 1)

    def test_missing_authoritative_affected_range_fails_closed(self) -> None:
        """Retain findings when the advisory lacks a machine-checkable range."""
        payload = results("0.20.3", [vulnerability("GHSA-unknown-range", None)])
        reconciled, audit = self.run_case(payload, direct_lock("0.20.3"))
        self.assertEqual(remaining_ids(reconciled), ["GHSA-unknown-range"])
        self.assertEqual(audit[0]["status"], "SCANNER_METADATA_CONFLICT")

    def test_reusable_security_scan_reconciles_before_reporter_verdict(self) -> None:
        """Require provenance reconciliation before the reusable scan publishes its verdict."""
        workflow = SECURITY_WORKFLOW.read_text(encoding="utf-8")
        preserve = workflow.index("Preserve base OSV evidence and direct-source provenance")
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
        self.assertNotIn(
            "github.repository == 'ContextualWisdomLab/.github' && github.event.pull_request.head.sha",
            workflow,
        )
        self.assertIn("osv_direct_source_reconcile.py", workflow)
        self.assertIn("osv-provenance-audit.json", workflow)
        self.assertEqual(workflow.count("--source-path pnpm-lock.yaml"), 2)


if __name__ == "__main__":
    unittest.main()
