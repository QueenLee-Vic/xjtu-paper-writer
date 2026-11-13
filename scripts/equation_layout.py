"""Narrow editable OMML layout: geometry-derived native paragraph tabs, not character conversion."""
from copy import deepcopy
import re
from lxml import etree as E
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';M='http://schemas.openxmlformats.org/officeDocument/2006/math'
Q=lambda n:'{'+W+'}'+n
NS={'w':W,'m':M}

def inventory(root):
    rows=[]
    for i,p in enumerate(root.iter(Q('p'))):
        maths=p.findall('.//m:oMath',NS)
        if not maths:continue
        content=''.join(p.xpath('./w:r/w:t/text()',namespaces=NS)).strip()
        number=re.fullmatch(r'[（(]\d+[)）]',content)
        math_text=''.join(maths[0].xpath('.//m:t/text()',namespaces=NS))
        complex_math=any(E.QName(n).localname not in ['oMath','r','rPr','t','sty','nor','ctrlPr'] for n in maths[0].iter())
        table=any(a.tag==Q('tbl') for a in p.iterancestors())
        display=bool(p.findall('m:oMathPara',NS))
        safe=(p.getparent().tag==Q('body') and len(maths)==1 and number is not None and not display and not table and not complex_math and len(math_text)<=50
              and all(n.tag in [Q('pPr'),Q('r'),'{'+M+'}oMath'] for n in p)
              and all(n.tag in [Q('rPr'),Q('t'),Q('tab')] for r in p.findall(Q('r')) for n in r))
        number_runs=[r for r in p.findall(Q('r')) if ''.join(r.xpath('./w:t/text()',namespaces=NS)).strip()]
        if len(number_runs)!=1:safe=False
        elif maths[0].getparent() is not p or p.index(maths[0])>=p.index(number_runs[0]):safe=False
        tab_runs=[r for r in p.findall(Q('r')) if r.find(Q('tab')) is not None]
        if tab_runs and (len(tab_runs)!=2 or any(r.find(Q('t')) is not None for r in tab_runs)):safe=False
        rows.append({'paragraph_index':i,'kind':'table_formula' if table else 'display_omml' if display else 'numbered_single' if number else 'inline_or_unnumbered',
                     'math_text_length':len(math_text),'structural_types':sorted({E.QName(e).localname for e in maths[0].iter()}),'width_status':'unmeasured_requires_render','math_objects':len(maths),'multiline_or_complex':complex_math,'existing_tabs':len(tab_runs),'eligible':bool(safe),'reason':'eligible_simple_literal_number' if safe else 'unsupported_structure_or_inline_long_complex'})
    return rows

def apply(root,indices,config,ensure,change):
    if not isinstance(indices,list) or any(type(i) is not int or i<0 for i in indices) or len(indices)!=len(set(indices)):raise ValueError('Equation indices must be unique nonnegative integers')
    observations=inventory(root);lookup={r['paragraph_index']:r for r in observations}
    paragraphs=list(root.iter(Q('p')))
    # Restrict this first implementation to one explicit A4 LTR section, no columns.
    secs=list(root.iter(Q('sectPr')))
    if len(secs)!=1:raise ValueError('Formula layout requires a single section')
    sec=secs[0];size=sec.find(Q('pgSz'));margins=sec.find(Q('pgMar'));cols=sec.find(Q('cols'))
    if size is None or margins is None:raise ValueError('Explicit page geometry required')
    if cols is not None and cols.get(Q('num'),'1')!='1':raise ValueError('Column geometry unsupported')
    if sec.find(Q('bidi')) is not None or int(margins.get(Q('gutter'),'0')):raise ValueError('RTL/gutter unsupported')
    width=int(size.get(Q('w')))-int(margins.get(Q('left')))-int(margins.get(Q('right')))
    if abs(int(size.get(Q('w')))-11906)>2 or abs(int(size.get(Q('h')))-16838)>2:raise ValueError('Only portrait A4 geometry validated')
    planned=[]
    def prop(key):
        r=config['effective_properties'][key]
        if key not in config['allowed_properties'] or r.get('confirmation_required') or r.get('status') not in ['default','explicit','verified','inherited','extracted']:raise ValueError('Unresolved formula property '+key)
        return r['value']
    if prop('equation.body_alignment')!='center' or prop('equation.number_alignment')!='right' or prop('equation.center_reference')!='text_area':raise ValueError('Unsupported requested formula goal')
    for index in indices:
        if index not in lookup or not lookup[index]['eligible']:raise ValueError('Requested formula is not safely eligible: '+str(index))
        p=paragraphs[index];pr=ensure(p,'pPr')
        for unsupported in ['bidi','numPr','framePr','textDirection','sectPr']:
            if pr.find(Q(unsupported)) is not None:raise ValueError('Unsupported formula paragraph property')
        ind=pr.find(Q('ind'))
        if ind is not None and any(float(ind.get(Q(k),'0'))!=0 for k in ['left','right','start','end','leftChars','rightChars']):raise ValueError('Indented equation region unsupported')
        # Property values still originate from the existing resolved configuration.
        change(pr,'jc',{'val':'both'},'equation.paragraph.alignment')
        change(pr,'spacing',{'line':'240','lineRule':'auto','before':'0','after':'0'},'equation.paragraph.line_spacing',remove=['beforeLines','afterLines','beforeAutospacing','afterAutospacing'])
        if prop('equation.paragraph.alignment')!='justify' or prop('equation.paragraph.line_spacing')!={'rule':'multiple','value':1,'unit':'multiple'} or prop('equation.paragraph.space_before_pt')!=0 or prop('equation.paragraph.space_after_pt')!=0:raise ValueError('Formula paragraph variant not validated')
        chars=prop('equation.paragraph.first_line_chars')
        change(pr,'ind',{'firstLineChars':round(chars*100)},'equation.paragraph.first_line_chars',remove=['firstLine','hanging','hangingChars'])
        old=pr.find(Q('tabs'))
        if old is not None:pr.remove(old)
        tabs=ensure(pr,'tabs')
        for alignment,pos in [('center',round(width/2)),('right',width)]:
            tab=E.SubElement(tabs,Q('tab'));tab.set(Q('val'),alignment);tab.set(Q('pos'),str(pos));tab.set(Q('leader'),'none')
        for run in list(p.findall(Q('r'))):
            if run.find(Q('tab')) is not None:p.remove(run)
        math=p.find('m:oMath',NS);number=next(r for r in p.findall(Q('r')) if ''.join(r.xpath('./w:t/text()',namespaces=NS)).strip())
        for before in [math,number]:
            run=E.Element(Q('r'));E.SubElement(run,Q('tab'));p.insert(p.index(before),run)
        planned.append({'paragraph_index':index,'method':'physical_text_area_tabs','center_twips':round(width/2),'right_twips':width,
                        'reference_character_tabs':deepcopy(config['effective_properties']['equation.tab_stops']['value']),
                        'character_conversion_performed':False,'geometry_status':'requires_render_check'})
    return observations,planned
