"""Preserve authenticated phase issuance bytes in explicit private custody.

The request and revalidation collaborators belong to the existing trusted App
issuer/runtime owner. This module neither authenticates arbitrary dictionaries
nor admits native execution from source acceptance or token-action metadata.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.premerge_review_tooling import _unique_object


MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def materialize_tooling(source_root, target_root, raw_manifest, *, accepted_digest,
                        admission, private_parent):
    """Copy exactly externally admitted inert source into a separate namespace.

    Supplied acceptance must be independently authenticated by the runtime owner.
    This checks its contract and bytes; it never creates acceptance evidence.
    The parent is held exclusively by that owner, not defended against same-UID
    or privileged namespace mutation by directory permission bits alone.
    """
    import hashlib
    import sys
    from scripts.ci.premerge_review_tooling import load_noema_tooling
    parent, source, target = map(Path, (private_parent, source_root, target_root))
    if (not parent.is_absolute() or not source.is_absolute() or not target.is_absolute()
            or target.parent != parent or source == target or parent.is_relative_to(source)):
        raise ValueError('bootstrap namespace refused')
    if any(path.is_symlink() for path in (parent, *parent.parents, source)):
        raise ValueError('bootstrap namespace refused')
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or os.path.lexists(target)):
        raise ValueError('bootstrap namespace refused')
    if admission.get('namespace') != str(parent):
        raise ValueError('bootstrap namespace differs from independent admission')
    for field in ('isolated_clean_job', 'native_custody', 'supplier_cost',
                  'supplier_retention', 'issuer_phase_separation'):
        if admission.get(field) is not True:
            raise ValueError('bootstrap execution evidence is not accepted')
    _validate_runtime(admission, parent)
    tooling = load_noema_tooling(source, raw_manifest, accepted_digest=accepted_digest,
        interpreter=Path(sys.executable).resolve(), phase_environment=lambda _: {})
    inventory = json.loads(raw_manifest)['files']
    target.mkdir(mode=0o700)
    for name, digest in inventory.items():
        raw = (source / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('bootstrap source changed during delivery')
        destination = target / name
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400), 'wb') as stream:
            stream.write(raw)
    tooling._verify()
    load_noema_tooling(target, raw_manifest, accepted_digest=accepted_digest,
        interpreter=Path(sys.executable).resolve(), phase_environment=lambda _: {})
    return target


def _validate_runtime(admission, parent):
    """Rebind explicit namespace, interpreter, dependencies and required admission."""
    import hashlib
    parent = Path(parent)
    if not parent.is_absolute() or any(path.is_symlink() for path in (parent, *parent.parents)):
        raise ValueError('bootstrap namespace refused')
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or admission.get('namespace') != str(parent)):
        raise ValueError('bootstrap namespace refused')
    for field in ('isolated_clean_job', 'native_custody', 'supplier_cost',
                  'supplier_retention', 'issuer_phase_separation'):
        if admission.get(field) is not True:
            raise ValueError('bootstrap execution evidence unavailable')
    interpreter = admission.get('interpreter')
    actual_interpreter = Path(sys.executable).resolve()
    if (not isinstance(interpreter, dict) or set(interpreter) != {'path', 'sha256'}
            or interpreter['path'] != str(actual_interpreter)
            or hashlib.sha256(actual_interpreter.read_bytes()).hexdigest() != interpreter['sha256']):
        raise ValueError('bootstrap interpreter differs from independent admission')
    dependencies = admission.get('dependencies')
    if not isinstance(dependencies, dict):
        raise ValueError('bootstrap dependency inventory unavailable')
    for name, digest in dependencies.items():
        path = Path(name)
        if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError('bootstrap dependency differs from independent admission')


def _response(raw):
    """Parse bounded original API bytes without reflecting credential payloads."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RESPONSE_BYTES:
        raise ValueError('issuer response size or type refused')
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError):
        raise ValueError('issuer response schema refused') from None
    if not isinstance(value, dict):
        raise ValueError('issuer response schema refused')
    return value


def run_bootstrap_review(source_root, raw_manifest, *, accepted_digest, admission,
                         private_parent, fetch_live, request, revalidate,
                         inference_key):
    """Compose actual admitted tooling, original App response and two children.

    Trusted runtime callbacks are externally held authority; this function only
    checks their supplied admission and orders preparation before the separately
    minted write token. No supplier policy is inferred from source or fixtures.
    """
    import hashlib
    import subprocess
    from scripts.ci.premerge_review_tooling import (
        load_noema_tooling, phase_environment_from_issuance,
        require_prepared_envelope, require_review_scope,
    )
    scope = admission['scope']
    parent = Path(private_parent)
    source = Path(source_root)
    target = materialize_tooling(source, parent / 'tooling', raw_manifest,
        accepted_digest=accepted_digest, admission=admission, private_parent=parent)
    if not isinstance(inference_key, str) or not inference_key.strip():
        raise ValueError('existing inference authority unavailable')
    envs = {}
    def fence():
        """Revalidate supplier, source, admitted scope and external authority."""
        revalidate()
        if hashlib.sha256(raw_manifest).hexdigest() != accepted_digest:
            raise ValueError('bootstrap source pin changed')
        live = fetch_live()
        require_review_scope(scope, live)
        from scripts.ci.premerge_review_tooling import admit_tooling
        inventory = json.loads(raw_manifest)['files']
        files = {name: (target / name).read_bytes() for name in inventory}
        admit_tooling(raw_manifest, accepted_digest=accepted_digest, source_files=files)
    def issue(phase):
        """Store exact authenticated response privately and consume its grant."""
        fence()
        path = parent / (phase + '.json')
        produce_issuance(phase, scope=scope, installation_id=admission['installation_id'],
            app_id=admission['app_id'], output=path, private_parent=parent,
            request=request, revalidate=fence)
        fence()
        response = _response(path.read_bytes())
        return phase_environment_from_issuance(phase, response,
            scope=scope, reviewer_actor=scope['reviewer'],
            installation_id=admission['installation_id'],
            inference_key=inference_key if phase == 'prepare' else None)
    fence()
    envs['prepare'] = issue('prepare')
    tooling = load_noema_tooling(target, raw_manifest,
        accepted_digest=accepted_digest, interpreter=Path(__import__('sys').executable),
        phase_environment=lambda phase: envs[phase])
    verdict = parent / 'verdict.json'
    if tooling.prepare_verdict(scope['repository'], scope['number'], scope['head'], verdict) != 0:
        raise ValueError('model preparation failed')
    require_prepared_envelope(verdict, scope)
    fence()
    # No write grant can be requested until preparation and live revalidation.
    envs['publish'] = issue('publish')
    fence()
    require_prepared_envelope(verdict, scope)
    return tooling.publish_verdict(scope['repository'], scope['number'], scope['head'], verdict)


def produce_issuance(phase, *, scope, installation_id, app_id, output,
                     private_parent, request, revalidate):
    """Request exact phase grant and exclusively store the unchanged response.

    Authenticated request supplies original response bytes from the same App
    transport. The caller must independently bind that collaborator, namespace,
    and installations; structural checks alone do not establish issuer authority.
    Publish revalidation must include the prepared envelope and live head/base.
    No inference credential is consumed here or attached to an issuer request.
    """
    if phase not in ('prepare', 'publish'):
        raise ValueError('issuer phase refused')
    if any(type(value) is not int or value < 1 for value in (installation_id, app_id)):
        raise ValueError('issuer identity refused')
    repository = scope['repository']
    # Validate repository grammar with the same canonical controller contract.
    import re
    if not isinstance(repository, str) or not re.fullmatch(
            r'ContextualWisdomLab/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+', repository):
        raise ValueError('issuer repository refused')
    if scope['reviewer'] != 'cwl-noema-review[bot]':
        raise ValueError('issuer actor refused')
    parent, target = Path(private_parent), Path(output)
    if not parent.is_absolute() or not target.is_absolute() or target.parent != parent:
        raise ValueError('issuer output namespace refused')
    for ancestor in (parent, *parent.parents):
        if ancestor.is_symlink():
            raise ValueError('issuer output namespace refused')
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('issuer output namespace refused')
    if os.path.lexists(target):
        raise ValueError('issuer output already exists')
    revalidate()
    app = _response(request('GET', '/app', None))
    if type(app.get('id')) is not int or app.get('id') != app_id or app.get('slug') != 'cwl-noema-review':
        raise ValueError('issuer App identity refused')
    revalidate()
    installation = _response(request('GET', '/repos/' + repository + '/installation', None))
    if (type(installation.get('id')) is not int or type(installation.get('app_id')) is not int
            or installation.get('id') != installation_id or installation.get('app_id') != app_id):
        raise ValueError('issuer installation refused')
    revalidate()
    permissions = {'contents': 'read', 'metadata': 'read',
                   'pull_requests': 'read' if phase == 'prepare' else 'write'}
    raw = request('POST', f'/app/installations/{installation_id}/access_tokens',
                  {'repositories': [repository.split('/', 1)[1]], 'permissions': permissions})
    response = _response(raw)
    if response.get('permissions') != permissions:
        raise ValueError('issuer phase grant refused')
    repositories = response.get('repositories')
    if (not isinstance(repositories, list) or len(repositories) != 1
            or not isinstance(repositories[0], dict)
            or repositories[0].get('full_name') != repository):
        raise ValueError('issuer response repository refused')
    if not isinstance(response.get('token'), str) or not response['token'].strip():
        raise ValueError('issuer token missing')
    revalidate()
    current = parent.lstat()
    if (current.st_dev, current.st_ino, current.st_mode, current.st_uid) != (
            info.st_dev, info.st_ino, info.st_mode, info.st_uid):
        raise ValueError('issuer output custody changed')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Retain incomplete private bytes for the existing custody owner;
        # never overwrite/retry a secret-bearing output after ambiguous I/O.
        raise
    return target


def _private_bytes(path, parent):
    """Read one bounded private single-link credential input without diagnostics."""
    path, parent = Path(path), Path(parent)
    if not path.is_absolute() or path.parent != parent or parent.is_symlink():
        raise ValueError('private credential namespace refused')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError('private credential custody refused')
        raw = os.read(fd, MAX_RESPONSE_BYTES + 1)
        if not 0 < len(raw) <= MAX_RESPONSE_BYTES:
            raise ValueError('private credential size refused')
        return raw
    finally:
        os.close(fd)


def authenticated_transport(jwt_file, private_parent, *, opener=None):
    """Use the existing externally supplied App JWT on fixed GitHub routes only.

    The runtime owner provides and refreshes this private credential; this helper
    neither signs a JWT nor reads an App private key. Injected openers are trusted
    test collaborators, not PR inputs. No redirect or ambient proxy is admitted.
    """
    import re
    import urllib.request
    jwt = _private_bytes(jwt_file, private_parent).decode('ascii')
    if not jwt or any(character.isspace() for character in jwt):
        raise ValueError('existing App authentication unavailable')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        """Reject credential forwarding before any redirected request dispatch."""
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            """Keep every response on the independently fixed issuer origin."""
            return None
    if opener is None:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()).open
    def request(method, route, payload):
        """Return unchanged bounded body bytes from an exact authenticated request."""
        get = method == 'GET' and (route == '/app' or re.fullmatch(
            r'/repos/ContextualWisdomLab/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+/installation', route))
        post = method == 'POST' and re.fullmatch(r'/app/installations/[1-9][0-9]*/access_tokens', route)
        if not (get or post) or (get and payload is not None):
            raise ValueError('issuer endpoint refused')
        body = json.dumps(payload, allow_nan=False).encode() if post else None
        req = urllib.request.Request('https://api.github.com' + route, data=body,
            method=method, headers={'Authorization': 'Bearer ' + jwt,
                'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
                'Content-Type': 'application/json'})
        with opener(req, timeout=60) as response:
            headers = getattr(response, 'headers', {})
            length = headers.get('Content-Length')
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if (not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RESPONSE_BYTES
                    or (length is not None and (not str(length).isdigit() or int(length) != len(raw)))):
                raise ValueError('issuer response framing refused')
            return raw
    return request


def main(argv=None):
    """Consume independently pinned bootstrap inputs, refusing absent admission."""
    import argparse
    import hashlib
    import re
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--materialize', action='store_true')
    modes.add_argument('--issue-prepare', action='store_true')
    modes.add_argument('--issue-publish', action='store_true')
    modes.add_argument('--revalidate-publish', action='store_true')
    modes.add_argument('--revalidate-prepare', action='store_true')
    parser.add_argument('--private-parent', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--accepted-digest', required=True)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--admission-digest', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr-number', type=int, required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--app-jwt-file', type=Path)
    parser.add_argument('--verdict-file', type=Path)
    args = parser.parse_args(argv)
    try:
        if not all(re.fullmatch(r'[0-9a-f]{64}', value) for value in
                   (args.accepted_digest, args.admission_digest)):
            raise ValueError('bootstrap independent pins unavailable')
        raw = args.manifest.read_bytes()
        admission_raw = args.admission.read_bytes()
        if hashlib.sha256(admission_raw).hexdigest() != args.admission_digest:
            raise ValueError('bootstrap admission pin refused')
        admission = _response(admission_raw)
        scope = admission['scope']
        if (scope['repository'], scope['number'], scope['head']) != (
                args.repo, args.pr_number, args.expected_head):
            raise ValueError('bootstrap target refused')
        if args.materialize:
            materialize_tooling(args.source_root, args.private_parent / 'tooling', raw,
                accepted_digest=args.accepted_digest, admission=admission,
                private_parent=args.private_parent)
            return 0
        from scripts.ci.premerge_review_tooling import (
            require_prepared_envelope, require_review_scope, load_noema_tooling,
        )
        def fence():
            """Bind original pins, actual admitted tooling and fresh live metadata."""
            if (args.manifest.read_bytes() != raw
                    or args.admission.read_bytes() != admission_raw):
                raise ValueError('bootstrap external pins changed')
            tooling = args.private_parent / 'tooling'
            _validate_runtime(admission, args.private_parent)
            load_noema_tooling(tooling, raw, accepted_digest=args.accepted_digest,
                interpreter=Path(sys.executable), phase_environment=lambda _: {})
            pr = json.loads(subprocess.run(['gh', 'api', f'repos/{args.repo}/pulls/{args.pr_number}'],
                capture_output=True, text=True, check=True, timeout=60).stdout)
            require_review_scope(scope, {'repository':pr['base']['repo']['full_name'],
                'number':pr['number'],'head':pr['head']['sha'],'base':pr['base']['sha'],
                'author':pr['user']['login'],'reviewer':scope['reviewer'],
                'state':str(pr['state']).upper(),'draft':pr['draft']})
            if (args.manifest.read_bytes() != raw
                    or args.admission.read_bytes() != admission_raw):
                raise ValueError('bootstrap external pins changed during live read')
            load_noema_tooling(tooling, raw, accepted_digest=args.accepted_digest,
                interpreter=Path(sys.executable), phase_environment=lambda _: {})
            for field in ('isolated_clean_job', 'native_custody', 'supplier_cost',
                          'supplier_retention', 'issuer_phase_separation'):
                if admission.get(field) is not True:
                    raise ValueError('bootstrap execution evidence unavailable')
            _validate_runtime(admission, args.private_parent)
            if args.issue_publish or args.revalidate_publish:
                if args.verdict_file != args.private_parent / 'verdict.json':
                    raise ValueError('bootstrap envelope namespace refused')
                require_prepared_envelope(args.verdict_file, scope)
        if args.revalidate_publish or args.revalidate_prepare:
            fence()
            return 0
        if args.app_jwt_file is None:
            raise ValueError('authenticated issuer transport unavailable')
        fence()
        transport = authenticated_transport(args.app_jwt_file, args.private_parent)
        phase = 'publish' if args.issue_publish else 'prepare'
        produce_issuance(phase, scope=scope, installation_id=admission['installation_id'],
            app_id=admission['app_id'], output=args.private_parent / (phase+'.json'),
            private_parent=args.private_parent, request=transport, revalidate=fence)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Noema bootstrap refused: independent issuer or custody input unavailable', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
