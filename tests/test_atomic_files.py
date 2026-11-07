from pathlib import Path
import os,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from atomic_files import atomic_text


class AtomicFilesTests(unittest.TestCase):
    def test_complete_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'progress.json';atomic_text(p,'{"phase":"one"}');atomic_text(p,'{"phase":"two"}')
            self.assertEqual(p.read_text(),'{"phase":"two"}')
            self.assertEqual(list(Path(tmp).glob('*.tmp')),[])

    def test_failed_replace_retains_previous_valid_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'progress.json';atomic_text(p,'{"phase":"one"}')
            with patch('atomic_files.os.replace',side_effect=OSError('fixture failure')):
                with self.assertRaises(OSError):atomic_text(p,'{"phase":"two"}')
            self.assertEqual(p.read_text(),'{"phase":"one"}')
            self.assertEqual(list(Path(tmp).glob('*.tmp')),[])

    @unittest.skipUnless(os.name=='nt','Windows sharing retry')
    def test_transient_reader_lock_retries_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'progress.json';atomic_text(p,'old');real_replace=os.replace;calls=[]
            def replace(source,target):
                calls.append(1)
                if len(calls)==1:
                    error=PermissionError('fixture sharing violation');error.winerror=5;raise error
                return real_replace(source,target)
            with patch('atomic_files.os.replace',side_effect=replace):atomic_text(p,'new')
            self.assertEqual(p.read_text(),'new');self.assertEqual(len(calls),2)
            self.assertEqual(list(Path(tmp).glob('*.tmp')),[])

    @unittest.skipUnless(os.name=='nt','Windows sharing retry')
    def test_persistent_reader_lock_is_bounded_and_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'progress.json';atomic_text(p,'old')
            error=PermissionError('fixture sharing violation');error.winerror=5
            with patch('atomic_files.os.replace',side_effect=error) as replace:
                with self.assertRaises(PermissionError):atomic_text(p,'new')
            self.assertEqual(replace.call_count,5);self.assertEqual(p.read_text(),'old')
            self.assertEqual(list(Path(tmp).glob('*.tmp')),[])


if __name__=='__main__':unittest.main()
