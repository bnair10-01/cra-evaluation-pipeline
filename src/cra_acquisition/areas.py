"""Assessment-area identity. Two names are the same area only when their place words match and their states do not
contradict each other. A name that fits several areas stays unlinked and is flagged; nothing is matched by substring."""
import re
from collections import namedtuple

STATE_CODES={'al','ak','az','ar','ca','co','ct','de','dc','fl','ga','hi','id','il','in','ia','ks','ky','la','me','mi','mn','ms','mo','mt',
             'ne','nv','nh','nj','nm','ny','nc','nd','oh','ok','or','pa','ri','sc','sd','tn','tx','ut','vt','va','wa','wv','wi','wy','pr'}
# 'ma' and 'md' are left out on purpose: in these documents they mean "metropolitan area" and "metropolitan division".
GENERIC={'aa','assessment','area','areas','msa','ma','md','metropolitan','statistical','division','county','counties','parish','multistate',
         'the','of','and','full','limited','scope','review','combined'}
MARKERS={'MSA','MA','AA','MD','COUNTIES','COUNTY','NON-MSA','MULTISTATE','METROPOLITAN'}
Parts=namedtuple('Parts','base states lead')   # lead: the first city of a hyphenated official name ('Albany' for Albany-Schenectady-Troy)

def area_parts(name):
    """(place words as a sorted string, set of state codes). 'Wichita KS MSA 48620' -> ('wichita', {'ks'})."""
    text=re.sub(r'\([^)]*\)',' ',str(name or ''))
    text=re.sub(r'\s+[-–—]\s+','-',text).replace('–','-')   # 'Naples – Marco Island' is one hyphenated name
    toks=re.findall(r"[A-Za-z0-9'&.]+(?:[-/][A-Za-z0-9'&.]+)*",text)
    shout=text==text.upper()                       # an all-capitals name: be stricter about what counts as a state
    states=set();words=[];lead=None
    for i,t in enumerate(toks):
        parts=re.split(r'[-/]',t)
        is_state=i>0 and all(len(p)==2 and p.isupper() and p.lower() in STATE_CODES for p in parts)
        if is_state and shout:
            nxt=toks[i+1].upper() if i+1<len(toks) else ''
            is_state=(i==len(toks)-1) or nxt in MARKERS or nxt.isdigit()
        if is_state:states.update(p.lower() for p in parts);continue
        if lead is None and len(parts)>1 and not {p.lower() for p in parts}<=(GENERIC|{'non'}):
            lead=' '.join(sorted({w for w in words+[parts[0].lower().strip(".'")] if w and w not in GENERIC and not w.isdigit()}))   # place words up to the first hyphenated name
        words+=[p.lower().strip(".'") for p in parts]
    keep={w for w in words if w and w not in GENERIC and not w.isdigit()}
    return Parts(' '.join(sorted(keep)),frozenset(states),lead or '')

def same_name(a,b):
    """Same place words, or one is the other's lead city ('Albany' / 'Albany-Schenectady-Troy')."""
    return bool(a.base) and (a.base==b.base or a.base==b.lead or b.base==a.lead or bool(a.lead and a.lead==b.lead))

def same_area(a,b):
    return same_name(a,b) and (not a.states or not b.states or bool(a.states&b.states))

def make_entry(area_id,names):
    parts=[area_parts(n) for n in names if n]
    return dict(id=area_id,label=next((n for n in names if n),''),parts=parts,states=frozenset().union(*[p.states for p in parts]) if parts else frozenset())

def index_from_mapping(mapping):
    """Compatibility helper: {name: id} -> index."""
    by={}
    for name,i in mapping.items():by.setdefault(i,[]).append(name)
    return [make_entry(i,names) for i,names in by.items()]

def resolve_area(name,index):
    """(area id or None, reason). Resolves only when exactly one area fits."""
    p=area_parts(name)
    if not p.base:return None,'no usable name'
    cands=[e for e in index if any(same_name(p,q) for q in e['parts'])]
    if not cands:return None,'no such area in this evaluation'
    ok=[e for e in cands if not p.states or not e['states'] or p.states&e['states']]
    if not ok:return None,'the same place name exists only in a different state'
    if len(ok)==1:return ok[0]['id'],None
    if p.states:
        exact=[e for e in ok if e['states']==p.states]
        if len(exact)==1:return exact[0]['id'],None
    return None,'ambiguous: '+'; '.join(e['label'] for e in ok)

def merge_areas(rows,flags,table='table_c_assessment_areas'):
    """Rows that are one area under different spellings become one row. State-bearing names merge when their states
    overlap; a name without a state joins only when exactly one state-bearing area shares its place words.
    Differing values for one field keep the earliest page's value and are flagged."""
    groups=[]
    def ps_of(r):return [area_parts(n) for n in (r.get('name'),(r['fields'].get('aa_name') or {}).get('value')) if n]
    def info(r):
        names=[r.get('name'),(r['fields'].get('aa_name') or {}).get('value')]
        ps=ps_of(r);base=next((p.base for p in ps if p.base),'');st=frozenset().union(*[p.states for p in ps]) if ps else frozenset()
        return names,base,st
    infos=[info(r) for r in rows]
    for r,(names,base,st) in zip(rows,infos):
        if not st:continue
        g=next((g for g in groups if base and g['states']&st and any(same_name(p,q) for p in ps_of(r) for q in g['parts'])),None)
        if g:g['rows'].append(r);g['states']|=st;g['names']+=[n for n in names if n];g['parts']+=ps_of(r)
        else:groups.append(dict(base=base,states=set(st),rows=[r],names=[n for n in names if n],parts=list(ps_of(r))))
    for r,(names,base,st) in zip(rows,infos):
        if st:continue
        stateful=[g for g in groups if base and g['states'] and any(same_name(p,q) for p in ps_of(r) for q in g['parts'])]
        if len(stateful)==1:g=stateful[0]
        elif len(stateful)>1:
            flags.append(dict(kind='ambiguous_area_alias',table=table,record=r['ids']['aa_id'],name=r.get('name'),detail='this name fits several areas ('+'; '.join(sorted({x['rows'][0].get('name') or '' for x in stateful}))+'); kept separate'))
            groups.append(dict(base=base,states=set(),rows=[r],names=[n for n in names if n],parts=list(ps_of(r))));continue
        else:g=next((g for g in groups if base and not g['states'] and any(same_name(p,q) for p in ps_of(r) for q in g['parts'])),None)
        if g:g['rows'].append(r);g['names']+=[n for n in names if n];g['parts']+=ps_of(r)
        else:groups.append(dict(base=base,states=set(),rows=[r],names=[n for n in names if n],parts=list(ps_of(r))))
    out=[]
    for g in groups:
        rs=g['rows'];first=lambda r:min([f['page'] for f in r['fields'].values()] or [10**6])
        primary=max(rs,key=lambda r:(len(r['fields']),-first(r)));merged=dict(primary,fields=dict(primary['fields']),aliases=sorted(set(g['names'])))
        for r in sorted(rs,key=first):
            if r is primary:continue
            for f,item in r['fields'].items():
                if f not in merged['fields']:merged['fields'][f]=item
                elif f!='aa_name' and str(merged['fields'][f]['value']).strip().casefold()!=str(item['value']).strip().casefold():
                    flags.append(dict(kind='conflict',table=table,record=primary['ids']['aa_id'],field=f,kept=str(merged['fields'][f]['value'])[:80],other=str(item['value'])[:80],page=item['page'],detail='same area written two ways; earliest value kept'))
        cand=[r['fields']['aa_name'] for r in rs if 'aa_name' in r['fields']]
        if cand:merged['fields']['aa_name']=max(cand,key=lambda it:(bool(area_parts(it['value']).states),len(str(it['value']))))   # the most specific spelling
        merged['entry']=make_entry(primary['ids']['aa_id'],[str((merged['fields'].get('aa_name') or {}).get('value') or primary.get('name') or '')]+g['names'])
        out.append(merged)
    return sorted(out,key=lambda r:(first(r),r['ids']['aa_id']))
