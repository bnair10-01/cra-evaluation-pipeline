"""Portable, atomic file helpers shared by every stage (UTF-8, no fixed temp names)."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()

def sha256_file(path,chunk=1<<20):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(chunk),b''):h.update(block)
    return h.hexdigest()

def canonical(value):
    """Deterministic JSON text used for hashing and cache fingerprints."""
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

def fingerprint(value):
    return sha256_bytes(canonical(value).encode('utf-8'))

def _no_dupes(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise ValueError(f'Duplicate JSON key: {k}')
        out[k]=v
    return out

def _no_constants(name):
    raise ValueError(f'Non-finite JSON number: {name}')

def loads(text):
    return json.loads(text,object_pairs_hook=_no_dupes,parse_constant=_no_constants)

def read_json(path):
    return loads(Path(path).read_text(encoding='utf-8'))

def atomic_write_bytes(path,data,exclusive=False,mode=None):
    """Write via a unique temp file in the same directory, fsync, then replace.
    exclusive=True refuses to overwrite an existing file."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if exclusive and path.exists():raise FileExistsError(str(path))
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name+'.',suffix='.part')
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        if mode is not None:os.chmod(name,mode)
        if exclusive:
            try:os.link(name,path)
            except OSError:
                if path.exists():raise FileExistsError(str(path))
                os.replace(name,path);name=None
            else:os.unlink(name);name=None
        else:
            os.replace(name,path);name=None
    finally:
        if name and os.path.exists(name):os.unlink(name)

def atomic_write_text(path,text,exclusive=False):
    atomic_write_bytes(path,text.encode('utf-8'),exclusive)

def write_json(path,value,exclusive=False):
    atomic_write_text(path,json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',exclusive)


def versioned_path(path):
    """path itself if free, else name-YYYYmmddTHHMMSS.ext. Outputs are never overwritten and never refused."""
    import datetime as dt
    path=Path(path)
    if not path.exists():return path
    return path.with_name(f"{path.stem}-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S%f}{path.suffix}")

def write_json_new(path,value):
    target=versioned_path(path);write_json(target,value,exclusive=True);return target


def now():
    """UTC timestamp, ISO 8601."""
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()

def collapse(value):
    """Whitespace collapsed to single spaces."""
    return ' '.join(value.split())

def wilson(k,n,z=1.96):
    """95% Wilson interval for k of n, or None when n is 0."""
    import math
    if n==0:return None
    p=k/n;d=1+z*z/n;c=p+z*z/(2*n);m=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))
    return [round(max(0,(c-m)/d),4),round(min(1,(c+m)/d),4)]
