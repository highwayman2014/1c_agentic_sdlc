import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from seed_workspace_index import seed


class SeedTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'source.db';c=sqlite3.connect(source)
        c.executescript("create table meta(key text,value text); insert into meta values('embedding_generation','7'); create table chunks(embedding blob); pragma user_version=1;")
        c.execute('insert into chunks values(?)',(b'\0'*8,));c.commit();c.close()
        Path(str(source)+'.usearch.json').write_text(json.dumps({'model_id':'fixture-model','dim':2,'embed_text_version':1,'generation':7,'count':1}))
        return source

    def test_consistent_private_copy_and_existing_destination_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.fixture(root);dest=root/'cache/workspaces/v1/new'
            report=seed(source,dest,'fixture-model',2)
            self.assertEqual(report['vectors'],1);self.assertEqual(report['quick_check'],'ok')
            self.assertFalse(report['shared_baseline'])
            with self.assertRaisesRegex(ValueError,'existing destination'):seed(source,dest,'fixture-model',2)
            c=sqlite3.connect(source);self.assertEqual(c.execute('select count(*) from chunks').fetchone()[0],1);c.close()

    def test_incompatible_model_fails_before_creating_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.fixture(root);dest=root/'cache'
            with self.assertRaisesRegex(ValueError,'profile mismatch'):seed(source,dest,'other-model',2)
            self.assertFalse(dest.exists())

    def test_token_layout_requires_explicit_compatible_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.fixture(root);dest=root/'cache'
            c=sqlite3.connect(source);c.execute("insert into meta values('token_layout_claim_v1','nonlegacy-profile')");c.commit();c.close()
            with self.assertRaisesRegex(ValueError,'Token-layout seed'):seed(source,dest,'fixture-model',2)
            self.assertEqual(json.loads((dest/'seed-manifest.json').read_text())['status'],'preparing')

    def test_wrong_generation_preserves_incomplete_copy_without_claiming_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.fixture(root);dest=root/'cache'
            c=sqlite3.connect(source);c.execute("update meta set value='8'");c.commit();c.close()
            with self.assertRaisesRegex(ValueError,'generation mismatch'):seed(source,dest,'fixture-model',2)
            self.assertEqual(json.loads((dest/'seed-manifest.json').read_text())['status'],'preparing')


if __name__=='__main__':unittest.main()
