"""Offline exact-member recovery from retained, digest-pinned public artifacts.

Not a PR-job downloader. Public reacquisition is a separately retained bounded
transaction; this helper verifies its bytes before selecting any member. Never
extract archive paths and never silently replace an existing output directory.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

ROOT = Path(__file__).resolve().parent
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_MEMBERS = 128
IMAGES = {
    'osv-scanner-action': ('dcd947131d8d11b8d0964de6590661fb921a4ecbd7b90a7cb21083acfc3fd8cc', {
        8: ('root/osv-scanner', 'osv-scanner', 'e2ab0a11b6b4ec7fca688409afb23428b2f66a4c223678b87fc74bdc68b66bcc', 57725090),
        9: ('root/osv-reporter', 'osv-reporter', 'e50a74ead4cbbb6856858643480bfd71086ae6b1ce0752f7929869dd140258e4', 45949090),
        10: ('root/exit_code_redirect.sh', 'exit_code_redirect.sh', None, 4096),
    }),
    'scorecard-action': ('2dd6a6d60100f78ef24e14a47941d0087a524b4d3642041558239b1c6097c941', {
        14: ('scorecard-action', 'scorecard-action', 'f701f40311e288d7fb2a9d65a9a7fe7e2b4241b34eb9bd89a8dd73245c388a6a', 115870642),
        15: ('policy.yml', 'policy.yml', '6e75dcc0df989d333492c0e1f6e484fc5b4d26ab768333ddcd0e3788539689b0', 1609),
    }),
}
GITLEAKS_ARCHIVE = '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb'
GITLEAKS_BINARY = '88f91962aa2f93ac6ab281d553b9e125f5197bbbce38f9f2437f7299c32e5509'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verified_bytes(data, descriptor):
    size, digest = descriptor.get('size'), descriptor.get('digest')
    if (type(size) is not int or not 0 <= size <= MAX_ARCHIVE or
            type(digest) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest) or
            len(data) != size or 'sha256:' + sha(data) != digest):
        raise ValueError('artifact identity mismatch')
    return data


def read_bounded(path, limit=MAX_ARCHIVE):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('artifact file refused')
    with path.open('rb') as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError('artifact size refused')
    return data


def verified_members(data, descriptor, expected, diff_id=None):
    """Return unique exact regular member bytes after whole-archive admission.

    Reject duplicate paths/basenames, aliases, links (including parent links),
    devices and sparse files even when they would not be extracted. Full bounded
    decompression also permits independent OCI uncompressed diff-ID verification.
    """
    verified_bytes(data, descriptor)
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
        raw = f.read(MAX_EXPANDED + 1)
    if len(raw) > MAX_EXPANDED:
        raise ValueError('expanded archive limit')
    if diff_id is not None and 'sha256:' + sha(raw) != diff_id:
        raise ValueError('layer diff identity mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = {}
        basenames = {}
        for member in archive:
            name = member.name
            parts = name.split('/')
            if (not name or name.startswith('/') or '\\' in name or '\x00' in name or
                    any(p in ('', '.', '..') for p in parts) or name in members or
                    not (member.isreg() or member.isdir()) or member.issparse() or
                    member.size < 0):
                raise ValueError('unsafe or duplicate archive member')
            members[name] = member
            basenames.setdefault(PurePosixPath(name).name, []).append(name)
            if len(members) > MAX_MEMBERS:
                raise ValueError('archive member limit')
        result = {}
        for path, (output, digest, limit) in expected.items():
            if path not in members or len(basenames.get(PurePosixPath(path).name, [])) != 1:
                raise ValueError('exact unique member absent')
            member = members[path]
            if not member.isreg() or not 0 < member.size <= limit:
                raise ValueError('selected regular member refused')
            for parent in PurePosixPath(path).parents:
                if str(parent) in members and not members[str(parent)].isdir():
                    raise ValueError('archive parent is not a directory')
            with archive.extractfile(member) as f:
                blob = f.read(limit + 1)
            if len(blob) != member.size or (digest is not None and sha(blob) != digest):
                raise ValueError('member identity mismatch')
            if output in result:
                raise ValueError('duplicate output name')
            result[output] = blob
        return result


def recover(evidence, output):
    """Verify all inputs before exclusively creating the owner-selected output."""
    files = {}
    receipts = []
    for image, (pin, selected) in IMAGES.items():
        raw = read_bounded(evidence / (image + '.manifest.raw.json'), 65536)
        if sha(raw) != pin:
            raise ValueError('manifest pin mismatch')
        manifest = json.loads(raw)
        config_data = read_bounded(evidence / (image + '.config.raw.json'), 65536)
        verified_bytes(config_data, manifest['config'])
        config = json.loads(config_data)
        if config.get('architecture') != 'amd64' or config.get('os') != 'linux':
            raise ValueError('image platform mismatch')
        for index, (member, name, digest, limit) in selected.items():
            descriptor = manifest['layers'][index]
            archive = evidence / (descriptor['digest'].split(':')[1] + '.tar.gz')
            blobs = verified_members(read_bounded(archive), descriptor,
                {member: (name, digest, limit)}, config['rootfs']['diff_ids'][index])
            if files.keys() & blobs.keys():
                raise ValueError('duplicate recovered output')
            files.update(blobs)
            receipts.append({'image': image, 'manifest': pin, 'layer': descriptor['digest'],
                             'member': member, 'output': name, 'sha256': sha(files[name])})
    release = read_bounded(evidence / 'gitleaks_8.30.1_linux_x64.tar.gz')
    checksum_lines = read_bounded(evidence / 'gitleaks_8.30.1_checksums.txt', 65536).decode('ascii').splitlines()
    matches = [line.split() for line in checksum_lines if len(line.split()) == 2 and line.split()[1] == 'gitleaks_8.30.1_linux_x64.tar.gz']
    if matches != [[GITLEAKS_ARCHIVE, 'gitleaks_8.30.1_linux_x64.tar.gz']]:
        raise ValueError('release checksum transaction mismatch')
    metadata = json.loads(read_bounded(evidence / 'gitleaks-v8.30.1-release.json', 1048576))
    assets = [a for a in metadata['assets'] if a['name'] == 'gitleaks_8.30.1_linux_x64.tar.gz']
    if len(assets) != 1 or assets[0]['digest'] != 'sha256:' + GITLEAKS_ARCHIVE or metadata['tag_name'] != 'v8.30.1':
        raise ValueError('release metadata mismatch')
    files.update(verified_members(release, {'size': assets[0]['size'], 'digest': 'sha256:' + GITLEAKS_ARCHIVE},
                 {'gitleaks': ('gitleaks', GITLEAKS_BINARY, 21958840)}))
    receipts.append({'release': 'v8.30.1', 'asset_id': assets[0]['id'], 'archive': GITLEAKS_ARCHIVE,
                     'member': 'gitleaks', 'output': 'gitleaks', 'sha256': sha(files['gitleaks'])})
    output.mkdir(mode=0o700, exist_ok=False)
    for name, blob in files.items():
        with (output / name).open('xb') as f:
            f.write(blob)
        (output / name).chmod(0o444 if name == 'policy.yml' else 0o555)
    inventory = {name: sha(blob) for name, blob in files.items() if name != 'exit_code_redirect.sh'}
    (output / 'inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
    (output / 'membership.json').write_text(json.dumps(receipts, indent=2) + '\n')
    return receipts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    receipts = recover(args.evidence, args.output)
    print(json.dumps({'verified_members': len(receipts), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
