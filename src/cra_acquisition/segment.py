"""Section segmentation and bounded task windows. Every page lands in a segment; nothing is dropped."""
import re

HEADINGS=[  # (kind, regex) tested against each line; the first heading on a page sets its kind
 ('summary',r"^(overall )?(institution'?s? )?(cra )?rating\b|^institution'?s? cra rating|^summary of (the )?institution|^overall cra rating|^cra rating$"),
 ('institution',r"^(description of|institution'?s?) (description|institution)|^description of institution|^institution description|^general information|^description of the bank"),
 ('scope',r"^scope of (the )?(evaluation|examination)|^scope$|^evaluation period|^scope and methodology"),
 ('aa',r"^description of (the )?(institution'?s? )?(operations|assessment area)|assessment area$|^description of .*(assessment area|aa)\b|^(full|limited)[- ]scope"),
 ('ltd',r"^loan[- ]to[- ]deposit"),
 ('conclusions',r"^(conclusions? with respect|conclusions? about|lending test|investment test|service test|community development test|geographic distribution|borrower (profile|distribution)|response to complaints|lending (inside|in) (the )?assessment|fair lending|discrimination|lending activity)"),
 ('appendix',r"^appendix\b|^glossary|^appendices"),
]
COMPILED=[(k,re.compile(r,re.I)) for k,r in HEADINGS]
TABLE_LABEL=re.compile(r"^\s*(table|chart)\s+[A-Za-z0-9\-]{1,4}\b[\s.:\-–—]",re.I)
NUMBER=re.compile(r"\d")

def page_kind(page,previous):
    if page['page']==1:return 'cover'
    for line in page['lines'][:25]:
        text=line.strip().rstrip(':')
        if len(text)>110:continue
        for kind,rx in COMPILED:
            if rx.search(text):return kind
    return previous or 'other'

def table_pages(bundle):
    """Pages that look like they hold table rows: pdfplumber tables, a table label, or numeric-dense lines."""
    out=[]
    for p in bundle['pages']:
        dense=sum(1 for l in p['lines'] if len(re.findall(r"\d[\d,.]*%?",l))>=3)
        if p['tables'] or any(TABLE_LABEL.match(l) for l in p['lines']) or dense>=4:out.append(p['page'])
    return out

def segments(bundle):
    kinds=[];previous=None
    for p in bundle['pages']:
        k=page_kind(p,previous);kinds.append(k);previous=k if k!='cover' else None
    result=[];start=0
    for i in range(1,len(kinds)+1):
        if i==len(kinds) or kinds[i]!=kinds[start]:
            result.append(dict(kind=kinds[start],first=start+1,last=i))
            start=i
    return result

def covered(segs,count):
    seen=set()
    for s in segs:seen.update(range(s['first'],s['last']+1))
    return seen==set(range(1,count+1))

def page_text(page,numbered=True):
    """Page text with stable line ids (pN.lM) so evidence and table ranges can be addressed."""
    if not numbered:return page['text']
    return '\n'.join(f"[p{page['page']}.l{n}] {line}" for n,line in enumerate(page['lines'],1))

def render_pages(bundle,pages,numbered=True):
    index={p['page']:p for p in bundle['pages']}
    return '\n\n'.join(f"=== PDF PAGE {n} ===\n"+page_text(index[n],numbered) for n in pages)

def windows(bundle,pages,max_chars=60000,overlap=1):
    """Split an ordered page list into windows no larger than max_chars, with page overlap.
    A single page larger than the limit still gets its own window (never truncated)."""
    index={p['page']:p for p in bundle['pages']}
    pages=sorted(set(pages));out=[];current=[];size=0
    for n in pages:
        c=index[n]['char_count']+20*len(index[n]['lines'])
        if current and size+c>max_chars:
            out.append(current)
            carry=current[-overlap:] if overlap else []
            current=[x for x in carry if x!=n];size=sum(index[x]['char_count'] for x in current)
        current.append(n);size+=c
    if current:out.append(current)
    return out

def pages_of_kinds(segs,kinds,limit=None):
    pages=[]
    for s in segs:
        if s['kind'] in kinds:pages+=list(range(s['first'],s['last']+1))
    return pages[:limit] if limit else pages

WIDE=8
def wide_tables(page):
    """(table_index, rows) for tables wide enough to be area-by-category distribution tables."""
    out=[]
    for ti,tab in enumerate(page.get('tables') or [],1):
        if tab and max(len(r) for r in tab)>=WIDE and len(tab)>=3:out.append((ti,tab))
    return out

def clean_cell(c):
    return ' '.join((c or '').split())

def render_tables(bundle,pages):
    """Cell-by-cell view of wide tables with stable row ids [pN.tK.rM]; row/column alignment survives here
    where plain text scatters labels and headers."""
    index={p['page']:p for p in bundle['pages']};out=[]
    for n in sorted(set(pages)):
        for ti,tab in wide_tables(index[n]):
            out.append(f"=== PAGE {n} TABLE {ti} (cell extraction) ===")
            for ri,row in enumerate(tab,1):
                cells=[clean_cell(c) for c in row]
                if any(cells):out.append(f"[p{n}.t{ti}.r{ri}] "+' | '.join(cells))
    return '\n'.join(out)
