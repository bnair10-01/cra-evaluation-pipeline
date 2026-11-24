"""Project-relative paths. Override the project root with CRA_ROOT."""
import os
from pathlib import Path

def root():
    value=os.environ.get('CRA_ROOT')
    return Path(value).resolve() if value else Path(__file__).resolve().parents[2]

ROOT=root()

_DEFAULT_PROJECT={'manifest':'reports/final_904bed5b30cc793e19d4.json','split':'docs/extraction_handoff/holdout_split.json','expected_documents':44,'scan_quota':4}

def project_config(root=None):
    """Names and sizes that used to be typed into the code (manifest path, split file, expected document count, scan quota)."""
    import json
    f=Path(root or ROOT)/'config/project.json'
    return {**_DEFAULT_PROJECT,**(json.loads(f.read_text(encoding='utf-8')) if f.is_file() else {})}
