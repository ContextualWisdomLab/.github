"""Bound the R matrix to supported Linux/x64 image aliases, never runner labels."""
import json
import sys


def admit(raw):
    rows = json.loads(raw)
    if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
        raise ValueError('Expected 1..64 matrix objects')
    supported = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('os'), str):
            raise ValueError('Expected an OS string in each matrix object')
        if not isinstance(row.get('r'), str) or not row['r'].strip():
            raise ValueError('Expected a nonempty R version')
        if row['os'] in ('ubuntu-latest', 'ubuntu-24.04'):
            supported.append(row)
        else:
            print('STOP unsupported platform leg: ' + repr(row['os']), file=sys.stderr)
    if not supported:
        raise ValueError('STOP: no supported Linux/x64 legs; no check was executed')
    return supported


if __name__ == '__main__':
    try:
        print(json.dumps(admit(sys.argv[1]), separators=(',', ':')))
    except (ValueError, TypeError, IndexError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
