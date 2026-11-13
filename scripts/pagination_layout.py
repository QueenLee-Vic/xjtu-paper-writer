"""Explicit native keep/header operations; no content reconstruction or reordering."""
from lxml import etree as E
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';Q=lambda s:'{'+W+'}'+s
NS={'w':W};KEY='pagination.explicit_plan'

def apply(root,plan,ensure,change):
    if not isinstance(plan,dict) or set(plan)-{'paragraph_groups','tables'}:raise ValueError('Invalid pagination plan')
    ps=list(root.iter(Q('p')));tables=list(root.iter(Q('tbl')));actions=[]
    for group in plan.get('paragraph_groups',[]):
        if not isinstance(group,list) or not 2<=len(group)<=8 or any(type(i)is not int or i<0 or i>=len(ps) for i in group) or len(group)!=len(set(group)):raise ValueError('Invalid keep group')
        nodes=[ps[i] for i in group]
        if any(p.getparent().tag!=Q('body') for p in nodes):raise ValueError('Keep groups require body paragraphs')
        positions=[list(p.getparent()).index(p) for p in nodes]
        if positions!=list(range(positions[0],positions[0]+len(group))):raise ValueError('Keep groups must be consecutive in object order')
        for p in nodes:
            if any(E.QName(e).localname in ['fldChar','fldSimple','ins','del','object','sectPr','txbxContent','anchor'] for e in p.iter()):raise ValueError('Unsafe keep group object')
        for index,p in enumerate(nodes):
            pr=ensure(p,'pPr');change(pr,'keepLines',{'val':'1'},KEY,['pStyle','keepNext','keepLines','pageBreakBefore','spacing','ind','jc','sectPr'])
            # Do not erase an existing last-paragraph keepNext preference.
            if index<len(nodes)-1:change(pr,'keepNext',{'val':'1'},KEY,['pStyle','keepNext','keepLines','pageBreakBefore','spacing','ind','jc','sectPr'])
        actions.append({'kind':'keep_group','paragraph_indices':group,'last_keep_next_preserved':True})
    for spec in plan.get('tables',[]):
        if set(spec)-{'index','repeat_header_rows','keep_together'}:raise ValueError('Unknown table pagination option')
        if type(spec.get('keep_together',False)) is not bool:raise ValueError('keep_together must be boolean')
        i=spec['index']
        if type(i)is not int or i<0 or i>=len(tables):raise ValueError('Invalid table index')
        table=tables[i];rows=table.findall(Q('tr'));headers=spec.get('repeat_header_rows',0)
        if type(headers)is not int or not 0<=headers<len(rows):raise ValueError('Header count must be explicit and less than row count')
        if len(list(table.iter(Q('tbl'))))>1 or any(E.QName(e).localname in ['oMath','object','anchor','vMerge','ins','del'] for e in table.iter()):raise ValueError('Complex table requires manual pagination')
        if spec.get('keep_together') and len(rows)>5:raise ValueError('Only short tables may be kept together')
        for ri,row in enumerate(rows):
            pr=row.find(Q('trPr'))
            if pr is None:pr=E.Element(Q('trPr'));row.insert(0,pr)
            if ri<headers:change(pr,'tblHeader',{'val':'1'},KEY)
            change(pr,'cantSplit',{'val':'1'},KEY)
        if spec.get('keep_together'):
            cells_ps=list(table.iter(Q('p')))
            for j,p in enumerate(cells_ps):
                pr=ensure(p,'pPr');change(pr,'keepLines',{'val':'1'},KEY,['pStyle','keepNext','keepLines','pageBreakBefore','spacing','ind','jc','sectPr'])
                if j<len(cells_ps)-1:change(pr,'keepNext',{'val':'1'},KEY,['pStyle','keepNext','keepLines','pageBreakBefore','spacing','ind','jc','sectPr'])
        actions.append({'kind':'table_pagination','index':i,'repeat_header_rows':headers,'keep_together':bool(spec.get('keep_together'))})
    return actions
