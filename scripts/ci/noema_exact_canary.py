"""Explicit non-ZDR consent for one immutable YAML, never ZDR attestation.

Consent includes disclosed gateway storage (no established finite deletion period)
and external classifier/provider/fallback recipients. No other private input is
covered. This module is inert unless the trusted Noema caller selects it.
"""
import hashlib
import json

REPOSITORY = 'ContextualWisdomLab/traveling-agent'
NUMBER = 4
HEAD = 'bf85ddde01f871f0e713db54aae5a16883777d9f'
PATH = '.github/workflows/docker-ephemeral-canary.yml'
DIGEST = '5427ca0c17d818d49f9af91b5cd495ab4599c969b894cb2467b794d674a96d3d'
SYSTEM = 'Return strict JSON only. Do not include markdown.'
INSTRUCTION = ('Independently review this exact YAML for correctness and security. '
               'Return the declared response schema. Cite changed RIGHT-side lines. '
               'For approval falsify at least two distinct concrete regression hypotheses; '
               'for request_changes confirm a concrete finding. This is a complete '
               'new file; no other repository context is authorized.\n'
               f'Repository: {REPOSITORY}\nPR: {NUMBER}\nHead: {HEAD}\nPath: {PATH}\n')


def require_target(repo, number, head):
    """Reject any repository, pull request or head outside exact consent."""
    if repo != REPOSITORY or type(number) is not int or number != NUMBER or head != HEAD:
        raise RuntimeError('Non-ZDR canary scope mismatch')


def require_content(content):
    """Admit only UTF-8 text with the explicitly consented content digest."""
    if type(content) is not str or hashlib.sha256(content.encode('utf-8')).hexdigest() != DIGEST:
        raise RuntimeError('Non-ZDR canary content scope mismatch')


def messages(content):
    """Build fixed instructions plus the digest-admitted file and nothing else."""
    require_content(content)
    return [{'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': INSTRUCTION + content}]


def validate_payload(payload):
    """Verify complete actual JSON payload; no title, threads or extra context."""
    if type(payload) is not dict or set(payload) != {'model', 'response_format', 'messages'}:
        raise RuntimeError('Non-ZDR canary payload scope mismatch')
    from scripts.ci.noema_review_gate import _noema_verdict_response_format, _required_probe_count
    if payload['response_format'] != _noema_verdict_response_format(_required_probe_count('', (PATH,))):
        raise RuntimeError('Non-ZDR canary schema scope mismatch')
    if payload['model'] != 'auto':
        raise RuntimeError('Non-ZDR canary model scope mismatch')
    rows = payload['messages']
    if type(rows) is not list or len(rows) != 2 or rows[0] != {'role': 'system', 'content': SYSTEM}:
        raise RuntimeError('Non-ZDR canary messages scope mismatch')
    row = rows[1]
    if type(row) is not dict or set(row) != {'role', 'content'} or row['role'] != 'user':
        raise RuntimeError('Non-ZDR canary message scope mismatch')
    text = row['content']
    if type(text) is not str or not text.startswith(INSTRUCTION):
        raise RuntimeError('Non-ZDR canary instruction scope mismatch')
    require_content(text[len(INSTRUCTION):])


def serialize_payload(content, response_format):
    """Serialize only approved input and fixed caller-owned schema."""
    payload = {'model': 'auto', 'response_format': response_format, 'messages': messages(content)}
    raw = json.dumps(payload).encode('utf-8')
    validate_payload(json.loads(raw))
    return raw


def main():
    """Authenticate exact target content through the existing GitHub reader."""
    import argparse
    from scripts.ci import noema_review_gate as gate
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr-number', required=True, type=int)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    require_target(args.repo, args.pr_number, args.expected_head)
    pr = gate.fetch_pr(args.repo, args.pr_number)
    gate.require_expected_head(pr, HEAD)
    if gate.fetch_changed_files(args.repo, args.pr_number) != [(PATH, 'added')]:
        raise RuntimeError('Non-ZDR canary changed-file scope mismatch')
    require_content(gate.fetch_file_content_at_ref(args.repo, PATH, HEAD))


def run_private_cli(callback):
    """Keep canary CLI failures finite without rendering private exceptions."""
    import sys
    try:
        return callback()
    except BaseException as exc:
        if isinstance(exc, SystemExit) and (exc.code is None or type(exc.code) is int):
            raise SystemExit(exc.code) from None
        if isinstance(exc, KeyboardInterrupt):
            print('::error::Non-ZDR canary interrupted; private diagnostics withheld.', file=sys.stderr)
            raise SystemExit(130) from None
        print('::error::Non-ZDR canary failed closed; private diagnostics withheld.', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    run_private_cli(main)
