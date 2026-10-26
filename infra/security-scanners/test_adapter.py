import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import adapter

class AdapterTests(unittest.TestCase):
    def test_osv_scan_flags(self):
        args, env = adapter.command('osv-base', '/trusted', {})
        self.assertEqual(args[1:], ['--format=json','--output-file=old-results.json','--maven-registry=https://maven-central.storage-download.googleapis.com/maven2','--no-resolve','--allow-no-lockfiles','-r','source/'])
        self.assertEqual(env['GOTOOLCHAIN'], 'auto')
    def test_retry(self):
        args,_=adapter.command('osv-head-retry','/trusted',{})
        self.assertIn('--output-file=new-results.json',args)
        self.assertFalse(any('maven-registry' in x for x in args))
    def test_reporter(self):
        args,_=adapter.command('osv-report','/trusted',{})
        self.assertEqual(args[1:],['--output-files=results.sarif','--old=old-results.json','--new=new-results.json','--gh-annotations=true','--fail-on-vuln=true'])
    def test_scorecard_scope(self):
        supplied={'GITHUB_TOKEN':'test-token','GITHUB_EVENT_PATH':'/event.json','GITHUB_EVENT_NAME':'pull_request','GITHUB_WORKSPACE':'/work','GITHUB_REPOSITORY':'org/repo','GITHUB_REF':'refs/pull/1/merge','AWS_SECRET_ACCESS_KEY':'must-not-flow','INPUT_PUBLISH_RESULTS':'true','ENABLED_CHECKS':'none'}
        args,env=adapter.command('scorecard','/trusted',supplied)
        self.assertEqual(env['INPUT_PUBLISH_RESULTS'],'false')
        self.assertEqual(env['INPUT_FILE_MODE'],'archive')
        self.assertEqual(env['INPUT_REPO_TOKEN'],'test-token')
        self.assertNotIn('AWS_SECRET_ACCESS_KEY',env)
        self.assertNotIn('ENABLED_CHECKS',env)
    def test_trivy_flags(self):
        args,_=adapter.command('trivy','/trusted',{})
        self.assertIn('--severity=CRITICAL,HIGH,MEDIUM',args)
        self.assertIn('--ignore-unfixed',args)
        self.assertIn('--exit-code=0',args)
        self.assertIn('--scanners=vuln,secret,misconfig',args)
    def test_unknown(self):
        with self.assertRaises(ValueError):adapter.command('shell','/trusted',{})
    def test_verify_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'osv-scanner';p.write_bytes(b'bad')
            with self.assertRaises(ValueError):adapter.verify(Path(d),{'osv-scanner':'0'*64})
    def test_status_not_overwritten(self):
        with patch('adapter.verify'),patch('adapter.subprocess.run') as run:
            run.return_value.returncode=1
            self.assertEqual(adapter.execute('osv-head',Path('/trusted'),{'osv-scanner':'0'*64},{}),1)
            run.return_value.returncode=128
            self.assertEqual(adapter.execute('osv-head',Path('/trusted'),{'osv-scanner':'0'*64},{}),0)
    def test_no_docker(self):
        for stage in ['osv-base','osv-head','osv-report','trivy']:
            args,env=adapter.command(stage,'/trusted',{})
            self.assertNotIn('docker',' '.join(args))
            self.assertNotIn('DOCKER_HOST',env)

if __name__=='__main__':unittest.main()
