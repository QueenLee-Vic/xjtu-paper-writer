#!/usr/bin/env python3
"""Conservative direct-format OOXML writer; publishes only after structural fidelity checks."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import sys
import tempfile
from urllib.parse import unquote
from zipfile import ZipFile
from lxml import etree as E
from resolve_style_config import load_json, normalize

ROOT=data_root()
OUTPUT_ROOT=output_root('format')
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M='http://schemas.openxmlformats.org/officeDocument/2006/math'
NS={'w':W,'m':M}
Q=lambda name:'{'+W+'}'+name
P_ORDER=['pStyle','keepNext','keepLines','pageBreakBefore','framePr','widowControl','numPr','suppressLineNumbers','pBdr','shd','tabs','suppressAutoHyphens','kinsoku','wordWrap','overflowPunct','topLinePunct','autoSpaceDE','autoSpaceDN','bidi','adjustRightInd','snapToGrid','spacing','ind','contextualSpacing','mirrorIndents','suppressOverlap','jc','textDirection','textAlignment','textboxTightWrap','outlineLvl','divId','cnfStyle','rPr','sectPr','pPrChange']
R_ORDER=['rStyle','rFonts','b','bCs','i','iCs','caps','smallCaps','strike','dstrike','outline','shadow','emboss','imprint','noProof','snapToGrid','vanish','webHidden','color','spacing','w','kern','position','sz','szCs','highlight','u','effect','bdr','shd','fitText','vertAlign','rtl','cs','em','lang','eastAsianLayout','specVanish','oMath','rPrChange']
T_ORDER=['tblStyle','tblpPr','tblOverlap','bidiVisual','tblStyleRowBandSize','tblStyleColBandSize','tblW','jc','tblCellSpacing','tblInd','tblBorders','shd','tblLayout','tblCellMar','tblLook','tblCaption','tblDescription','tblPrChange']
C_ORDER=['cnfStyle','tcW','gridSpan','hMerge','vMerge','tcBorders','shd','noWrap','tcMar','textDirection','tcFitText','vAlign','hideMark','headers','cellIns','cellDel','cellMerge','tcPrChange']
COMPLEX={'oMath','oMathPara','object','pict','fldSimple','fldChar','instrText','ins','del','moveFrom','moveTo','txbxContent','commentRangeStart','commentRangeEnd','commentReference','footnoteReference','endnoteReference','AlternateContent','sdt','customXml'}
RUN_SUFFIX={'font.eastAsia','font.latin','size_pt','color','bold','italic'}
PAR_SUFFIX={'alignment','first_line_chars','hanging_chars','hanging_pt','line_spacing','space_before_pt','space_after_pt'}
# Projection ignores only implemented formatting nodes at their defined locations.
REMOVE={'pPr':{'jc','ind','spacing'},'rPr':{'rFonts','sz','color','b','i'},'tblPr':{'tblBorders'},'tcPr':{'tcBorders'}}

def parse(data):
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('DTD/entities unsupported')
    return E.fromstring(data,E.XMLParser(resolve_entities=False,no_network=True,remove_blank_text=False))

def digest(data):return hashlib.sha256(data).hexdigest()
def canonical(node):return E.tostring(node,method='c14n')
def local(node):return E.QName(node).localname if isinstance(node.tag,str) else ''

def read_package(path):
    with ZipFile(path,'r') as z:
        infos=z.infolist()
        if len({i.filename for i in infos})!=len(infos) or sum(i.file_size for i in infos)>100_000_000:raise ValueError('Duplicate ZIP entries or package too large')
        if z.testzip():raise ValueError('ZIP CRC failure')
        parts={i.filename:z.read(i) for i in infos}
    for required in ['[Content_Types].xml','_rels/.rels','word/document.xml','word/styles.xml']:
        if required not in parts:raise ValueError('Missing OOXML part '+required)
    types=parse(parts['[Content_Types].xml'])
    defaults={e.get('Extension') for e in types if local(e)=='Default'}
    overrides={e.get('PartName','').lstrip('/') for e in types if local(e)=='Override'}
    for name,data in parts.items():
        if name.endswith('/'):continue
        if name!='[Content_Types].xml' and name not in overrides and name.rsplit('.',1)[-1] not in defaults:raise ValueError('Missing content type: '+name)
        if name.endswith(('.xml','.rels')):
            xml=parse(data)
            if name.endswith('.rels'):
                folder=posixpath.dirname(name).replace('/_rels','') if name!='_rels/.rels' else ''
                for rel in xml:
                    if rel.get('TargetMode')=='External':continue
                    target=unquote(rel.get('Target','').split('#')[0])
                    resolved=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(folder,target))
                    if resolved not in parts:raise ValueError('Broken relationship: '+name)
    if any(n.startswith('_xmlsignatures/') for n in parts):raise ValueError('Signed packages cannot be modified safely')
    if parse(parts['word/document.xml']).tag!=Q('document'):raise ValueError('Unsupported document namespace')
    return parts,infos

def snapshot(parts,equation_targets=(),pagination_plan=None):
    d=parse(parts['word/document.xml']);copy=deepcopy(d)
    pagination_plan=pagination_plan or {}
    pagination_ps={i for group in pagination_plan.get('paragraph_groups',[]) for i in group}
    for spec in pagination_plan.get('tables',[]):
        table=list(copy.iter(Q('tbl')))[spec['index']]
        for node in table.findall('./w:tr/w:trPr',NS):
            for child in list(node):
                if child.tag in [Q('tblHeader'),Q('cantSplit')]:node.remove(child)
        if spec.get('keep_together'):
            pagination_ps.update(i for i,p in enumerate(copy.iter(Q('p'))) if table in p.iterancestors())
    def remove_keep(p):
        pr=p.find(Q('pPr'))
        if pr is not None:
            for c in list(pr):
                if c.tag in [Q('keepNext'),Q('keepLines')]:pr.remove(c)
            if not pr.attrib and not len(pr):p.remove(pr)
        return p
    for i,p in enumerate(copy.iter(Q('p'))):
        if i in pagination_ps:remove_keep(p)
        if i in equation_targets:
            pr=p.find(Q('pPr'))
            if pr is not None:
                for tabs in list(pr.findall(Q('tabs'))):pr.remove(tabs)
            for r in list(p.findall(Q('r'))):
                if r.find(Q('tab')) is not None and r.find(Q('t')) is None:p.remove(r)
    for parent in list(copy.iter()):
        if not isinstance(parent.tag,str):continue
        tag=local(parent)
        if tag in REMOVE and parent.tag==Q(tag):
            for child in list(parent):
                if child.tag in {Q(k) for k in REMOVE[tag]}:parent.remove(child)
        if tag=='sectPr' and parent.tag==Q(tag):
            for child in parent:
                allowed={'pgSz':['w','h','orient'],'pgMar':['top','bottom','left','right','header','footer']}.get(local(child),[])
                for k in allowed:child.attrib.pop(Q(k),None)
            for child in list(parent):
                if local(child) in ['pgSz','pgMar'] and not child.attrib and not len(child):parent.remove(child)
    for node in reversed(list(copy.iter())):
        if isinstance(node.tag,str) and local(node) in ['pPr','rPr','tblPr','tcPr','trPr'] and not node.attrib and not len(node) and not (node.text or '').strip():
            node.getparent().remove(node)
    return {'content_tree':digest(canonical(copy)),
            'text_order':[e.text for e in d.iter(Q('t'))],
            'formula_objects':[digest(canonical(e)) for e in d.iter() if local(e) in ['oMath','oMathPara']],
            'other_parts':{k:digest(v) for k,v in parts.items() if k!='word/document.xml'},
            'part_names':sorted(parts),
            'protected_subtrees':[digest(canonical(remove_keep(deepcopy(e)) if i in pagination_ps else e)) for i,e in enumerate(d.iter(Q('p'))) if dangerous(e) and i not in equation_targets]}

def compare_snapshots(before,after):
    diffs=[k for k in before if before[k]!=after.get(k)]
    return {'passed':not diffs,'different_layers':diffs,'checked_layers':list(before),'visual_verification':'not_performed'}

def ensure(parent,tag,order=None):
    child=parent.find(Q(tag))
    if child is not None:return child
    child=E.Element(Q(tag))
    if order and tag in order:
        rank=order.index(tag)
        for i,e in enumerate(parent):
            if local(e) in order and order.index(local(e))>rank:parent.insert(i,child);break
        else:parent.append(child)
    elif tag in ['pPr','rPr','tblPr','tcPr','trPr']:parent.insert(0,child)
    else:parent.append(child)
    return child

def dangerous(node):return any(local(e) in COMPLEX or local(e)=='anchor' for e in node.iter())

def format_package(parts,config,scope=None,role_map=None,equation_indices=None,pagination_plan=None):
    if config.get('schema_version')!='1.0' or config.get('kind')!='effective_style':raise ValueError('Expected resolved schema 1.0 configuration')
    if config.get('writer_contract',{}).get('contract_version') not in ['1.2']:raise ValueError('Unsupported writer contract')
    effective=config['effective_properties'];permitted=set(config['allowed_properties']) & set(effective)
    if scope is not None:
        if not isinstance(scope,list) or any(k not in effective for k in scope):raise ValueError('Scope requires exact known property keys')
        permitted &= set(scope)
    # Per-operation scope does not clear or rewrite full readiness.
    pending=[p for p in config.get('pending_confirmation',[]) if p['property'] in permitted]
    if pending:raise ValueError('Unresolved confirmations in requested scope')
    blocked={k for group in config.get('pending_validation',[]) for k in group['properties']}
    values={}
    for key in permitted:
        r=effective[key]
        if key.startswith('equation.') or key in blocked:continue
        if r.get('apply') is True and r.get('authorized') is True and not r.get('confirmation_required'):
            if r.get('status') not in ['verified','explicit','inherited','extracted','theme_resolved','default'] and r.get('resolution_status')!='confirmed_by_user':raise ValueError('Untrusted executable state '+key)
            if config['apply_properties'].get(key)!=r:raise ValueError('Inconsistent executable property '+key)
            values[key]=normalize(key,r['value'])
    d=parse(parts['word/document.xml']);styles=parse(parts['word/styles.xml'])
    style_by_id={e.get(Q('styleId')):e for e in styles.findall(Q('style'))}
    edits=[];skips=[];mutations=[]
    def change(parent,tag,attributes,key,order=None,remove=()):
        old=canonical(parent);node=ensure(parent,tag,order);before_attrs=dict(node.attrib)
        for name in remove:node.attrib.pop(Q(name),None)
        for name,value in attributes.items():node.set(Q(name),str(value))
        for attr in set(before_attrs)|set(node.attrib):
            if before_attrs.get(attr)!=node.get(attr):mutations.append({'path':d.getroottree().getpath(node),'attribute':attr,'after':node.get(attr),'property':key})
        if canonical(parent)!=old:edits.append({'property':key,'location':d.getroottree().getpath(parent),'element':tag})
    def paragraph(p,prefix):
        for suffix in PAR_SUFFIX:
            key=prefix+'.'+suffix
            if key not in values:continue
            value=values[key];pr=ensure(p,'pPr')
            if suffix=='alignment':change(pr,'jc',{'val':'both' if value=='justify' else value},key,P_ORDER)
            elif suffix in ['space_before_pt','space_after_pt']:
                a='before' if suffix.startswith('space_before') else 'after'
                change(pr,'spacing',{a:round(value*20)},key,P_ORDER,[a+'Lines',a+'Autospacing'])
            elif suffix=='line_spacing':
                rule=value['rule'];change(pr,'spacing',{'line':round(value['value']*(240 if rule=='multiple' else 20)),'lineRule':{'multiple':'auto','exact':'exact','at_least':'atLeast'}[rule]},key,P_ORDER)
            else:
                attr={'first_line_chars':'firstLineChars','hanging_chars':'hangingChars','hanging_pt':'hanging'}[suffix]
                # Removing physical/character alternatives is part of this exact indent operation.
                change(pr,'ind',{attr:round(value*(20 if suffix=='hanging_pt' else 100))},key,P_ORDER,['firstLine','firstLineChars','hanging','hangingChars'])
        for run in p.findall('.//w:r',NS):
            if run.find(Q('t')) is None:continue
            for suffix in RUN_SUFFIX:
                key=prefix+'.'+suffix
                if key not in values:continue
                value=values[key];pr=ensure(run,'rPr')
                if suffix.startswith('font.'):
                    east=suffix.endswith('eastAsia');change(pr,'rFonts',{'eastAsia':value} if east else {'ascii':value,'hAnsi':value},key,R_ORDER,['eastAsiaTheme'] if east else ['asciiTheme','hAnsiTheme'])
                elif suffix=='size_pt':change(pr,'sz',{'val':round(value*2)},key,R_ORDER)
                elif suffix=='color':change(pr,'color',{'val':value},key,R_ORDER,['themeColor','themeTint','themeShade'])
                else:change(pr,'b' if suffix=='bold' else 'i',{'val':'1' if value else '0'},key,R_ORDER)
    tables=list(d.iter(Q('tbl')));unsafe_tables=set()
    for i,t in enumerate(tables):
        if dangerous(t) or any(a.tag==Q('tbl') for a in t.iterancestors()) or len(list(t.iter(Q('tbl'))))>1 or t.find('w:tblPr/w:tblpPr',NS) is not None:
            unsafe_tables.add(t);skips.append({'object':'table','index':i,'reason':'complex_table_preserved'});continue
        key='table.style'
        if key in values:
            grid=values[key]=='grid';pr=ensure(t,'tblPr')
            for edge in ['top','left','bottom','right','insideH','insideV']:
                borders=ensure(pr,'tblBorders',T_ORDER)
                change(borders,edge,{'val':'single' if grid or edge in ['top','bottom'] else 'nil','sz':'4','color':'000000'},key)
            # Cell borders override table declarations; explicitly set supported simple cells.
            rows=t.findall(Q('tr'))
            for ri,row in enumerate(rows):
                for cell in row.findall(Q('tc')):
                    cp=ensure(cell,'tcPr');borders=ensure(cp,'tcBorders',C_ORDER)
                    for edge in ['top','left','bottom','right','insideH','insideV','tl2br','tr2bl','start','end']:
                        on=grid and edge not in ['tl2br','tr2bl'] or not grid and ((edge=='top' and ri==0) or (edge=='bottom' and ri in [0,len(rows)-1]))
                        change(borders,edge,{'val':'single' if on else 'nil','sz':'4','color':'000000'},key,['top','start','left','bottom','end','right','insideH','insideV','tl2br','tr2bl'])
    paragraphs=list(d.iter(Q('p')));role_map=role_map or {}
    if any(not str(k).isdigit() or int(k)>=len(paragraphs) or v not in ['body','title','heading.1','heading.2','heading.3','caption.figure','caption.table','references','table.cell'] for k,v in role_map.items()):raise ValueError('Invalid explicit paragraph role mapping')
    ref_mode=False
    for index,p in enumerate(paragraphs):
        loc={'object':'paragraph','index':index}
        table=next((a for a in p.iterancestors(Q('tbl'))),None)
        if any(local(e) not in ['pPr','r','hyperlink','bookmarkStart','bookmarkEnd','proofErr','permStart','permEnd'] for e in p) or any(local(e) not in ['rPr','t','tab','br','cr','lastRenderedPageBreak','noBreakHyphen','softHyphen','drawing'] for r in p.findall('.//w:r',NS) for e in r) or dangerous(p) or any(local(a) in COMPLEX for a in p.iterancestors()) or table in unsafe_tables:
            skips.append({**loc,'reason':'formula_or_complex_object_preserved'});continue
        if p.findall('.//w:drawing',NS):
            if ''.join(p.itertext()).strip() or len(p.findall('.//w:drawing',NS))!=1:
                skips.append({**loc,'reason':'mixed_image_paragraph_preserved'});continue
            if 'image.alignment' in values:change(ensure(p,'pPr'),'jc',{'val':values['image.alignment']},'image.alignment',P_ORDER)
            continue
        text=''.join(p.itertext()).strip();sid=p.find('w:pPr/w:pStyle',NS);sid=sid.get(Q('val')) if sid is not None else None
        role=None;seen=set();names=[]
        while sid and sid not in seen:
            seen.add(sid);style=style_by_id.get(sid)
            if style is None:break
            name=style.find(Q('name'));names.append(name.get(Q('val'),'').lower() if name is not None else '')
            outline=style.find('w:pPr/w:outlineLvl',NS)
            if outline is not None and outline.get(Q('val')) in ['0','1','2'] and role is None:role='heading.'+str(int(outline.get(Q('val')))+1)
            base=style.find(Q('basedOn'));sid=base.get(Q('val')) if base is not None else None
        for name in names:
            if role:break
            m=re.fullmatch(r'(?:heading|标题)\s*([1-3])',name)
            if m:role='heading.'+m[1]
            elif name in ['title','标题']:role='title'
            elif name in ['figure caption','figcaption','图题']:role='caption.figure'
            elif name in ['table caption','tablecaption','表题']:role='caption.table'
            elif name in ['bibliography','参考文献正文']:role='references'
            elif name in ['caption','题注']:
                if re.match(r'^(图|Fig)',text):role='caption.figure'
                elif re.match(r'^(表|Table)',text):role='caption.table'
        if re.fullmatch(r'参考文献|References',text,re.I):ref_mode=True;role=role or 'heading.1'
        elif role and role.startswith(('heading.','title')):ref_mode=False
        elif ref_mode:role='references'
        role=role_map.get(str(index),role)
        if table is not None:role='table.cell'
        if role is None:
            explicit=p.find('w:pPr/w:pStyle',NS)
            if explicit is None or names and names[0] in ['normal','正文']:role='body'
        if role:paragraph(p,role)
        else:skips.append({**loc,'reason':'unrecognized_semantic_style'})
    math_present=any(local(e) in ['oMath','oMathPara','object'] for e in d.iter())
    for sec in d.iter(Q('sectPr')):
        if math_present:
            skips.append({'object':'section','reason':'page_changes_skipped_to_preserve_formula_layout'});continue
        size=values.get('page.size');orient=values.get('page.orientation')
        if size is not None or orient is not None:
            pg=sec.find(Q('pgSz'))
            dims={'A4':(11906,16838),'Letter':(12240,15840)}.get(size)
            if isinstance(size,dict):dims=(round(size['width']*1440/2.54),round(size['height']*1440/2.54))
            if dims is None and pg is not None and pg.get(Q('w')) and pg.get(Q('h')):dims=(int(pg.get(Q('w'))),int(pg.get(Q('h'))))
            if dims:
                actual_orient=orient or (pg.get(Q('orient'),'portrait') if pg is not None else 'portrait')
                dims=tuple(sorted(dims,reverse=actual_orient=='landscape'))
                attributes={}
                if size is not None or orient is not None:attributes.update(w=dims[0],h=dims[1])
                if orient is not None:attributes['orient']=orient
                change(sec,'pgSz',attributes,'page.size' if size is not None else 'page.orientation',['headerReference','footerReference','footnotePr','endnotePr','type','pgSz','pgMar','paperSrc','pgBorders','lnNumType','pgNumType','cols','formProt','vAlign','noEndnote','titlePg','textDirection','bidi','rtlGutter','docGrid'])
        for key,value in values.items():
            if key.startswith('page.margin.') or key in ['page.header_distance_cm','page.footer_distance_cm']:
                edge=key.split('.')[2][:-3] if key.startswith('page.margin.') else 'header' if 'header_' in key else 'footer'
                change(sec,'pgMar',{edge:round(value*1440/2.54)},key,['headerReference','footerReference','footnotePr','endnotePr','type','pgSz','pgMar','paperSrc','pgBorders','lnNumType','pgNumType','cols','formProt','vAlign','noEndnote','titlePg','textDirection','bidi','rtlGutter','docGrid'])
    if equation_indices:
        from equation_layout import apply
        required={'equation.body_alignment','equation.number_alignment','equation.center_reference','equation.tab_stops','equation.paragraph.alignment','equation.paragraph.line_spacing','equation.paragraph.first_line_chars','equation.paragraph.space_before_pt','equation.paragraph.space_after_pt'}
        if not required <= permitted:raise ValueError('Formula operation requires authorization for the entire geometry group')
        def attrs(root):return {(root.getroottree().getpath(e),k):v for e in root.iter() for k,v in e.attrib.items()}
        a=attrs(d)
        inventory,layout=apply(d,equation_indices,config,lambda parent,tag:ensure(parent,tag,P_ORDER),change)
        b=attrs(d)
        for path,attr in set(a)|set(b):
            if a.get((path,attr))!=b.get((path,attr)):mutations.append({'path':path,'attribute':attr,'after':b.get((path,attr)),'property':'equation.tab_stops'})
        edits.append({'property':'equation.tab_stops','location':'explicit formula paragraphs','element':'tabs'})
    else:
        from equation_layout import inventory as equation_inventory
        inventory=equation_inventory(d);layout=[]
    pagination_actions=[]
    if pagination_plan:
        from pagination_layout import apply as apply_pagination
        pagination_actions=apply_pagination(d,pagination_plan,lambda p,t:ensure(p,t,P_ORDER),change)
    changed=dict(parts);changed['word/document.xml']=E.tostring(d.getroottree(),xml_declaration=True,encoding='UTF-8',standalone=True)
    applied=sorted({e['property'] for e in edits})
    return changed,{'pagination_actions':pagination_actions,'formula_inventory':inventory,'formula_layout':layout,'formula_geometry_ready':False,'mutations':mutations,'edits':edits,'applied_properties':applied,'skipped_properties':[{'property':k,'reason':'unsupported_no_matching_safe_object_or_unchanged'} for k in sorted(permitted-set(applied))],
                    'skipped_objects':skips,'full_ready_for_writer':config['writer_contract']['ready_for_writer'],'partial_scope_execution':True,'partial_ready_for_supported_operations':True,'scope_completion':'partial; unsupported and protected objects skipped',
                    'pending_validation':config.get('pending_validation',[]),'visual_verification':'not_performed',
                    'complex_object_fidelity':'package_structure_preserved; rendering/behavior unverified'}

def verify_format_delta(before,after,report,config,scope):
    def attributes(data):
        root=parse(data);tree=root.getroottree()
        return {(tree.getpath(e),k):v for e in root.iter() if isinstance(e.tag,str) for k,v in e.attrib.items()}
    a,b=attributes(before),attributes(after);planned={}
    allowed=set(config['allowed_properties']) & (set(scope) if scope is not None else set(config['effective_properties']))
    for mutation in report['mutations']:
        if mutation['property'] not in allowed and not (mutation['property']=='pagination.explicit_plan' and report.get('pagination_actions')):raise ValueError('Unauthorized planned format change')
        planned[(mutation['path'],mutation['attribute'])]=mutation['after']
    for key in set(a)|set(b):
        if a.get(key)!=b.get(key) and (key not in planned or planned[key]!=b.get(key)):raise ValueError('Unexplained format/object attribute change')
    return True

def format_docx(input_path,output_path,config,scope=None,role_map=None,equation_indices=None,pagination_plan=None):
    inp=Path(input_path).resolve();out=Path(output_path).resolve()
    if inp==out or out.exists() or not any(out.is_relative_to(p) for p in [OUTPUT_ROOT,output_root('render'),output_root('pagination'),output_root('workflow'),output_root('experiment_report')]) or out.suffix.lower()!='.docx':raise ValueError('Output must be a new DOCX within an authorized workspace output root')
    if inp.suffix.lower()!='.docx':raise ValueError('Input must be DOCX')
    source_hash=digest(inp.read_bytes());parts,infos=read_package(inp)
    contract=config.get('writer_contract',{})
    if contract.get('source_docx_sha256') and contract['source_docx_sha256']!=source_hash:raise ValueError('Source hash does not match contract')
    if contract.get('input_path') and Path(contract['input_path']).resolve()!=inp:raise ValueError('Input differs from contract')
    if contract.get('output_path') and Path(contract['output_path']).resolve()!=out:raise ValueError('Output differs from contract')
    before=snapshot(parts,equation_indices or (),pagination_plan);changed,report=format_package(parts,config,scope,role_map,**({'equation_indices':equation_indices} if equation_indices else {}),**({'pagination_plan':pagination_plan} if pagination_plan else {}))
    verify_format_delta(parts['word/document.xml'],changed['word/document.xml'],report,config,scope)
    report['authorized_format_delta_passed']=True
    out.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=out.parent,suffix='.pending');os.close(fd);temp=Path(name)
    try:
        with ZipFile(temp,'w') as z:
            for info in infos:z.writestr(info,changed[info.filename])
        actual,_=read_package(temp);fidelity=compare_snapshots(before,snapshot(actual,equation_indices or (),pagination_plan));report['fidelity']=fidelity
        if not fidelity['passed']:raise ValueError('Content fidelity failed: '+str(fidelity['different_layers']))
        if digest(inp.read_bytes())!=source_hash:raise ValueError('Original changed during formatting')
        # Hard-link publication is atomic and refuses to replace a concurrent existing target.
        os.link(temp,out)
    finally:temp.unlink(missing_ok=True)
    report.update(schema_version='1.0',source_sha256=source_hash,source_unchanged=True,output=str(out),write_performed=True,package_check='ZIP/XML/content-types/relationship-target checks passed; full ECMA schema and Word rendering unverified')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--config',required=True,type=Path);p.add_argument('--report',required=True,type=Path);p.add_argument('--scope',type=Path);p.add_argument('--role-map',type=Path);p.add_argument('--equation-indices',type=Path);p.add_argument('--pagination-plan',type=Path);a=p.parse_args()
    try:
        report_path=a.report.resolve()
        if report_path.exists() or not any(report_path.is_relative_to(x) for x in [OUTPUT_ROOT,output_root('render'),output_root('pagination'),output_root('workflow'),output_root('experiment_report')]) or report_path.suffix!='.json':raise ValueError('Report must be a new JSON within an authorized workspace output root')
        report=format_docx(a.input,a.output,load_json(a.config),load_json(a.scope) if a.scope else None,load_json(a.role_map) if a.role_map else None,load_json(a.equation_indices) if a.equation_indices else None,load_json(a.pagination_plan) if a.pagination_plan else None)
        report_path.parent.mkdir(parents=True,exist_ok=True)
        with report_path.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
        print('New DOCX published; structural content fidelity passed; visual validation not performed.')
    except Exception as e:p.exit(1,f'Formatting stopped: {type(e).__name__}: {e}\n')
if __name__=='__main__':main()
