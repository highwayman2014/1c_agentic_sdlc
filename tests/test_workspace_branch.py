from pathlib import Path
import subprocess,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from workspace_branch import plan,apply_switch,git


class BranchTests(unittest.TestCase):
    def fixture(self,root):
        root.mkdir();git(root,'init','-b','main');git(root,'config','user.name','Fixture');git(root,'config','user.email','fixture@example.invalid')
        (root/'src/cf').mkdir(parents=True);(root/'src/cf/base.bsl').write_text('baseline')
        (root/'bsl-analyzer.toml').write_text('[source]\nroot="src/cf"\nextensions=[]\n[search.baseline]\nbackend="sqlite"\n')
        git(root,'add','.');git(root,'commit','-m','fixture main');git(root,'switch','-c','task/existing')
        (root/'src/cf/added.bsl').write_text('added');git(root,'add','.');git(root,'commit','-m','fixture added file');git(root,'switch','main')

    def test_plan_readonly_and_stop_precedes_bulk_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'repo';self.fixture(root);p=plan(root,'task/existing')
            self.assertTrue(p['requires_rebind']);self.assertEqual(git(root,'branch','--show-current'),'main')
            state={'stopped':False};events=[]
            def inspect(root,stop=False):
                if stop:state['stopped']=True;events.append('stop');return [{'pid':1,'mode':'daemon','owned':True}]
                return [] if state['stopped'] else [{'pid':1,'mode':'daemon','owned':True}]
            def switch(root,branch):
                self.assertTrue(state['stopped']);events.append('switch');git(root,'switch','--no-overwrite-ignore',branch)
            result=apply_switch(p,True,inspect,switch)
            self.assertEqual(events,['stop','switch']);self.assertEqual(result['status'],'switched');self.assertTrue((root/'src/cf/added.bsl').exists())

    def test_explicit_stop_ack_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'repo';self.fixture(root);p=plan(root,'task/existing')
            with self.assertRaisesRegex(ValueError,'restart-backend'):
                apply_switch(p,False,lambda root,stop=False:[{'pid':1,'mode':'daemon','owned':True}])
            self.assertEqual(git(root,'branch','--show-current'),'main')

    def test_foreign_or_unmanaged_backend_blocks_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'repo';self.fixture(root);p=plan(root,'task/existing')
            with self.assertRaisesRegex(ValueError,'foreign'):
                apply_switch(p,True,lambda root,stop=False:[{'pid':1,'mode':'daemon','owned':False}])
            self.assertEqual(git(root,'branch','--show-current'),'main')

    def test_dirty_tree_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'repo';self.fixture(root);(root/'src/cf/base.bsl').write_text('unfinished')
            with self.assertRaisesRegex(ValueError,'Uncommitted'):plan(root,'task/existing')
            self.assertEqual((root/'src/cf/base.bsl').read_text(),'unfinished')

    def test_busy_branch_and_linked_manifest_are_not_reassigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'repo';self.fixture(root);linked=base/'linked'
            git(root,'worktree','add',str(linked),'task/existing')
            with self.assertRaisesRegex(ValueError,'checked out elsewhere'):plan(root,'task/existing')
            with self.assertRaisesRegex(ValueError,'Primary checkout'):plan(linked,'main')

    def test_ignored_local_profile_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'repo';self.fixture(root);git(root,'switch','task/existing')
            (root/'AGENTS.md').write_text('versioned target instructions');git(root,'add','AGENTS.md');git(root,'commit','-m','fixture target profile');git(root,'switch','main')
            (root/'.git/info/exclude').write_text('/AGENTS.md\n');(root/'AGENTS.md').write_text('private local instructions')
            p=plan(root,'task/existing')
            with self.assertRaisesRegex(ValueError,'switch'):apply_switch(p,False,lambda root,stop=False:[])
            self.assertEqual((root/'AGENTS.md').read_text(),'private local instructions');self.assertEqual(git(root,'branch','--show-current'),'main')

    def test_changed_branch_with_same_sha_requires_new_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'repo';self.fixture(root);p=plan(root,'task/existing');git(root,'switch','-c','task/same-sha')
            with self.assertRaisesRegex(ValueError,'HEAD/branch changed'):apply_switch(p,False,lambda root,stop=False:[])

    def test_identical_source_branch_does_not_stop_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'repo';self.fixture(root);git(root,'branch','task/same','main');p=plan(root,'task/same');self.assertFalse(p['requires_rebind'])
            def forbidden(*args,**kwargs):raise AssertionError('No source/baseline changes: no backend operation')
            self.assertEqual(apply_switch(p,False,forbidden)['status'],'switched')


if __name__=='__main__':unittest.main()
