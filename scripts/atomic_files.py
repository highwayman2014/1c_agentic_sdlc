"""Durable best-effort replacement for owned progress/manifest files.
Does not claim protection against hardware faults or replace SQLite backup API.
"""
import os
import time
from pathlib import Path
import uuid


def atomic_text(path, text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary,path)
                break
            except PermissionError as error:
                if os.name!='nt' or getattr(error,'winerror',None) not in (5,32,33) or attempt==4:
                    raise
                time.sleep((0.02,0.05,0.1,0.2)[attempt])
    finally:
        try:temporary.unlink()
        except FileNotFoundError:pass
    if os.name!='nt' and hasattr(os,'O_DIRECTORY'):
        descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
