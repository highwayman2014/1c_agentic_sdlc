"""Prepare an isolated SQLite seed without starting MCP or an embedder.

This makes a PRIVATE COPY, not an external shared baseline. Existing destinations
are never replaced. Requires the validated 0.4.3 layout helper and model identity.
"""
import argparse
from contextlib import closing
import csv
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tomllib
from atomic_files import atomic_text


def private_directory(path):
    """Create only new directories with the analyzer's protected owner-only DACL."""
    if path.exists(): raise ValueError('Refusing to provision an existing destination directory')
    missing=[];parent=path
    while not parent.exists(): missing.append(parent);parent=parent.parent
    if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()):
        raise ValueError('Cache ancestor must not be a reparse point')
    for target in reversed(missing):
        if os.name!='nt': target.mkdir(mode=0o700);continue
        from ctypes import wintypes
        sid=list(csv.reader(io.StringIO(subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True))))[0][-1]
        descriptor=ctypes.c_void_p()
        advapi=ctypes.WinDLL('advapi32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        convert=advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
        if not convert(f'O:{sid}D:P(A;OICI;FA;;;{sid})',1,ctypes.byref(descriptor),None):raise ctypes.WinError(ctypes.get_last_error())
        class SA(ctypes.Structure):
            _fields_=[('nLength',wintypes.DWORD),('lpSecurityDescriptor',ctypes.c_void_p),('bInheritHandle',wintypes.BOOL)]
        security=SA(ctypes.sizeof(SA),descriptor,False)
        create=kernel.CreateDirectoryW;create.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(SA)]
        try:
            if not create(str(target),ctypes.byref(security)):raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree(descriptor)


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(8*1024*1024),b''):h.update(part)
    return h.hexdigest()


def seed(source, destination, model, dimension):
    if not source.is_file():raise ValueError('Seed SQLite does not exist')
    side=Path(str(source)+'.usearch.json')
    identity=json.loads(side.read_text())
    if identity.get('model_id')!=model or identity.get('dim')!=dimension or identity.get('embed_text_version')!=1:
        raise ValueError('Seed model/dimension/embed text profile mismatch')
    private_directory(destination)
    manifest={'strategy':'private-sqlite-seed','shared_baseline':False,'source':str(source),'destination':str(destination),'model':model,'dimension':dimension,'status':'preparing'}
    atomic_text(destination/'seed-manifest.json',json.dumps(manifest,indent=2))
    db=destination/'bsl-search.db'
    # A committed backup includes the active source WAL, unlike copying the .db file.
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(db)) as out:
        src.backup(out)
        check=out.execute('pragma quick_check').fetchall()
        if check!=[('ok',)]:raise ValueError('Copied SQLite failed quick_check')
        version=out.execute('pragma user_version').fetchone()[0]
        generation=out.execute("select value from meta where key='embedding_generation'").fetchone()[0]
        token_claim=out.execute("select value from meta where key='token_layout_claim_v1'").fetchone()
        if token_claim and token_claim[0]:
            raise ValueError('Token-layout seed requires a verified profile-aware adapter; copied destination retained')
        chunks,vectors,bad=out.execute('select count(*),count(embedding),sum(case when embedding is not null and length(embedding) != ? then 1 else 0 end) from chunks',(dimension*4,)).fetchone()
    if version!=1 or bad or int(generation)!=identity['generation'] or vectors!=identity['count']:
        raise ValueError('Seed SQLite and sidecar coverage/generation mismatch; preserved incomplete destination')
    copied=[]
    ann=Path(str(source)+'.usearch')
    if ann.exists():
        before=(ann.stat().st_size,ann.stat().st_mtime_ns)
        for file in (ann,side):
            target=destination/('bsl-search.db'+str(file)[len(str(source)):]);shutil.copy2(file,target);copied.append(target)
        if before!=(ann.stat().st_size,ann.stat().st_mtime_ns) or json.loads(side.read_text())!=identity:
            raise ValueError('Source ANN changed during copy; no MCP started')
    manifest.update(status='ready',chunks=chunks,vectors=vectors,generation=int(generation),quick_check='ok',
                    files={x.name:{'size':x.stat().st_size,'sha256':sha256(x)} for x in [db,*copied]})
    atomic_text(destination/'seed-manifest.json',json.dumps(manifest,indent=2))
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--cache-base',type=Path,required=True);p.add_argument('--layout-helper',type=Path,required=True)
    p.add_argument('--analyzer',type=Path,required=True);p.add_argument('--apply',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args();root=a.workspace.resolve()
    cfg=tomllib.loads((root/'bsl-analyzer.toml').read_text(encoding='utf-8-sig'))
    baseline=cfg.get('search',{}).get('baseline',{})
    if baseline.get('backend','sqlite')!='sqlite':raise ValueError('Private SQLite seed requires explicit local SQLite profile')
    if subprocess.check_output([str(a.analyzer),'--version'],text=True).strip()!='bsl-analyzer 0.4.3':raise ValueError('Cache layout helper is pinned to validated 0.4.3')
    expected=a.cache_base.resolve()/'workspaces/v1'
    destination=Path(subprocess.check_output([str(a.layout_helper),str(root),str(a.cache_base.resolve())],text=True).strip()).resolve()
    if destination.parent!=expected or len(destination.name)!=64:raise ValueError('Unexpected cache helper output')
    if destination.exists():raise ValueError('Destination exists; inspect/reuse it instead of reseeding')
    embedding=baseline['embedding']
    if any(embedding.get(key) for key in ('query_prefix','document_prefix','max_input_tokens','tokenizer_file','tokenizer_sha256')):
        raise ValueError('Pinned seed helper supports only the validated legacy embedding profile without prefix/token overrides')
    report={'workspace':str(root),'source':str(a.source.resolve()),'destination':str(destination),'strategy':'private-sqlite-seed','shared_baseline':False,'apply':a.apply}
    if a.apply:report['seed']=seed(a.source.resolve(),destination,embedding['model'],embedding['dimension'])
    if a.output:atomic_text(a.output,json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='seed'},ensure_ascii=False))


if __name__=='__main__':main()
