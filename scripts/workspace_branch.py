"""Plan/switch an existing branch in a primary checkout without exposing BSL to bulk checkout.
Default is read-only. --apply --restart-backend explicitly disconnects all clients of the
selected owned workspace before source changes. Never rewrites indexes, branch tips, commits,
stashes, remotes, infobases, or backends of another folder/user.
"""
import argparse,json,subprocess,sys,tomllib
from pathlib import Path
from atomic_files import atomic_text
HERE=Path(__file__).resolve().parent


def git(root,*args):
    p=subprocess.run(['git','-C',str(root),*args],capture_output=True)
    if p.returncode:raise ValueError('Git operation failed: '+args[0])
    return p.stdout.decode('utf-8').strip()


def clean(root):
    if git(root,'status','--porcelain'):raise ValueError('Uncommitted/untracked changes; no switch, reset or stash')
    for name in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply'):
        if Path(git(root,'rev-parse','--path-format=absolute','--git-path',name)).exists():raise ValueError('Unfinished Git operation: '+name)


def backend_processes(root,stop=False):
    command=['powershell.exe','-NoProfile','-NonInteractive','-File',str(HERE/'workspace_backend.ps1'),'-Source',str(root)]
    if stop:command.append('-Stop')
    p=subprocess.run(command,capture_output=True,text=True)
    if p.returncode:raise ValueError('Cannot verify/stop owned BSL backend; no Git switch performed')
    rows=json.loads(p.stdout or '[]');return rows if isinstance(rows,list) else [rows]


def plan(root,branch):
    root=Path(root).resolve();clean(root)
    common=Path(git(root,'rev-parse','--path-format=absolute','--git-common-dir')).resolve()
    if common.parent!=root or not (root/'.git').is_dir():raise ValueError('Primary checkout required; preserve linked-worktree task manifests')
    if not branch or branch.startswith('-'):raise ValueError('Invalid target branch')
    git(root,'check-ref-format','--branch',branch)
    current=git(root,'branch','--show-current')
    if not current:raise ValueError('Detached HEAD is not an ordinary task branch')
    target=git(root,'rev-parse','--verify','refs/heads/'+branch+'^{commit}')
    if branch!=current and 'branch refs/heads/'+branch in git(root,'worktree','list','--porcelain').splitlines():raise ValueError('Target branch is checked out elsewhere')
    head=git(root,'rev-parse','HEAD');cfg=tomllib.loads((root/'bsl-analyzer.toml').read_text(encoding='utf-8-sig'))
    layout=cfg.get('source',{});paths=[layout.get('root','src/cf')]
    paths += [x['path'] if isinstance(x,dict) else x for x in layout.get('extensions',[])]
    for path in paths:
        if Path(path).is_absolute() or '..' in Path(path).parts:raise ValueError('Branch helper requires repository-relative source roots')
    changes=git(root,'diff','--no-renames','--name-status',head,target,'--',*paths)
    baseline=cfg.get('search',{}).get('baseline',{})
    dynamic_shared=(baseline.get('backend')=='postgres' and not baseline.get('workspace_code',{}).get('snapshot_id'))
    rebind=branch!=current and (bool(changes) or dynamic_shared)
    return {'workspace':str(root),'from_branch':current,'from_sha':head,'branch':branch,'target_sha':target,
            'source_changes':changes.splitlines(),'requires_rebind':rebind,'indexes_preserved':True,
            'next':'Reconnect client and run workspace_health; status alone is not source coverage proof'}


def apply_switch(report,restart=False,inspect=backend_processes,switch=None):
    root=Path(report['workspace']);clean(root)
    if git(root,'rev-parse','HEAD')!=report['from_sha'] or git(root,'branch','--show-current')!=report['from_branch']:raise ValueError('HEAD/branch changed after plan')
    if git(root,'rev-parse','refs/heads/'+report['branch'])!=report['target_sha']:raise ValueError('Target changed after plan')
    if report['branch']==report['from_branch']:return {**report,'status':'unchanged'}
    stopped=[]
    if report['requires_rebind']:
        running=inspect(root)
        if any(not p.get('owned') or p.get('mode')!='daemon' for p in running):raise ValueError('Unmanaged/foreign source backend: coordinate or use worktree')
        if running and not restart:raise ValueError('Explicit --restart-backend required to disconnect this workspace before bulk switch')
        if running:
            stopped=inspect(root,stop=True)
            if inspect(root):raise ValueError('Backend still present; branch not switched')
    report['stopped_backends']=stopped
    # Protect local ignored profiles from accidental overwrite by a target branch.
    if switch:switch(root,report['branch'])
    else:git(root,'switch','--no-overwrite-ignore',report['branch'])
    clean(root)
    return {**report,'status':'switched','stopped_backends':stopped,'actual_sha':git(root,'rev-parse','HEAD')}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--branch',required=True);p.add_argument('--apply',action='store_true');p.add_argument('--restart-backend',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args();report={}
    try:
        report=plan(a.workspace,a.branch)
        if a.apply:report=apply_switch(report,a.restart_backend)
        print(json.dumps(report,ensure_ascii=False,indent=2));return 0
    except Exception as e:report.update(status='blocked',error=str(e));print(str(e),file=sys.stderr);return 1
    finally:
        if a.output:atomic_text(a.output,json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':sys.exit(main())
