"""Trusted personal LiteLLM route; never infer cost/privacy from auto or HTTP200."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BASE_URL = 'https://litellm.poinnetworks.net/v1'
MODEL = 'personal-litellm/auto'


def require_admission(*, zero_cost: bool, zero_retention: bool, private_target: bool) -> None:
    """Reject missing supplier evidence; existing key possession is not policy."""
    if zero_cost is not True:
        raise RuntimeError('STOP: personal auto zero-cost supplier is not attested')
    if private_target and zero_retention is not True:
        raise RuntimeError('STOP: private personal auto zero-retention supplier is not attested')


def configure_opencode(path: Path) -> None:
    """Reset only provider/model routing, preserving read-only agent permissions."""
    source = path.read_text(encoding='utf-8')
    # Generated workflow configs are JSON; tracked JSONC uses full-line comments.
    data = json.loads('\n'.join(line for line in source.splitlines()
                                if not line.lstrip().startswith('//')))
    data.update(model=MODEL, small_model=MODEL, enabled_providers=['personal-litellm'])
    data['provider'] = {'personal-litellm': {
        'npm': '@ai-sdk/openai-compatible', 'name': 'Personal LiteLLM auto',
        'options': {'baseURL': BASE_URL, 'apiKey': '{env:LLM_GATEWAY_API_KEY}'},
        'models': {'auto': {'name': 'Auto', 'tool_call': True,
                            'limit': {'context': 200000, 'output': 32768}}},
    }}
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    """Validate trusted nonsecret admission inputs and optionally reset config."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zero-cost', choices=('true', 'false'), required=True)
    parser.add_argument('--zero-retention', choices=('true', 'false'), required=True)
    parser.add_argument('--private-target', choices=('true', 'false'), required=True)
    parser.add_argument('--opencode-config', type=Path)
    args = parser.parse_args(argv)
    require_admission(zero_cost=args.zero_cost == 'true',
                      zero_retention=args.zero_retention == 'true',
                      private_target=args.private_target == 'true')
    if args.opencode_config is not None:
        configure_opencode(args.opencode_config)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
