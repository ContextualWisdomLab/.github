"""Explicit offline fixture-only GitHub CLI, denying all writes/endpoints."""
import json
from pathlib import Path
import sys
import os

fixture = json.loads(Path(os.environ['FIXTURE_FILE']).read_text())
args = sys.argv[1:]
with Path(fixture['calls']).open('a') as handle:
    handle.write(json.dumps(args) + '\n')
if any(x in args for x in ('POST', 'PATCH', 'PUT', 'DELETE', '--method', '-X')):
    raise SystemExit('fixture forbids mutations')
if not args or args[0] != 'api':
    raise SystemExit('fixture only permits api reads')
endpoints = [x for x in args[1:] if x.startswith('repos/')]
if len(endpoints) != 1:
    raise SystemExit('fixture requires one endpoint')
endpoint = endpoints[0]
if endpoint == 'repos/ContextualWisdomLab/fast-mlsirm/pulls/2018':
    print(json.dumps(fixture['pull']))
elif endpoint.startswith('repos/ContextualWisdomLab/fast-mlsirm/pulls/2018/reviews'):
    if fixture['lookup_fail']:
        print('fixture read failure', file=sys.stderr)
        raise SystemExit(1)
    if fixture['malformed']:
        print('not-json')
    else:
        print(json.dumps([fixture['reviews']] if '--slurp' in args else fixture['reviews']))
elif endpoint == 'repos/ContextualWisdomLab/.github/contents/scripts/ci/opencode_review_receipt_gate.py?ref=6a37e4cdfbd8bf6f3a60645a0ad7c13e1b9c1ae3':
    if args[-2:] != ['--jq', '.content']:
        raise SystemExit('fixture expects pinned content field')
    print(fixture['helper_base64'])
else:
    raise SystemExit('fixture rejects endpoint outside exact bounded contract')
