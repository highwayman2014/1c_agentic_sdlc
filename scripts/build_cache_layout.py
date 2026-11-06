"""Build the pinned 0.4.3 read-only cache-layout helper from matching SDK artifacts.
No MCP, database, provider or Cargo build is started. Review before using for another version.
"""
import argparse
from pathlib import Path
import subprocess


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analyzer-source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();release=a.analyzer_source/'target/release'
    if a.output.exists():raise SystemExit('Refusing to overwrite an installed helper')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    source=Path(__file__).with_name('bsl_cache_layout.rs')
    cmd=['rustc','--edition=2021',str(source),'-O','-C','lto=fat','-C','embed-bitcode=yes','-o',str(a.output),'-L',f'dependency={release/"deps"}']
    for name in ('project_model','blake3'):
        candidates=list((release/'deps').glob(f'lib{name}-*.rlib'))
        if not candidates:raise SystemExit('Matching release library missing: '+name)
        library=max(candidates,key=lambda x:x.stat().st_mtime)
        cmd+=['--extern',f'{name}={library}']
    for lib in list((release/'build').glob('*/out'))+list((Path.home()/'.cargo/registry/src').glob('*/windows_x86_64_msvc-*/lib')):
        if any(lib.glob('*.lib')):cmd+=['-L',f'native={lib}']
    subprocess.run(cmd,check=True)
    print('Built pinned layout helper:',a.output)


if __name__=='__main__':main()
