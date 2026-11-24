"""Source-only reviewer packets and reference ingestion. Packets are built from the manifest and the
PDFs only: no model output can reach them. Submissions are hash-locked with a blindness attestation."""
import csv
import datetime as dt
from pathlib import Path
import shutil

from .io import sha256_file,write_json
from .paths import ROOT
from .research import norm,number_from,NUMERIC
from . import tasks as T

IDENTITY_ALIASES={'aa_name':'aa_name','product':'product','category':'category','years':'years','dimension':'dimension','criterion':'criterion','institution_name':'institution_name'}

def form_columns(cols,inv):
    out={}
    for table,fields in cols.items():
        ident=[f for f in inv['row_identity'][table]]
        pk_refs={*[c for c in fields if c.endswith('_id')]}
        values=[f for f in fields if f not in pk_refs]
        out[table]=['pe_id',*ident,*[f for f in values if f not in ident],'source_page']
    return out

def build_packet(manifest,ids,out_dir,render_images=True,root=ROOT):
    from .prepare import render_page_png
    from .validate import inventory
    inv=inventory(root);cols=T.research_columns(root);forms=form_columns(cols,inv)
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=False)
    docs=[]
    for rec in manifest['documents']:
        if rec['pe_id'] not in ids:continue
        d=out/rec['pe_id'];d.mkdir()
        shutil.copyfile(Path(root)/rec['path'],d/'source.pdf')
        if sha256_file(d/'source.pdf')!=rec['sha256']:raise ValueError('Copied PDF differs from the manifest')
        pages=rec.get('pages') or 0
        if render_images:
            (d/'pages').mkdir()
            for n in range(1,pages+1):
                png,_=render_page_png(d/'source.pdf',n);(d/'pages'/f'{n:04d}.png').write_bytes(png)
        docs.append(dict(pe_id=rec['pe_id'],agency=rec['agency'],pages=pages,sha256=rec['sha256']))
    (out/'forms').mkdir()
    for table,header in forms.items():
        with (out/'forms'/f'{table}.csv').open('w',newline='',encoding='utf-8') as f:csv.writer(f).writerow(header)
    (out/'INSTRUCTIONS.md').write_text(INSTRUCTIONS,encoding='utf-8')
    manifest_out=dict(created_at=dt.datetime.now(dt.timezone.utc).isoformat(),documents=docs,forms=forms,
                      contains_model_output=False,field_inventory_hash=sha256_file(Path(root)/'config/field_inventory.json'))
    write_json(out/'packet_manifest.json',manifest_out);return manifest_out

INSTRUCTIONS="""# Blind reference coding instructions

You are the independent reference reviewer. This packet holds only the source PDFs, page images and blank forms.
Do NOT look at any model or pipeline output for these documents until you have submitted.

1. Code every evaluation from the PDF alone. One CSV row per record (one row per product, assessment area,
   distribution cell row, conclusion, peer). Fill the identity columns the same way for every row of that kind.
2. Copy values exactly as printed. Leave a cell empty when the evaluation does not print it (that is NULL).
   Zero is `0`. Never calculate. Percentages as printed (for example `93.3%`). Booleans as 1 or 0.
3. `source_page` is the physical PDF page (not the printed label).
4. Table E: one row per examiner judgment; `label_verbatim` is the exact evaluative phrase.
5. When finished run `cra review submit-reference` with your name and the start/end times; it hash-locks your files.
   Record honestly whether you saw any model output (`--attest-blind` only if you did not).
"""

def read_forms(form_dir,inv,cols):
    """Wide CSV forms -> long rows [{pe_id, table, context, field, value, critical}]."""
    rows=[];critical=inv['critical_fields']
    for table,fields in cols.items():
        path=Path(form_dir)/f'{table}.csv'
        if not path.is_file():continue
        with path.open(newline='',encoding='utf-8') as f:
            for n,rec in enumerate(csv.DictReader(f),2):
                if not any((v or '').strip() for v in rec.values()):continue
                page_raw=(rec.get('source_page') or '').strip()
                page=int(page_raw) if page_raw.isdigit() else None
                ident=[norm(rec.get(i) or '') for i in inv['row_identity'][table]]
                context='|'.join(ident) or 'row'
                for field in fields:
                    raw=(rec.get(field) or '').strip()
                    if field in {'pe_id','source_page'} or raw=='' or field.endswith('_id'):continue
                    rows.append(dict(pe_id=rec['pe_id'].strip(),table=table,context=context,field=field,
                                     value=normalize_value(cols[table][field],raw),critical=field in critical.get(table,[]),line=n,row_id=f"{rec['pe_id'].strip()}:{table}:{n}",page=page))
    return rows

def normalize_value(sql_type,raw):
    if sql_type in NUMERIC:
        try:
            v=number_from(raw)
            return int(v) if sql_type=='INTEGER' and v==v.to_integral_value() else float(v)
        except ValueError:return raw
    return raw

def submit_reference(form_dir,out_dir,reviewer,started,finished,blind,expected_ids,root=ROOT,coverage=None):
    from .validate import inventory
    if not blind:raise ValueError('Submission requires the blindness attestation; do not submit if model output was seen')
    inv=inventory(root);cols=T.research_columns(root);rows=read_forms(form_dir,inv,cols)
    if not rows:raise ValueError('The forms folder contains no coded rows; fill the forms before submitting (nothing was written)')
    present={r['pe_id'] for r in rows}
    missing=sorted(set(expected_ids)-present)
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')
    path=out/f'reference_{stamp}.json'
    if coverage is not None:
        known=set(T.research_columns(root))
        for pe,tables in coverage.items():
            if pe not in set(expected_ids) or not set(tables)<=known:raise ValueError(f'Bad coverage entry for {pe}')
    payload=dict(reviewer=reviewer,started=started,finished=finished,attested_blind=True,rows=rows,coverage=coverage,
                 documents_with_rows=sorted(present),documents_missing=missing,field_inventory_hash=sha256_file(Path(root)/'config/field_inventory.json'))
    write_json(path,payload,exclusive=True)
    write_json(out/f'reference_{stamp}.lock.json',dict(file=path.name,sha256=sha256_file(path),locked_at=stamp))
    return dict(path=str(path),sha256=sha256_file(path),missing=missing,rows=len(rows))
