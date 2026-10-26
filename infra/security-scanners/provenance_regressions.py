"""Exact legacy acquisition versus successor member admission; synthetic bytes only."""
import contextlib,hashlib,io,json,pathlib,runpy,sys,tarfile,tempfile,unittest,urllib.request
from unittest.mock import patch
SOURCE=pathlib.Path(sys.argv.pop(1)).resolve()
# Source is compiled, never imported from supplier, so legacy top-level IO is
# only executed with finite fake public-download responses and scratch files.
TEXT=(SOURCE/'acquire_tools.py').read_text()
def digest(b):return hashlib.sha256(b).hexdigest()
def archive(rows):
    f=io.BytesIO()
    with tarfile.open(fileobj=f,mode='w:gz') as t:
        for path,kind,content in rows:
            m=tarfile.TarInfo(path);m.type=kind;m.size=len(content) if kind==tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):m.linkname='elsewhere'
            t.addfile(m,io.BytesIO(content) if m.isfile() else None)
    return f.getvalue()
def select(blob,member='root/osv-scanner'):
    desc={'size':len(blob),'digest':'sha256:'+digest(blob)}
    if 'def verified_members(' in TEXT:
        m=runpy.run_path(str(SOURCE/'acquire_tools.py'))
        return m['verified_members'](blob,desc,{member:('osv-scanner',digest(b'good'),16)})
    # Run the authentic predecessor whole helper. Only the remote acquisition
    # and its manifest descriptors are finite synthetic collaborators.
    with tempfile.TemporaryDirectory() as d:
        root=pathlib.Path(d); downloads={};token=b'{"token":"public-fixture"}'
        for file,count,indices in [('osv-scanner-action.manifest.json',11,[8,9,10]),('scorecard-action.manifest.json',16,[14,15])]:
            layers=[{} for _ in range(count)]
            for i in indices:
                data=blob if file.startswith('osv-') and i==8 else archive([('irrelevant',tarfile.REGTYPE,b'unused')])
                row={'size':len(data),'digest':'sha256:'+digest(data)};layers[i]=row
                downloads[row['digest']]=data
            (root/file).write_text(json.dumps({'repo':file,'manifest':{'layers':layers}}))
        def open_(req,timeout=None):
            url=req.full_url if isinstance(req,urllib.request.Request) else req
            return io.BytesIO(token if '/token?' in url else downloads[url.rsplit('/',1)[1]])
        with patch.object(urllib.request,'urlopen',open_),contextlib.redirect_stdout(io.StringIO()):
            exec(compile(TEXT,str(SOURCE/'acquire_tools.py'),'exec'),{'__file__':str(root/'acquire_tools.py'),'__name__':'__main__'})
        p=root/'tools/osv-scanner'
        return {'osv-scanner':p.read_bytes()} if p.exists() else {}
class ExactArchiveAdmission(unittest.TestCase):
    def test_exact_unique_regular_positive(self):
        self.assertEqual(select(archive([('root',tarfile.DIRTYPE,b''),('root/osv-scanner',tarfile.REGTYPE,b'good')]))['osv-scanner'],b'good')
    def test_wrong_path_same_basename_rejected(self):
        with self.assertRaises(ValueError):select(archive([('elsewhere/osv-scanner',tarfile.REGTYPE,b'good')]))
    def test_duplicate_basename_rejected(self):
        with self.assertRaises(ValueError):select(archive([('root/osv-scanner',tarfile.REGTYPE,b'good'),('other/osv-scanner',tarfile.REGTYPE,b'good')]))
    def test_duplicate_exact_path_rejected(self):
        with self.assertRaises(ValueError):select(archive([('root/osv-scanner',tarfile.REGTYPE,b'good'),('root/osv-scanner',tarfile.REGTYPE,b'good')]))
    def test_selected_symlink_rejected(self):
        with self.assertRaises(ValueError):select(archive([('root/osv-scanner',tarfile.SYMTYPE,b'')]))
    def test_parent_symlink_trap_rejected(self):
        with self.assertRaises(ValueError):select(archive([('root',tarfile.SYMTYPE,b''),('root/osv-scanner',tarfile.REGTYPE,b'good')]))
    def test_parent_hardlink_trap_rejected(self):
        with self.assertRaises(ValueError):select(archive([('root',tarfile.LNKTYPE,b''),('root/osv-scanner',tarfile.REGTYPE,b'good')]))
    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):select(archive([('../osv-scanner',tarfile.REGTYPE,b'good')]))
    def test_dot_alias_rejected(self):
        with self.assertRaises(ValueError):select(archive([('./root/osv-scanner',tarfile.REGTYPE,b'good')]))
    def test_absolute_rejected(self):
        with self.assertRaises(ValueError):select(archive([('/root/osv-scanner',tarfile.REGTYPE,b'good')]))
    def test_content_digest_checked(self):
        with self.assertRaises(ValueError):select(archive([('root/osv-scanner',tarfile.REGTYPE,b'evil')]))
    def test_missing_member_rejected(self):
        with self.assertRaises(ValueError):select(archive([('other',tarfile.REGTYPE,b'good')]))
if __name__=='__main__':unittest.main(verbosity=2)
