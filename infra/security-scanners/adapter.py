#!/usr/bin/env python3
"""Trusted workload-image CLI. Invoke with python3 -I; never from PR checkout.
No Docker client, arbitrary command, download, or host operation exists here.
Binary inventory is supplied by the image owner, not by the pull request.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def verify(root, inventory):
    for name, digest in inventory.items():
        if name not in {'osv-scanner','osv-reporter','scorecard-action','policy.yml','trivy','gitleaks'}:
            raise ValueError('unknown inventory entry')
        path = root / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('trusted tool integrity failure: '+name)


def command(stage, root, supplied):
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
           'HOME': '/work/home', 'TMPDIR': '/tmp'}
    exe = lambda name: str(Path(root)/name)
    if stage in ('osv-base','osv-head','osv-base-retry','osv-head-retry'):
        output = 'old-results.json' if 'base' in stage else 'new-results.json'
        args = [exe('osv-scanner'),'--format=json','--output-file='+output]
        if not stage.endswith('retry'):
            args += ['--maven-registry=https://maven-central.storage-download.googleapis.com/maven2']
        args += ['--no-resolve','--allow-no-lockfiles','-r','source/']
        env['GOTOOLCHAIN']='auto'
    elif stage == 'osv-report':
        args=[exe('osv-reporter'),'--output-files=results.sarif','--old=old-results.json',
              '--new=new-results.json','--gh-annotations=true','--fail-on-vuln=true']
    elif stage == 'scorecard':
        args=[exe('scorecard-action')]
        for key in ('GITHUB_EVENT_PATH','GITHUB_EVENT_NAME','GITHUB_REF','GITHUB_REPOSITORY',
                    'GITHUB_WORKSPACE','GITHUB_API_URL'):
            if key in supplied: env[key]=supplied[key]
        env.update(INPUT_RESULTS_FILE='results.sarif',INPUT_RESULTS_FORMAT='sarif',
                   INPUT_PUBLISH_RESULTS='false',INPUT_FILE_MODE='archive',
                   INPUT_INTERNAL_PUBLISH_BASE_URL='https://api.scorecard.dev',
                   INPUT_REPO_TOKEN=supplied.get('GITHUB_TOKEN',''),
                   INPUT_INTERNAL_DEFAULT_TOKEN=supplied.get('GITHUB_TOKEN',''))
        # The original binary requires /policy.yml. Image recipe installs it there.
    elif stage == 'trivy':
        args=[exe('trivy'),'fs','.', '--scanners=vuln,secret,misconfig',
              '--severity=CRITICAL,HIGH,MEDIUM','--ignore-unfixed', '--format=sarif',
              '--output=trivy-results.sarif','--exit-code=0', '--cache-dir=.cache/trivy']
    else:
        raise ValueError('unknown scanner stage')
    return args,env


def execute(stage, root, inventory, supplied):
    verify(root,inventory)
    args,env=command(stage,root,supplied)
    required=Path(args[0]).name
    if required not in inventory:
        raise ValueError('scanner absent from trusted inventory')
    # upstream Scorecard Validate prints the token. Suppress raw output entirely;
    # artifact is still written and original exit retained. Never log raw token.
    quiet=stage=='scorecard'
    # Timeout/cancellation belongs to the invoking Actions step/job, including
    # reporter's 25-minute job and Scorecard's inherited default job budget.
    # Do not introduce a second, shorter subprocess deadline here.
    result=subprocess.run(args,env=env,stdout=subprocess.DEVNULL if quiet else None,
                          stderr=subprocess.DEVNULL if quiet else None)
    # subprocess represents a terminating signal as -N; Bash/Actions returns
    # 128+N. Normalize before applying the scan-only exit128 compatibility rule.
    code = 128 - result.returncode if result.returncode < 0 else result.returncode
    return 0 if stage.startswith('osv-') and stage != 'osv-report' and code == 128 else code


def main():
    p=argparse.ArgumentParser()
    p.add_argument('stage',choices=['osv-base','osv-head','osv-base-retry','osv-head-retry','osv-report','scorecard','trivy'])
    a=p.parse_args()
    root=Path('/opt/security')
    inventory=json.loads((root/'inventory.json').read_text())
    return execute(a.stage,root,inventory,os.environ)

if __name__=='__main__':
    sys.exit(main())
