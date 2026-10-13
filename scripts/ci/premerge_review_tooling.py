"""Admit independently pinned reviewer source before loading any candidate code.

This source-only boundary does not issue credentials or admit a runner. Its
caller must obtain accepted_digest independently of PR data and supply the
complete regular-file inventory from the selected immutable Git tree. Merely
hashing a caller's own manifest is not independent source acceptance.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import re
import tempfile
import subprocess
from pathlib import Path
from collections.abc import Mapping


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys before any manifest interpretation."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("manifest contains duplicate fields")
        result[key] = value
    return result


def _safe_path(value: object) -> bool:
    """Accept canonical relative inventory paths without traversal or controls."""
    return (
        isinstance(value, str)
        and bool(value)
        and "\\" not in value
        and not any(ord(character) < 32 for character in value)
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def admit_tooling(
    raw_manifest: bytes, *, accepted_digest: str, source_files: Mapping[str, bytes]
) -> None:
    """Reject a manifest that does not match independently accepted bytes."""
    if not isinstance(raw_manifest, bytes) or not 0 < len(raw_manifest) <= 2 * 1024 * 1024:
        raise ValueError("manifest size is outside the bounded contract")
    if hashlib.sha256(raw_manifest).hexdigest() != accepted_digest:
        raise ValueError("tooling does not match the accepted manifest digest")
    try:
        manifest = json.loads(raw_manifest, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manifest JSON is malformed") from exc
    keys = {"schema_version", "repository", "commit", "tree", "entrypoint", "files"}
    if not isinstance(manifest, dict) or set(manifest) != keys:
        raise ValueError("manifest fields do not match the trusted schema")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("manifest schema version is unsupported")
    if manifest["repository"] != "ContextualWisdomLab/.github":
        raise ValueError("manifest tooling repository is untrusted")
    for field in ("commit", "tree"):
        if not isinstance(manifest[field], str) or not re.fullmatch(r"[0-9a-f]{40}", manifest[field]):
            raise ValueError("manifest requires immutable commit and tree identities")
    inventory = manifest["files"]
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("manifest source inventory must be nonempty")
    for name, digest in inventory.items():
        if not _safe_path(name) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("manifest source inventory contains invalid paths or digests")
    if not _safe_path(manifest["entrypoint"]) or manifest["entrypoint"] not in inventory:
        raise ValueError("manifest entrypoint is not in the accepted source inventory")
    actual = {name: hashlib.sha256(data).hexdigest() for name, data in source_files.items()}
    if manifest["files"] != actual:
        raise ValueError("tooling source inventory differs from the accepted manifest")


def require_review_scope(expected: Mapping[str, object], live: Mapping[str, object]) -> None:
    """Refuse changed PR scope before model preparation or App publication."""
    fields = {"repository", "number", "head", "base", "author", "reviewer"}
    if set(expected) != fields or set(live) != fields | {"state", "draft"}:
        raise ValueError("review scope fields are incomplete or unexpected")
    if type(live["number"]) is not int or type(expected["number"]) is not int or expected["number"] < 1:
        raise ValueError("review scope PR number is invalid")
    repository = expected["repository"]
    if not isinstance(repository, str) or not re.fullmatch(
        r"ContextualWisdomLab/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+", repository
    ):
        raise ValueError("review scope repository is outside the organization")
    for field in ("head", "base"):
        if not isinstance(expected[field], str) or not re.fullmatch(r"[0-9a-f]{40}", expected[field]):
            raise ValueError("review scope requires immutable head and base")
    for field in ("author", "reviewer"):
        if not isinstance(expected[field], str) or not expected[field].strip():
            raise ValueError("review scope identity is missing")
    if expected["author"].strip().casefold() == expected["reviewer"].strip().casefold():
        raise ValueError("review scope requires an independent reviewer")
    if live["state"] != "OPEN" or live["draft"] is not False:
        raise ValueError("review scope is closed or draft")
    if any(expected[field] != live[field] for field in fields):
        raise ValueError("review scope changed after admission")


def require_prepared_envelope(path: Path, scope: Mapping[str, object]) -> None:
    """Validate compatible eight-field model output before publisher credentials.

    This is same-invocation runner-local custody, not cross-run authenticity.
    The independently admitted tooling is responsible for substantive model
    validation; no externally supplied envelope is accepted by run_review.
    """
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
                raise ValueError("prepared envelope is not a private single-link regular file")
            raw = stream.read(2 * 1024 * 1024 + 1)
        if not 0 < len(raw) <= 2 * 1024 * 1024:
            raise ValueError("prepared envelope exceeds its bounded size")
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("prepared envelope is unavailable or malformed") from exc
    keys = {"schema_version", "repository", "pull_request_number", "expected_head",
            "expected_base", "reviewer_actor", "pull_request_author", "verdict"}
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ValueError("prepared envelope does not match compatible producer schema")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("prepared envelope schema version is invalid")
    bound = {"repository": "repository", "number": "pull_request_number",
             "head": "expected_head", "base": "expected_base",
             "author": "pull_request_author", "reviewer": "reviewer_actor"}
    if any(payload[key] != scope[field] for field, key in bound.items()):
        raise ValueError("prepared envelope identity differs from admitted scope")
    verdict = payload["verdict"]
    if not isinstance(verdict, dict) or verdict.get("decision") not in {"approve", "request_changes", "comment"}:
        raise ValueError("prepared envelope is missing a model verdict")


def require_phase_environment(phase: str, environment: Mapping[str, str]) -> None:
    """Reject loader overrides and inference capability in publisher children.

    Metadata alone cannot distinguish read/write GitHub tokens; exact token
    scope must still be verified by the trusted runtime admission adapter.
    Never include values in refusal diagnostics.
    """
    forbidden = {"PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH",
                 "DYLD_INSERT_LIBRARIES", "BASH_ENV", "ENV"}
    if any(key in environment for key in forbidden):
        raise ValueError("phase environment contains executable-loader overrides")
    if phase == "publish":
        if any(key in environment for key in ("NOEMA_LLM_API_KEY", "LLM_GATEWAY_API_KEY")):
            raise ValueError("phase environment publisher contains inference capability")
    elif phase == "prepare":
        if environment.get("NOEMA_LLM_MODEL") != "auto":
            raise ValueError("phase environment must request literal auto")
    else:
        raise ValueError("phase environment has an unsupported phase")


def accepted_prepare_transport(context):
    """Validate only independently pinned workflow/document transport capabilities.

    The enclosing execution admission digest binds these fields, not ambient
    environment values. Runtime admission still owns their namespace and supplier.
    """
    if context is None:
        return {}
    if not isinstance(context, dict) or not context or set(context) - {
        'GITHUB_OUTPUT', 'NOEMA_TRANSPORT_RETRY_ATTEMPT',
        'NOEMA_HWP_MCP_SOURCE', 'NOEMA_NODE_EXECUTABLE', 'node_sha256', 'hwp_files',
    }:
        raise ValueError('prepare transport has unsupported fields')
    for field in ('GITHUB_OUTPUT', 'NOEMA_HWP_MCP_SOURCE'):
        if field in context:
            value = context[field]
            if (not isinstance(value, str) or value != value.strip()
                    or any(ord(character) < 32 or ord(character) == 127 for character in value)):
                raise ValueError('prepare transport path differs from consumer identity')
    environment = {}
    if 'GITHUB_OUTPUT' in context or 'NOEMA_TRANSPORT_RETRY_ATTEMPT' in context:
        attempt = context.get('NOEMA_TRANSPORT_RETRY_ATTEMPT')
        if not isinstance(attempt, str) or not re.fullmatch(r'[0-2]', attempt):
            raise ValueError('prepare retry context is outside the existing bound')
        output = context.get('GITHUB_OUTPUT')
        if not isinstance(output, str) or not Path(output).is_absolute():
            raise ValueError('prepare output requires an accepted absolute path')
        info = Path(output).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError('prepare output is not private regular custody')
        environment.update(GITHUB_OUTPUT=output, NOEMA_TRANSPORT_RETRY_ATTEMPT=attempt)
    document_keys = {'NOEMA_HWP_MCP_SOURCE', 'NOEMA_NODE_EXECUTABLE', 'node_sha256', 'hwp_files'}
    if document_keys & set(context):
        if not document_keys <= set(context):
            raise ValueError('prepare document transport is incomplete')
        source, node = context['NOEMA_HWP_MCP_SOURCE'], context['NOEMA_NODE_EXECUTABLE']
        if not all(isinstance(value, str) and Path(value).is_absolute() for value in (source, node)):
            raise ValueError('prepare document supplier paths are not absolute')
        root, executable = Path(source), Path(node)
        if root.is_symlink() or not root.is_dir() or executable.is_symlink():
            raise ValueError('prepare document supplier is not regular custody')
        info = executable.stat()
        if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
            raise ValueError('prepare Node supplier is not executable')
        digest = context['node_sha256']
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('prepare Node digest is missing')
        if hashlib.sha256(executable.read_bytes()).hexdigest() != digest:
            raise ValueError('prepare Node supplier bytes changed')
        inventory = context['hwp_files']
        if not isinstance(inventory, dict) or not inventory or any(
            not _safe_path(name) or not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
            for name, value in inventory.items()
        ):
            raise ValueError('prepare HWP inventory is malformed')
        actual = {}
        for path in root.rglob('*'):
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise ValueError('prepare HWP supplier has unsupported custody')
            if path.is_file():
                actual[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != inventory:
            raise ValueError('prepare HWP supplier bytes changed')
        environment.update(NOEMA_HWP_MCP_SOURCE=source, NOEMA_NODE_EXECUTABLE=node)
    return environment


def phase_environment_from_issuance(
    phase, response, *, scope, reviewer_actor, installation_id, inference_key=None,
    prepare_transport=None,
):
    """Consume a trusted installation-token issuance response without logging it.

    The response must come directly from the existing authenticated App issuer,
    not PR data or an artifact. The controller does not mint a token, read a
    secret, or establish issuer authenticity by validating this dictionary.
    """
    expected_permissions = {"contents": "read", "metadata": "read",
                           "pull_requests": "read" if phase == "prepare" else "write"}
    if phase not in {"prepare", "publish"} or not isinstance(response, dict):
        raise ValueError("credential issuance has unsupported phase or shape")
    if response.get("permissions") != expected_permissions:
        raise ValueError("credential issuance permissions do not match the phase")
    repositories = response.get("repositories")
    if not isinstance(repositories, list) or len(repositories) != 1:
        raise ValueError("credential issuance must be single-repository scoped")
    if not isinstance(repositories[0], dict) or repositories[0].get("full_name") != scope["repository"]:
        raise ValueError("credential issuance repository does not match the review")
    token = response.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("credential issuance returned no usable token")
    if reviewer_actor != scope["reviewer"] or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\[bot\]", reviewer_actor):
        raise ValueError("credential issuance reviewer actor is not the admitted independent App")
    if type(installation_id) is not int or installation_id < 1:
        raise ValueError("credential issuance installation identity is invalid")
    environment = {"PATH": "/usr/bin:/bin", "GH_TOKEN": token,
                   "NOEMA_REVIEW_ACTOR": reviewer_actor,
                   "NOEMA_REVIEW_INSTALLATION_ID": str(installation_id),
                   "NOEMA_REVIEW_TOKEN_SOURCE": "noema-review-github-app" if phase == "prepare" else "noema-review-github-app-refresh"}
    if phase == "prepare":
        if not isinstance(inference_key, str) or not inference_key.strip():
            raise ValueError("credential issuance preparation requires existing inference authority")
        environment.update(NOEMA_LLM_MODEL="auto", NOEMA_LLM_API_KEY=inference_key,
                           NOEMA_LLM_API_URL="https://litellm.poinnetworks.net/v1/chat/completions")
        environment.update(accepted_prepare_transport(prepare_transport))
    return environment


class _NoemaTooling:
    """Execute one compatible producer/publisher from a sealed tooling namespace.

    The trusted caller owns the namespace exclusively through both phases and
    supplies phase-scoped environments, including separately attested read or
    write authority. This adapter does not authenticate an external envelope.
    Interpreter and installed third-party dependencies need independent runtime
    admission; the manifest binds repository files only.
    """

    def __init__(self, root, raw, accepted_digest, interpreter, phase_environment, child_runner):
        """Retain explicit controller dependencies without loading candidate code."""
        self.root = Path(root)
        self.raw = raw
        self.accepted_digest = accepted_digest
        self.interpreter = Path(interpreter)
        self.phase_environment = phase_environment
        self.child_runner = child_runner

    def _verify(self):
        """Re-read complete regular source files before each child invocation."""
        if not self.root.is_absolute() or self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("source inventory root is not an absolute owned directory")
        files = {}
        for path in self.root.rglob("*"):
            if path.is_symlink():
                raise ValueError("source inventory contains a symbolic link")
            if path.is_file():
                files[path.relative_to(self.root).as_posix()] = path.read_bytes()
            elif not path.is_dir():
                raise ValueError("source inventory contains an unsupported file kind")
        admit_tooling(self.raw, accepted_digest=self.accepted_digest, source_files=files)
        manifest = json.loads(self.raw)
        if manifest["entrypoint"] != ".github/actions/noema-review/two_phase.py":
            raise ValueError("source inventory entrypoint is not the compatible Noema tooling")
        return self.root / manifest["entrypoint"]

    def _run(self, phase, repo, number, head, path):
        """Run a fresh isolated-import child with explicit phase environment only."""
        entrypoint = self._verify()
        if not self.interpreter.is_absolute() or not self.interpreter.is_file():
            raise ValueError("trusted interpreter must be an absolute executable file")
        environment = self.phase_environment(phase)
        require_phase_environment(phase, environment)
        # Credential acquisition can yield to a trusted issuer; bind source
        # again afterwards so those credentials never reach stale tooling.
        entrypoint = self._verify()
        command = [str(self.interpreter), "-I", "-B", str(entrypoint),
                   "--repo", repo, "--pr-number", str(number), "--expected-head", head,
                   f"--{phase}-verdict-file", str(path)]
        result = self.child_runner(command, cwd=self.root, env=environment, check=False)
        return result.returncode

    def prepare_verdict(self, repo, number, head, path):
        """Consume PR bytes as data through the admitted model producer."""
        return self._run("prepare", repo, number, head, path)

    def publish_verdict(self, repo, number, head, path):
        """Publish only through the same compatible trusted tooling source."""
        return self._run("publish", repo, number, head, path)


def load_noema_tooling(
    root, raw_manifest, *, accepted_digest, interpreter, phase_environment,
    child_runner=subprocess.run,
):
    """Bind the real two-phase CLI without importing caller-selected modules."""
    tooling = _NoemaTooling(root, raw_manifest, accepted_digest, interpreter,
                           phase_environment, child_runner)
    tooling._verify()
    return tooling


def run_review(
    raw_manifest, *, accepted_digest, source_files, scope, fetch_live,
    require_execution_admission, load_tooling, refresh_publisher, private_parent,
):
    """Admit source and current scope before invoking trusted runtime collaborators.

    Callbacks are trusted controller dependencies, never PR payload. Their
    authority, isolation, supplier policy and source binding require separate
    operational acceptance; these checks do not manufacture such authority.
    """
    admit_tooling(raw_manifest, accepted_digest=accepted_digest, source_files=source_files)
    require_review_scope(scope, fetch_live())
    require_execution_admission()
    tooling = load_tooling()
    with tempfile.TemporaryDirectory(prefix="premerge-review-", dir=private_parent) as directory:
        envelope = Path(directory) / "verdict.json"
        result = tooling.prepare_verdict(scope["repository"], scope["number"], scope["head"], envelope)
        if result != 0 or not envelope.is_file():
            raise RuntimeError("model preparation did not produce a verdict")
        require_prepared_envelope(envelope, scope)
        require_review_scope(scope, fetch_live())
        require_execution_admission()
        refresh_publisher()
        require_review_scope(scope, fetch_live())
        require_prepared_envelope(envelope, scope)
        return tooling.publish_verdict(scope["repository"], scope["number"], scope["head"], envelope)


def production_main(argv=None):
    """Validate independently pinned custody inputs and live scope before setup.

    Files must be supplied by the existing custody owner outside PR data. This
    validates supplied evidence, not its authority: independent acceptance of
    the digest is an explicit operational prerequisite, never generated here.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--admit-production', action='store_true')
    modes.add_argument('--run-production', action='store_true')
    modes.add_argument('--prepare-production', action='store_true')
    modes.add_argument('--publish-production', action='store_true')
    parser.add_argument('--phase-issuance', type=Path)
    parser.add_argument('--verdict-file', type=Path)
    parser.add_argument('--prepare-issuance', type=Path)
    parser.add_argument('--publish-issuance', type=Path)
    parser.add_argument('--private-parent', type=Path)
    parser.add_argument('--tooling-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--accepted-digest', required=True)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--admission-digest', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr-number', type=int, required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args(argv)
    try:
        if not all(re.fullmatch(r'[0-9a-f]{64}', value) for value in
                   (args.accepted_digest, args.admission_digest)):
            raise ValueError('independent admission pins are missing or malformed')
        raw = args.manifest.read_bytes()
        tooling = _NoemaTooling(args.tooling_root, raw, args.accepted_digest,
                               Path(sys.executable), None, None)
        tooling._verify()
        admission_raw = args.admission.read_bytes()
        if hashlib.sha256(admission_raw).hexdigest() != args.admission_digest:
            raise ValueError('execution admission differs from independent pin')
        admission = json.loads(admission_raw, object_pairs_hook=_unique_object)
        scope = admission['scope']
        if scope['repository'] != args.repo or scope['number'] != args.pr_number or scope['head'] != args.expected_head:
            raise ValueError('execution admission target differs from request')
        for field in ('isolated_clean_job', 'native_custody', 'supplier_cost', 'supplier_retention', 'issuer_phase_separation'):
            if admission.get(field) is not True:
                raise ValueError('execution admission required evidence is not accepted')
        fetched = subprocess.run(['gh', 'api', f'repos/{args.repo}/pulls/{args.pr_number}'],
                                 check=True, capture_output=True, text=True, timeout=60)
        pr = json.loads(fetched.stdout)
        live = {'repository': pr['base']['repo']['full_name'], 'number': pr['number'],
                'head': pr['head']['sha'], 'base': pr['base']['sha'],
                'author': pr['user']['login'], 'reviewer': scope['reviewer'],
                'state': str(pr['state']).upper(), 'draft': pr['draft']}
        require_review_scope(scope, live)
        # Live metadata retrieval may yield while custody is revoked. Refuse
        # stale admission before either phase obtains credentials or executes.
        if args.admission.read_bytes() != admission_raw or args.manifest.read_bytes() != raw:
            raise ValueError('independent custody changed during live scope retrieval')
        if args.prepare_production or args.publish_production:
            phase = 'prepare' if args.prepare_production else 'publish'
            if args.phase_issuance is None or args.verdict_file is None:
                raise ValueError('phase issuer output and private verdict custody required')
            info = args.phase_issuance.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
                raise ValueError('issuer output custody is not private')
            response = json.loads(args.phase_issuance.read_bytes(), object_pairs_hook=_unique_object)
            environment = phase_environment_from_issuance(
                phase, response, scope=scope, reviewer_actor=scope['reviewer'],
                installation_id=admission['installation_id'],
                inference_key=os.environ.get('LLM_GATEWAY_API_KEY') if phase == 'prepare' else None,
                prepare_transport=admission.get('prepare_transport') if phase == 'prepare' else None)
            phase_tooling = load_noema_tooling(args.tooling_root, raw,
                accepted_digest=args.accepted_digest, interpreter=Path(sys.executable),
                phase_environment=lambda requested: environment if requested == phase else {})
            if phase == 'publish':
                require_prepared_envelope(args.verdict_file, scope)
            status = getattr(phase_tooling, phase + '_verdict')(
                args.repo, args.pr_number, args.expected_head, args.verdict_file)
            if phase == 'prepare' and status == 0 and args.verdict_file.exists():
                require_prepared_envelope(args.verdict_file, scope)
            return status
        if args.run_production:
            if not args.prepare_issuance or not args.publish_issuance or not args.private_parent:
                raise ValueError('phase issuance and private custody are required')
            environments = {}

            def phase_environment(phase):
                """Expose only the admitted credential for the selected phase."""
                return environments[phase]

            def read_issuance(path, phase):
                """Consume private issuer output without logging credential bytes."""
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
                    raise ValueError('issuer output is not private regular custody')
                response = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
                return phase_environment_from_issuance(
                    phase, response, scope=scope, reviewer_actor=scope['reviewer'],
                    installation_id=admission['installation_id'],
                    inference_key=os.environ.get('LLM_GATEWAY_API_KEY') if phase == 'prepare' else None,
                    prepare_transport=admission.get('prepare_transport') if phase == 'prepare' else None,
                )

            def revalidate_admission():
                """Refuse evidence or source drift at every controller boundary."""
                if args.admission.read_bytes() != admission_raw or args.manifest.read_bytes() != raw:
                    raise ValueError('independent custody changed after admission')
                tooling._verify()

            def fetch_live():
                """Re-fetch current scope before each admitted phase."""
                current = subprocess.run(['gh', 'api', f'repos/{args.repo}/pulls/{args.pr_number}'],
                                         check=True, capture_output=True, text=True, timeout=60)
                document = json.loads(current.stdout)
                return {'repository': document['base']['repo']['full_name'], 'number': document['number'],
                        'head': document['head']['sha'], 'base': document['base']['sha'],
                        'author': document['user']['login'], 'reviewer': scope['reviewer'],
                        'state': str(document['state']).upper(), 'draft': document['draft']}

            def refresh_publisher():
                """Consume separately issued publication authority only after model completion."""
                environments['publish'] = read_issuance(args.publish_issuance, 'publish')

            environments['prepare'] = read_issuance(args.prepare_issuance, 'prepare')
            files = {name: (args.tooling_root / name).read_bytes() for name in json.loads(raw)['files']}
            return run_review(raw, accepted_digest=args.accepted_digest, source_files=files,
                              scope=scope, fetch_live=fetch_live,
                              require_execution_admission=revalidate_admission,
                              load_tooling=lambda: load_noema_tooling(args.tooling_root, raw,
                                  accepted_digest=args.accepted_digest, interpreter=Path(sys.executable),
                                  phase_environment=phase_environment),
                              refresh_publisher=refresh_publisher, private_parent=args.private_parent)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # No credential values, response bodies or exception payloads in logs.
        print('premerge admission refused: independent admission pins or custody/scope evidence unavailable', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(production_main())
