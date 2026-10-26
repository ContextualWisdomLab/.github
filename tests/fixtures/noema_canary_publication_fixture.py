"""Offline external-IO adapters for the actual workflow-to-CLI composition."""


def main():
    """Run a full trusted CLI with only synthetic gh, HTTP and IO faults."""
    import base64
    import hashlib
    import json
    import os
    from pathlib import Path
    import runpy
    import socket
    import subprocess
    import sys
    import urllib.error
    import urllib.request

    root = Path(os.environ['FIXTURE_SOURCE'])
    settings = json.loads(Path(os.environ['FIXTURE_INPUT']).read_text())
    state_path = Path(os.environ['FIXTURE_STATE'])
    sys.path.insert(0, str(root))
    from scripts.ci import noema_exact_canary as policy, noema_review_gate as gate

    phase, case, marker = settings['phase'], settings['case'], settings['marker']
    content = 'name: synthetic\non: workflow_dispatch\n'
    # The only policy substitution is explicitly synthetic content provenance.
    policy.DIGEST = hashlib.sha256(content.encode()).hexdigest()
    state = {'phase': phase, 'case': case, 'external_calls': [], 'queries': [],
             'requests': [], 'posts': [], 'faults': [],
             'canary_mode': os.environ.get('NOEMA_EXACT_CANARY_NON_ZDR'),
             'argv': sys.argv[1:], 'fixture_digest_substitution': True}

    def save():
        """Persist external observations outside public CLI streams."""
        state_path.write_text(json.dumps(state, indent=2))

    def fault():
        """Raise private diagnostics only at the selected external boundary."""
        error = OSError(marker)
        error.add_note(marker)
        raise error

    def verdict():
        """Return substantive, line-cited evidence admitted by the real gate."""
        return {'decision': 'approve', 'summary': 'Synthetic exact-file review.',
                'findings': [], 'reviewed_lines': [
                    {'path': policy.PATH, 'line': 1, 'side': 'RIGHT',
                     'analysis': 'Reviewed the new workflow.'}],
                'adversarial_validation': {'status': 'passed',
                    'residual_risk': 'Offline fixture only.', 'probes': [
                        {'path': policy.PATH, 'line': i + 1, 'side': 'RIGHT',
                         'hypothesis': f'Concrete regression {i}',
                         'attack_or_counterexample': f'Concrete counterexample {i}',
                         'evidence': f'Exact line {i + 1}', 'outcome': 'falsified'}
                        for i in range(2)]}}

    def fake_run(args, **kwargs):
        """Replace only external gh IO, retaining all real gate consumers."""
        state['external_calls'].append(list(args))
        save()
        if args[:3] == ['gh', 'api', 'graphql']:
            query = kwargs.get('input', '')
            state['queries'].append(query)
            save()
            if phase == 'publish' and case == 'pr_nonzero':
                state['faults'].append('gh_stderr')
                save()
                return subprocess.CompletedProcess(args, 1, '', marker)
            pr = {'number': policy.NUMBER, 'state': 'OPEN', 'isDraft': False,
                  'headRefOid': policy.HEAD, 'baseRefOid': 'b' * 40,
                  'title': marker, 'body': marker,
                  'author': {'login': 'synthetic-author'},
                  'reviews': {'nodes': []}, 'reviewThreads': {'nodes': []}}
            if phase == 'publish':
                if case in {'cleanup_os', 'draft'}:
                    pr['isDraft'] = True
                elif case == 'head_drift':
                    pr['headRefOid'] = 'c' * 40
                elif case == 'base_drift':
                    pr['baseRefOid'] = 'c' * 40
                elif case == 'author_drift':
                    pr['author']['login'] = 'different-author'
                elif case == 'self_author':
                    pr['author']['login'] = 'cwl-noema-review[bot]'
            value = json.dumps({'data': {'repository': {'pullRequest': pr}}})
        elif args[:4] == ['gh', 'api', '-X', 'POST']:
            state['posts'].append(json.loads(kwargs['input']))
            save()
            value = '{}'
        elif args[:2] == ['gh', 'api'] and '/files' in args[2]:
            value = json.dumps([policy.PATH, 'added']) + '\n'
        elif args[:2] == ['gh', 'api'] and '/contents/' in args[2]:
            data = content.encode()
            value = json.dumps({'encoding': 'base64', 'size': len(data),
                                'content': base64.b64encode(data).decode()})
        elif args[:2] == ['gh', 'api'] and 'Accept: application/vnd.github.v3.diff' in args:
            value = (f'diff --git a/{policy.PATH} b/{policy.PATH}\n'
                     f'--- /dev/null\n+++ b/{policy.PATH}\n'
                     '@@ -0,0 +1,2 @@\n+name: synthetic\n+on: workflow_dispatch\n')
        else:
            raise AssertionError('Unexpected external operation')
        return subprocess.CompletedProcess(args, 0, value, '')

    subprocess.run = fake_run
    socket.getaddrinfo = lambda *_a, **_kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]

    class Response:
        """Synthetic successful model reply with untrusted model metadata."""
        def __enter__(self):
            """Enter the actual HTTP consumer's context."""
            return self

        def __exit__(self, *_args):
            """Preserve normal response settlement."""
            return False

        def read(self):
            """Return valid substantive evidence and a private metadata marker."""
            return json.dumps({'model': marker, 'choices': [
                {'message': {'content': json.dumps(verdict())}}]}).encode()

    class ErrorBody:
        """Synthetic capacity failure with private provider metadata."""
        def read(self, *_args):
            """Return typed and free-text telemetry through the real parser."""
            return json.dumps({'error': {'detail': {'model': marker,
                'terminal_reason': marker, 'attempts': [{'provider_name': marker,
                'phase': marker, 'attempt_number': 1,
                'provider_status': 503}]}}}).encode()

        def close(self):
            """Settle the inert error body."""
            return None

    class Opener:
        """Record real Request bytes without network dispatch."""
        def open(self, request):
            """Serve one finite synthetic HTTP outcome."""
            state['requests'].append({'url': request.full_url,
                                      'data': request.data.decode()})
            save()
            if case == 'prepare_http':
                raise urllib.error.HTTPError(request.full_url, 503, marker, {}, ErrorBody())
            return Response()

    urllib.request.build_opener = lambda *_a, **_kw: Opener()
    real_unlink, real_fsync = Path.unlink, os.fsync

    def unlink(path, *args, **kwargs):
        """Inject a reached cleanup fault without replacing its caller."""
        if phase == 'publish' and case == 'cleanup_os' and path.name == 'noema-verdict-envelope.json':
            state['faults'].append('cleanup_os')
            save()
            fault()
        return real_unlink(path, *args, **kwargs)

    def fsync(fd):
        """Inject preparation persistence failure through a real file owner."""
        if phase == 'prepare' and case == 'prepare_fsync_os':
            state['faults'].append('prepare_fsync_os')
            save()
            fault()
        return real_fsync(fd)

    Path.unlink, os.fsync = unlink, fsync

    def audit(event, _args):
        """Forbid every unadapted process or socket operation."""
        if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
            raise AssertionError('Offline fixture IO fence')

    sys.addaudithook(audit)
    save()
    argv = sys.argv[1:]
    if argv[:1] == ['-m']:
        module = argv[1]
        sys.argv = [module, *argv[2:]]
        if module == 'scripts.ci.noema_exact_canary':
            # Execute its complete real CLI, substituting only the fixture digest.
            path = root / 'scripts/ci/noema_exact_canary.py'
            text = path.read_text()
            old = "DIGEST = '5427ca0c17d818d49f9af91b5cd495ab4599c969b894cb2467b794d674a96d3d'"
            assert text.count(old) == 1
            text = text.replace(old, 'DIGEST = ' + repr(policy.DIGEST))
            exec(compile(text, str(path), 'exec'), {'__name__': '__main__', '__file__': str(path)})
        else:
            assert module == 'scripts.ci.personal_review_route'
            runpy.run_module(module, run_name='__main__')
    else:
        assert argv[0] == str(root / '.github/actions/noema-review/two_phase.py')
        sys.argv = argv
        runpy.run_path(argv[0], run_name='__main__')


if __name__ == '__main__':
    main()
