"""중앙 Noema의 k-csap native App 경로를 실제 shell로 검증한다."""

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/noema-review.yml"
TARGET = "ContextualWisdomLab/k-csap-skills"
METADATA = "Select native Noema credential for metadata reads"
REVIEWER = "Select fail-closed Noema reviewer credential"


def job_text(job):
    source = WORKFLOW.read_text()
    return re.split(r"\n {2}(?=\S)", source.split(f"\n  {job}:\n", 1)[1], maxsplit=1)[0]


def step_text(job, name):
    body = job_text(job).split(f"      - name: {name}\n", 1)[1]
    return body.split("\n      - name:", 1)[0]


def run_selection(job, name, repository=TARGET, client="fixture-client", key="fixture-key", pat="fixture-pat", oidc="https://fixture.invalid/exchange"):
    script = textwrap.dedent(step_text(job, name).split("        run: |\n", 1)[1])
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "output"
        result = subprocess.run(
            [shutil.which("bash") or "/bin/bash"], input=script,
            text=True, capture_output=True, timeout=10, check=False,
            env={"PATH": os.defpath, "GITHUB_OUTPUT": str(output),
                 "TARGET_REPOSITORY": repository, "PR_NUMBER": "269",
                 "EXPECTED_HEAD_SHA": "a" * 40,
                 "METADATA_TOKEN": pat, "NOEMA_REVIEW_TOKEN": pat,
                 "NOEMA_GITHUB_APP_CLIENT_ID": client,
                 "NOEMA_GITHUB_APP_PRIVATE_KEY": key, "TOKEN_EXCHANGE_URL": oidc},
        )
        values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    # 비밀값 대신 합성 placeholder만 사용하며 선택 단계의 누출도 거부한다.
    for value in (client, key, pat, oidc):
        if value:
            assert value not in result.stdout + result.stderr
    return result, values


class KcsapNoemaAppIdentity(unittest.TestCase):
    def test_metadata_requires_app_even_when_pat_and_oidc_exist(self):
        for job in ("admit-current-head", "noema-review"):
            for client, key in (("fixture-client", "fixture-key"), ("", "fixture-key"), ("fixture-client", ""), ("", "")):
                with self.subTest(job=job, client_present=bool(client), key_present=bool(key)):
                    result, values = run_selection(job, METADATA, client=client, key=key)
                    if client and key:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(values.get("source"), "github-app")
                        self.assertEqual(values.get("repository"), "k-csap-skills")
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn("source", values)
                        self.assertIn("::error::", result.stdout)

    def test_kcsap_token_wiring_cannot_reenter_legacy_fallback(self):
        metadata_legacy = "secrets.NOEMA_REVIEW_TOKEN || secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || steps.noema_metadata_app_token.outputs.token || github.token"
        reviewer_legacy = "secrets.NOEMA_REVIEW_TOKEN || steps.noema_github_app_token.outputs.token || steps.noema_oidc_token.outputs.token"
        publication_legacy = "steps.noema_credential.outputs.source == 'pat' && secrets.NOEMA_REVIEW_TOKEN || steps.noema_credential.outputs.source == 'github-app' && steps.noema_github_app_publication_token.outputs.token || steps.noema_credential.outputs.source == 'oidc' && steps.noema_oidc_token.outputs.token || ''"
        cases = [
            ("admit-current-head", "Admit only the exact live Noema head", "noema_metadata_app_token", metadata_legacy),
            ("noema-review", "Reject a stale trigger before credential or model setup", "noema_metadata_app_token", metadata_legacy),
            ("noema-review", "Validate current pull request head", "noema_github_app_token", reviewer_legacy),
            ("noema-review", "Resolve Noema target repository visibility", "noema_github_app_token", reviewer_legacy),
            ("noema-review", "Check live pull request draft state before sidecar provisioning", "noema_github_app_token", reviewer_legacy),
            ("noema-review", "Prepare Noema model verdict", "noema_github_app_token", reviewer_legacy),
            ("noema-review", "Publish prepared Noema verdict on the exact live head", "noema_github_app_publication_token", publication_legacy),
        ]
        for job, name, app_step, legacy in cases:
            with self.subTest(step=name):
                expression = re.search(r"GH_TOKEN: \$\{\{ (.*?) \}\}", step_text(job, name)).group(1)
                expected = f"env.TARGET_REPOSITORY == '{TARGET}' && steps.{app_step}.outputs.token || (env.TARGET_REPOSITORY != '{TARGET}' && ({legacy})) || ''"
                self.assertEqual(expression, expected)

    def test_other_repositories_preserve_legacy_selection(self):
        for repository in ("ContextualWisdomLab/example", TARGET + "-other"):
            for job in ("admit-current-head", "noema-review"):
                for client, key, pat, expected in (("fixture-client", "fixture-key", "fixture-pat", "pat"), ("fixture-client", "fixture-key", "", "github-app"), ("", "", "", "workflow")):
                    with self.subTest(repository=repository, job=job, source=expected):
                        result, values = run_selection(job, METADATA, repository=repository, client=client, key=key, pat=pat)
                        self.assertEqual(result.returncode, 0)
                        self.assertEqual(values.get("source"), expected)
            for client, key, pat, oidc, expected in (("fixture-client", "fixture-key", "fixture-pat", "", "pat"), ("fixture-client", "fixture-key", "", "", "github-app"), ("", "", "", "https://fixture.invalid/exchange", "oidc")):
                with self.subTest(repository=repository, source=expected):
                    result, values = run_selection("noema-review", REVIEWER, repository=repository, client=client, key=key, pat=pat, oidc=oidc)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(values.get("source"), expected)

    def test_reviewer_requires_native_app_without_pat_or_oidc_fallback(self):
        for client, key in (("fixture-client", "fixture-key"), ("", "fixture-key"), ("fixture-client", ""), ("", "")):
            for pat, oidc in (("fixture-pat", "https://fixture.invalid/exchange"), ("", "https://fixture.invalid/exchange"), ("", "")):
                with self.subTest(client_present=bool(client), key_present=bool(key), pat_present=bool(pat), oidc_present=bool(oidc)):
                    result, values = run_selection("noema-review", REVIEWER, client=client, key=key, pat=pat, oidc=oidc)
                    if client and key:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(values.get("source"), "github-app")
                        self.assertEqual(values.get("repository"), "k-csap-skills")
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn("source", values)
                        self.assertIn("::error::", result.stdout)
