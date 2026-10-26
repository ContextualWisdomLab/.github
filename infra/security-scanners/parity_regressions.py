"""Fresh native F1/F2 regressions, parameterized by exact source path."""
import hashlib,json,pathlib,runpy,subprocess,sys,tempfile,unittest
from unittest.mock import patch
SOURCE=pathlib.Path(sys.argv.pop(1)).resolve()
WRAPPER=pathlib.Path(sys.argv.pop(1)).resolve()
OUT=pathlib.Path(sys.argv.pop(1)).resolve()
M=runpy.run_path(str(SOURCE/'adapter.py'))
class ParityFindings(unittest.TestCase):
    def test_F1_all_child_timeouts_remain_caller_owned(self):
        observed=[]
        for stage in ('osv-base','osv-head','osv-base-retry','osv-head-retry','osv-report','scorecard','trivy'):
            with patch.dict(M['execute'].__globals__,verify=lambda *a:None),patch.object(subprocess,'run') as run:
                run.return_value.returncode=0
                name=pathlib.Path(M['command'](stage,SOURCE,{})[0][0]).name
                M['execute'](stage,SOURCE,{name:'0'*64},{})
                observed.append({'stage':stage,'timeout':run.call_args.kwargs.get('timeout')})
        (OUT/'F1-observed.json').write_text(json.dumps(observed,indent=2)+'\n')
        self.assertTrue(all(x['timeout'] is None for x in observed),observed)
    def test_F2_signalled_child_matches_pinned_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            exe=root/'osv-scanner'
            exe.write_text('#!'+sys.executable+'\nimport os,signal\nos.kill(os.getpid(),signal.SIGTERM)\n')
            exe.chmod(0o700)
            env={'PATH':str(root)+':/usr/bin:/bin','HOME':d,'TMPDIR':d}
            args,_=M['command']('osv-head',root,{})
            ref=subprocess.run(['/bin/bash',str(WRAPPER),'\n'.join(args[1:])],env=env,capture_output=True,timeout=5)
            conf=root/'invoke.json'
            conf.write_text(json.dumps({'root':d,'digest':hashlib.sha256(exe.read_bytes()).hexdigest()}))
            code='import runpy,pathlib,sys,json; m=runpy.run_path(sys.argv[1]); c=json.loads(pathlib.Path(sys.argv[2]).read_text()); sys.exit(m["execute"]("osv-head",pathlib.Path(c["root"]),{"osv-scanner":c["digest"]},{}))'
            actual=subprocess.run([sys.executable,'-I','-B','-c',code,str(SOURCE/'adapter.py'),str(conf)],env=env,capture_output=True,timeout=5)
            (OUT/'F2-observed.json').write_text(json.dumps({'wrapper':ref.returncode,'adapter':actual.returncode,'signal':'SIGTERM'})+'\n')
            self.assertEqual(ref.returncode,143)
            self.assertEqual(actual.returncode,ref.returncode)
if __name__=='__main__':unittest.main(verbosity=2)
