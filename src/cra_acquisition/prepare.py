"""Deterministic page preparation: one parser path, every page accounted for.

Page classes
  text              native text, no dominant image
  ocr_layer         dominant page image with an embedded (hidden OCR) text layer: image review required
  image_no_text     dominant image, no usable text: needs OCR or vision
  sparse            a few characters only: needs review
  blank             rendered page is confirmed (near-)white with no text or images
  no_text_content   no text, but the render is not blank: needs OCR or vision
  unreadable        the parser failed; the error is recorded, never swallowed
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .io import fingerprint, read_json, sha256_file, write_json
from .paths import ROOT

PREPARE_VERSION='prepare-1'
COMMON=set('the of and to in a for is was that with as by on at are be this from or an it its not were has have bank loans loan area areas lending test small business income low moderate middle upper institution assessment evaluation community performance rating credit table total percent'.split())

def parser_info():
    from importlib.metadata import version
    info=dict(prepare=PREPARE_VERSION,pdfplumber=version('pdfplumber'),pdfminer=version('pdfminer.six'),pypdfium2=version('pypdfium2'))
    info['fingerprint']=fingerprint(info)
    return info

def tesseract():
    exe=os.environ.get('CRA_TESSERACT') or shutil.which('tesseract')
    return exe if exe and Path(exe).exists() or (exe and shutil.which(exe)) else None


def text_quality(text):
    tokens=re.findall(r"[A-Za-z]+",text)
    flags=[]
    n=len(text)
    bad=text.count('�')+len(re.findall(r'\(cid:\d+\)',text))
    if n and bad/n>0.01:flags.append('garbled_glyphs')
    if len(tokens)>=60:
        hit=sum(t.lower() in COMMON for t in tokens)/len(tokens)
        if hit<0.08:flags.append('low_word_quality')
    if re.search(r'\S{60,}',text):flags.append('very_long_unspaced_run')
    return flags

def blank_check(pdf_page):
    """Render small and test for near-white; True means confirmed blank."""
    bitmap=pdf_page.render(scale=0.25,grayscale=True)
    image=bitmap.to_pil().convert('L')
    low,high=image.getextrema()
    hist=image.histogram()
    dark=sum(hist[:200])
    return dark<=max(3,image.size[0]*image.size[1]*0.0005)

def classify(chars,alnum,big_image,render_blank,has_images):
    if big_image and alnum>=20:return 'ocr_layer'
    if big_image:return 'image_no_text'
    if alnum>=20:return 'text'
    if alnum>0:return 'sparse'
    if not has_images and render_blank:return 'blank'
    return 'no_text_content'

def printed_label_guess(lines):
    """Footer/header page label as printed; kept separate from the physical page number."""
    for line in list(lines[-3:])+list(lines[:2]):
        m=re.fullmatch(r'(?:page\s+)?([ivxlc]{1,6}|[A-Z]?-?\d{1,3})',line.strip(),re.I)
        if m:return m.group(1)
    return None

def prepare_pdf(path,expected_hash=None):
    import pdfplumber
    import pypdfium2
    path=Path(path)
    digest=sha256_file(path)
    if expected_hash and digest!=expected_hash:raise ValueError('PDF checksum mismatch')
    pages=[]
    errors=0
    pdfium=pypdfium2.PdfDocument(str(path))
    try:
      with pdfplumber.open(path) as doc:
          if not doc.pages:raise ValueError('PDF contains no pages')
          for number,page in enumerate(doc.pages,1):
              record=dict(page=number,width=float(page.width),height=float(page.height),rotation=int(page.rotation or 0))
              try:
                  label=pdfium.get_page_label(number-1) or None
              except Exception:
                  label=None
              try:
                  text=page.extract_text(layout=False) or ''
                  words=[[round(w['x0'],1),round(w['top'],1),round(w['x1'],1),round(w['bottom'],1),w['text']] for w in page.extract_words()]
                  try:tables=page.extract_tables()
                  except Exception as e:
                      tables=[];record['table_error']=f'{type(e).__name__}: {e}'
                  images=page.images
                  area=float(page.width*page.height) or 1.0
                  coverage=sum(abs(i['x1']-i['x0'])*abs(i['bottom']-i['top']) for i in images)/area
                  big=any(abs(i['x1']-i['x0'])*abs(i['bottom']-i['top'])>=0.65*area for i in images)
                  alnum=sum(ch.isalnum() for ch in text)
                  blank=False
                  if alnum==0 and not images:
                      blank=blank_check(pdfium[number-1])
                  lines=[l for l in text.split('\n') if l.strip()]
                  record.update(text=text,words=words,tables=tables,lines=lines,image_count=len(images),
                                image_coverage=round(min(coverage,1.0),3),char_count=len(text),alnum_count=alnum,
                                page_class=classify(len(text),alnum,big,blank,bool(images)),
                                quality_flags=text_quality(text),printed_label_pdf=label,
                                printed_label_guess=printed_label_guess(lines))
              except Exception as e:  # recorded, never silently dropped
                  errors+=1
                  record.update(text='',words=[],tables=[],lines=[],image_count=0,image_coverage=0.0,char_count=0,
                                alnum_count=0,page_class='unreadable',quality_flags=['parser_error'],
                                printed_label_pdf=label,printed_label_guess=None,error=f'{type(e).__name__}: {e}')
              record['needs_review']=record['page_class'] in ('ocr_layer','image_no_text','sparse','no_text_content','unreadable') or bool(record['quality_flags'])
              pages.append(record)
    finally:
      pdfium.close()
    return dict(sha256=digest,parser=parser_info(),page_count=len(pages),unreadable_pages=errors,pages=pages)

def bundle_path(root,pe_id):
    return Path(root)/'data/derived/pages'/f'{pe_id}.json'

def load_or_prepare(root,record,force=False):
    """Prepared bundle keyed by PDF hash and parser fingerprint; rebuilt if either differs."""
    root=Path(root);out=bundle_path(root,record['pe_id'])
    if out.is_file() and not force:
        try:
            cached=read_json(out)
            if cached.get('sha256')==record['sha256'] and cached.get('parser',{}).get('fingerprint')==parser_info()['fingerprint']:
                return cached
        except (OSError,ValueError):pass
    bundle=prepare_pdf(root/record['path'],record['sha256'])
    bundle['pe_id']=record['pe_id']
    write_json(out,bundle)
    return bundle

def ocr_page(pdf_path,page_number,languages='eng',timeout=180):
    """Optional OCR of one page through a local Tesseract executable. Raises if unavailable."""
    exe=tesseract()
    if not exe:raise RuntimeError('Tesseract executable not found (set CRA_TESSERACT)')
    import pypdfium2
    pdf=pypdfium2.PdfDocument(str(pdf_path))
    try:
        image=pdf[page_number-1].render(scale=300/72).to_pil()
    finally:
        pdf.close()
    with tempfile.TemporaryDirectory() as d:
        png=Path(d)/'page.png';image.save(png)
        result=subprocess.run([exe,str(png),'stdout','-l',languages],capture_output=True,text=True,timeout=timeout)
    if result.returncode:raise RuntimeError(f'Tesseract failed with status {result.returncode}')
    return result.stdout

def render_page_png(pdf_path,page_number,max_edge=2576):
    """PNG bytes of one page for review packets or the vision path (long edge bounded)."""
    import io as _io
    import pypdfium2
    pdf=pypdfium2.PdfDocument(str(pdf_path))
    try:
        page=pdf[page_number-1];w,h=page.get_size()
        scale=min(2.0,max_edge/max(w,h))
        image=page.render(scale=scale).to_pil().convert('RGB')
    finally:
        pdf.close()
    buf=_io.BytesIO();image.save(buf,format='PNG',optimize=True);return buf.getvalue(),image.size

def inventory(root,manifest,force=False,progress=None):
    docs=[]
    for record in manifest['documents']:
        if progress:progress(record['pe_id'])
        bundle=load_or_prepare(root,record,force)
        counts={}
        for p in bundle['pages']:counts[p['page_class']]=counts.get(p['page_class'],0)+1
        docs.append(dict(pe_id=record['pe_id'],agency=record['agency'],exam_type=record['exam_type'],
                         scan_status=record['scan_status'],pages=bundle['page_count'],
                         manifest_pages=record.get('pages'),classes=counts,
                         review_pages=[p['page'] for p in bundle['pages'] if p['needs_review']],
                         flagged=[dict(page=p['page'],flags=p['quality_flags']) for p in bundle['pages'] if p['quality_flags']]))
    total=sum(d['pages'] for d in docs)
    return dict(run_id=manifest['run_id'],documents=docs,total_pages=total,
                mismatched_page_counts=[d['pe_id'] for d in docs if d['manifest_pages'] is not None and d['manifest_pages']!=d['pages']],
                parser=parser_info(),tesseract=bool(tesseract()))

def main():
    p=argparse.ArgumentParser(description='Prepare page bundles for the final manifest')
    p.add_argument('--final',type=Path,required=True);p.add_argument('--output',type=Path)
    p.add_argument('--pe-id',action='append');p.add_argument('--force',action='store_true')
    a=p.parse_args()
    manifest=read_json(a.final)
    if a.pe_id:manifest=dict(manifest,documents=[r for r in manifest['documents'] if r['pe_id'] in a.pe_id])
    result=inventory(ROOT,manifest,a.force,lambda i:print('preparing',i,flush=True))
    if a.output:write_json(a.output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='documents'},indent=1))
if __name__=='__main__':main()
