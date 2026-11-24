"""Deterministic reading of numeric table rows. The model identifies a table; code reads the cells.

Rules: values keep their printed form; parentheses and a leading minus are negative; '-', '--',
'N/A', 'NA', 'n/a' are 'not reported' (None) and never zero; a row whose number count does not match
the declared columns is reported as unread, not guessed."""
from decimal import Decimal, InvalidOperation
import re

TOKEN=re.compile(r"\(?-?\$?\d[\d,]*(?:\.\d+)?%?\)?|(?<![\w])(?:N/?A|n/?a|--?|—|–)(?![\w])")
NOT_REPORTED={'-','--','—','–','na','n/a'}
CATEGORIES=[  # (canonical, regex on the cleaned lower-case row label)
 ('low',r"^low( income)?\b|^low$"),
 ('moderate',r"^moderate( income)?\b"),
 ('middle',r"^middle( income)?\b"),
 ('upper',r"^upper( income)?\b"),
 ('not available',r"^(not available|unknown|n/?a\b|income not available|tracts? .*not available|unknown income)|revenues? (are )?not available|unknown revenues?"),
 ('at or below $1 million',r"(<=|\u2264|<|at or below|less than or equal to|under|up to)\s*\$?1(,000,000| million| mm)?(?!,)\b|\$?1(,000,000| million| mm)\s*or\s*less"),
 ('above $1 million',r"(>|above|over|more than|greater than)\s*\$?1(,000,000| million| mm)?(?!,)\b|\$1,000,001"),
]
CATEGORY_RX=[(c,re.compile(r,re.I)) for c,r in CATEGORIES]

def parse_token(token):
    """(value, as_printed) for one token; value is a Decimal, or None for not reported."""
    t=token.strip()
    if t.lower() in NOT_REPORTED:return None,t
    neg=t.startswith('(') and t.endswith(')') or t.startswith('-') or t.startswith('(-')
    core=re.sub(r"[()$,%\s-]",'',t)
    if not core:raise ValueError('empty number')
    try:value=Decimal(core)
    except InvalidOperation as e:raise ValueError(f'bad number {token!r}') from e
    return (-value if neg else value),t

def split_row(line):
    """Label text before the first number token, plus the number tokens in order."""
    matches=list(TOKEN.finditer(line))
    # a leading digit group can belong to the label (e.g. '2015 Low'); the caller supplies column counts
    return matches

def read_row(line,ncols):
    """Read exactly ncols trailing numeric tokens; the rest is the label. None if the row doesn't fit."""
    matches=list(TOKEN.finditer(line))
    if len(matches)<ncols or ncols<1:return None
    use=matches[-ncols:]
    label=line[:use[0].start()].strip(' .:\t')
    # trailing tokens must reach the end of the line (nothing but whitespace after the last one)
    if line[use[-1].end():].strip():return None
    between=line[use[0].start():use[-1].end()]
    leftovers=TOKEN.sub('',between).strip()
    if leftovers:return None  # non-numeric text between values: refuse to guess
    values=[]
    for m in use:
        try:values.append(parse_token(m.group(0)))
        except ValueError:return None
    return dict(label=label,values=values,line=line)

def category(label):
    clean=re.sub(r"\s+",' ',label).strip().lower()
    clean=re.sub(r"^[^\w\u2264\u2265<>$]+|[\W_]+$",'',clean)   # keep leading < > and the less/greater-or-equal signs
    for canonical,rx in CATEGORY_RX:
        if rx.search(clean):return canonical
    return None

def read_table(lines,first,last,column_meanings):
    """Read lines[first-1:last] (1-based, inclusive). Returns rows and rejected lines (with reasons)."""
    rows=[];rejected=[]
    ncols=len(column_meanings)
    for number in range(first,last+1):
        if not 1<=number<=len(lines):
            rejected.append(dict(line=number,reason='line out of range'));continue
        text=lines[number-1]
        row=read_row(text,ncols)
        if row is None:
            if TOKEN.search(text) and re.search(r"[A-Za-z]",text):
                rejected.append(dict(line=number,text=text,reason='numeric count does not match declared columns'))
            continue
        cat=category(row['label'])
        if cat is None and re.match(r'^\W*totals?\b',row['label'],re.I):continue   # totals are not categories; skipped quietly
        if cat is None:
            rejected.append(dict(line=number,text=text,reason='row label is not a recognized category'));continue
        rows.append(dict(line=number,text=text,category=cat,label=row['label'],cells=[
            dict(column=m,value=v,printed=p) for m,(v,p) in zip(column_meanings,row['values'])]))
    return rows,rejected

def read_cell_rows(table,first,last,columns):
    """Rows of a pdfplumber table: column 0 is the row label, the rest are numeric cells that must match `columns`.
    Returns (rows, rejected). A row whose cells are not all numbers (or '--') is rejected, never guessed."""
    rows=[];rejected=[];n=len(columns)
    for ri in range(first,last+1):
        if not 1<=ri<=len(table):rejected.append(dict(row=ri,reason='row out of range'));continue
        cells=[' '.join((c or '').split()) for c in table[ri-1]]
        label=cells[0] if cells else ''
        values=[c for c in cells[1:] if c!='']
        if re.match(r'^\W*totals?\b',label,re.I):continue
        if len(values)!=n:rejected.append(dict(row=ri,label=label,reason=f'{len(values)} numeric cells but {n} columns declared'));continue
        try:parsed=[parse_token(v) for v in values]
        except ValueError:rejected.append(dict(row=ri,label=label,reason='non-numeric cell'));continue
        rows.append(dict(row=ri,label=label,cells=[dict(column=c,value=v,printed=p) for c,(v,p) in zip(columns,parsed)],tokens=values))
    return rows,rejected


def total_row(lines,first,last,column_meanings):
    """The printed 'Total' row of a text-line table, read like any row (None when absent or not readable)."""
    ncols=len(column_meanings)
    for number in range(max(1,first),min(len(lines),last)+1):
        row=read_row(lines[number-1],ncols)
        if row and re.match(r'^\W*totals?\b',row['label'],re.I):
            return dict(line=number,text=lines[number-1],cells=[dict(column=m,value=v,printed=p) for m,(v,p) in zip(column_meanings,row['values'])])
    return None

def data_positions(table_row):
    """Physical cell indexes (after the label column) that hold a value; empty/merged cells are skipped, as read_cell_rows does."""
    return [i for i,c in enumerate(table_row) if i>0 and ' '.join((c or '').split())!='']

def column_headers(table,first_row,positions):
    """For each physical column: the header texts above the data, one per header row. Merged header cells (printed once,
    followed by empty cells) are carried to the right until the next header text."""
    rows=[]
    for r in table[:max(0,first_row-1)]:
        cells=[' '.join((c or '').split()) for c in r];cur='';out=[]
        for i,c in enumerate(cells):
            if i==0:out.append('');continue
            if c:cur=c
            out.append(cur)
        rows.append(out)
    return {p:[row[p] for row in rows if p<len(row) and row[p]] for p in positions}

_FAMILY=[('marketshare',re.compile(r'market share',re.I)),('aggregate',re.compile(r'aggregate|market loans',re.I)),('bank',re.compile(r'\bbank\b',re.I)),
         ('demographic',re.compile(r'famil|household|housing units|business|farms|population|owner',re.I))]
_DECLARED={'aggregate_pct':'aggregate','bank_count_pct':'bank','bank_count':'bank','bank_dollars':'bank','bank_dollar_pct':'bank','demographic_pct':'demographic'}

def header_category(texts):
    for x in texts:
        c=category(x)
        if c:return c
    return None

def header_family(texts):
    """Measure family from the most specific header text that names one (checked from the bottom header row upwards)."""
    for x in reversed(texts):
        if re.match(r'^\W*total\b',x,re.I) or x.strip() in ('#','$'):continue   # "Total Small Loans to Businesses" names the loans, not a population base
        for fam,rx in _FAMILY:
            if rx.search(x):return fam
    return None
