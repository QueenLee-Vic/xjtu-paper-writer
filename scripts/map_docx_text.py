#!/usr/bin/env python3
"""Read-only DOCX paragraph/run/object map; reuses package fidelity and style inheritance tools."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from lxml import etree as E
import format_docx as core
from inspect_docx import Inspector
from protect_academic_text import ROOT,digest,load_json

OUT=output_root('mapping');Q=core.Q;W=core.W;M=core.M;NS=core.NS
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
W14='http://schemas.microsoft.com/office/word/2010/wordml'
OBJECT_NAMES={'hyperlink':'hyperlink','fldSimple':'simple_field','fldChar':'field_boundary','instrText':'field_instruction','bookmarkStart':'bookmark_start','bookmarkEnd':'bookmark_end','ins':'revision_insertion','del':'revision_deletion','moveFrom':'revision_move_from','moveTo':'revision_move_to','txbxContent':'text_box','drawing':'drawing','anchor':'floating_image','pict':'legacy_picture','object':'embedded_object','sdt':'content_control','customXml':'custom_xml','commentRangeStart':'comment_range_start','commentRangeEnd':'comment_range_end','commentReference':'comment_reference','footnoteReference':'footnote_reference','endnoteReference':'endnote_reference','AlternateContent':'alternate_content','altChunk':'external_content','smartTag':'smart_tag','permStart':'permission_start','permEnd':'permission_end','sym':'symbol_glyph','pPrChange':'paragraph_format_revision','rPrChange':'run_format_revision'}
OPAQUE={'oMath','oMathPara','drawing','pict','object','txbxContent','ins','del','moveFrom','moveTo','sdt','customXml','AlternateContent','sym'}

def c14n(node):return E.tostring(node,method='c14n',exclusive=True) if node is not None else b''
def locator_id(prefix,part,locator):return prefix+core.digest((part+'\0'+locator).encode())[:28]
def owner(node):return next(node.iterancestors(Q('p')),None)
def story_key(p,part):
    ancestor=next((a for a in p.iterancestors() if core.local(a) in ['txbxContent','footnote','endnote','comment']),None)
    return part+(':'+ancestor.getroottree().getpath(ancestor) if ancestor is not None else '')

def range_states(root,part):
    """Detect multi-paragraph fields/bookmarks; malformed containers remain read-only."""
    depth=defaultdict(int);ranges=defaultdict(set);marks=defaultdict(set);members=defaultdict(set);bad=set()
    for node in root.iter():
        if not isinstance(node.tag,str):continue
        p=node if node.tag==Q('p') else owner(node)
        if p is None:continue
        key=story_key(p,part);members[key].add(p)
        if depth[key]:marks[p].add('inside_field')
        if ranges[key]:marks[p].add('inside_bookmark_or_comment_range')
        if node.tag==Q('fldChar'):
            marks[p].add('field_code');kind=node.get(Q('fldCharType'))
            if kind=='begin':depth[key]+=1
            elif kind=='end':
                if depth[key]==0:bad.add(key)
                else:depth[key]-=1
            elif kind!='separate' or not depth[key]:bad.add(key)
        local=core.local(node)
        if local in ['bookmarkStart','commentRangeStart']:
            token=(local,node.get(Q('id')))
            if token in ranges[key]:bad.add(key)
            ranges[key].add(token);marks[p].add('range_anchor')
        elif local in ['bookmarkEnd','commentRangeEnd']:
            token=('bookmarkStart' if local=='bookmarkEnd' else 'commentRangeStart',node.get(Q('id')))
            if token not in ranges[key]:bad.add(key)
            else:ranges[key].remove(token)
            marks[p].add('range_anchor')
    bad.update(k for k in members if depth[k] or ranges[k])
    for key in bad:
        for p in members[key]:marks[p].add('malformed_field_or_range_story')
    return marks,sorted(bad)

def role_of(p,text,sid,fmt,inspector):
    proxy=ET.Element(Q('p'));ET.SubElement(ET.SubElement(proxy,Q('r')),Q('t')).text=text
    role,basis=inspector.role(proxy,sid,fmt)
    names=[(s.find(Q('name')).get(Q('val'),'') if s.find(Q('name')) is not None else '').lower() for _,s in inspector.chain(sid)]
    if role=='references_heading':return role,None,basis
    if any(n in ['figure caption','figcaption','图题'] for n in names):return 'figure_caption',None,'semantic_style'
    if any(n in ['table caption','tablecaption','表题'] for n in names):return 'table_caption',None,'semantic_style'
    if any(n in ['caption','题注'] for n in names):return ('table_caption' if text.startswith(('表','Table')) else 'figure_caption'),None,'semantic_caption_style'
    if any(n in ['bibliography','参考文献正文'] for n in names):return 'references',None,'semantic_style'
    if any(n in ['equation','公式'] for n in names):return 'equation',None,'semantic_style'
    level=fmt.get('outlineLvl',{}).get('value')
    if level in [str(i) for i in range(9)]:return 'heading',int(level)+1,'outline_level'
    for name in reversed(names):
        match=re.fullmatch(r'(?:heading|标题)\s*([1-9])',name)
        if match:return 'heading',int(match[1]),'semantic_style'
    if role.startswith('heading_'):return 'heading',int(role[-1]),basis
    if role=='title':return role,None,basis
    if role in ['figure_caption','table_caption']:return role,None,basis
    if sid in inspector.invalid_styles or (sid and sid not in inspector.styles):return 'unknown',None,'missing_or_cyclic_style'
    if not names or names[-1] in ['normal','正文','body text','bodytext']:return 'body',None,'normal_or_default_style'
    return 'unknown',None,'unclassified_custom_style_not_guessed_from_font'

def map_docx(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT) or path.suffix.lower()!='.docx':raise ValueError('Input must be a project-local DOCX')
    source_sha=core.digest(path.read_bytes());parts,_=core.read_package(path);before=core.snapshot(parts)
    document_guards=[]
    if 'word/settings.xml' in parts:
        settings=core.parse(parts['word/settings.xml']);protection=settings.find(Q('documentProtection'));tracking=settings.find(Q('trackRevisions'))
        if protection is not None and protection.get(Q('enforcement'),'1') not in ['0','false','off']:document_guards.append('document_protection_active_or_unspecified')
        if tracking is not None and tracking.get(Q('val'),'1') not in ['0','false','off']:document_guards.append('revision_tracking_enabled')
    paragraphs=[];objects=[];sections=[];warnings=[];story_inventory=[];object_registry={}
    with ZipFile(path) as archive:
        inspector=Inspector(archive)
        story_parts=['word/document.xml']+[name for name in sorted(parts) if name!='word/document.xml' and name.endswith('.xml') and core.local(core.parse(parts[name])) in ['hdr','ftr','footnotes','endnotes','comments','glossaryDocument']]
        for part in story_parts:
            root=core.parse(parts[part]);nodes=list(root.iter(Q('p')));native_counts=Counter(p.get('{'+W14+'}paraId') for p in nodes if p.get('{'+W14+'}paraId'))
            marks,bad=range_states(root,part);warnings.extend('malformed_field_or_range:'+k for k in bad)
            relname=part.rsplit('/',1)[0]+'/_rels/'+part.rsplit('/',1)[1]+'.rels'
            relations={r.get('Id'):dict(r.attrib) for r in core.parse(parts[relname])} if relname in parts else {}
            ref_mode=False;heading_stack=[];story_inventory.append({'part':part,'paragraph_count':len(nodes),'xml_sha256':core.digest(parts[part]),'editable_story':part=='word/document.xml'})
            for pi,p in enumerate(nodes):
                tree=p.getroottree();xpath=tree.getpath(p);native=p.get('{'+W14+'}paraId');use_native=native and native_counts[native]==1
                pid=locator_id('p',part,'native:'+native if use_native else xpath)
                sid_node=p.find('w:pPr/w:pStyle',NS);sid=sid_node.get(Q('val')) if sid_node is not None else inspector.defaults['paragraph']
                table=next(p.iterancestors(Q('tbl')),None);table_style=table.find('w:tblPr/w:tblStyle',NS) if table is not None else None
                table_sid=table_style.get(Q('val')) if table_style is not None else inspector.defaults['table'] if table is not None else None
                pfmt=inspector.cascade('p',sid,p.find(Q('pPr')),table=table_sid)
                owned=[e for e in p.iter() if e is not p and isinstance(e.tag,str) and owner(e) is p]
                local_objects=[];by_element={}
                ancestors=[a for a in p.iterancestors() if core.local(a) in OBJECT_NAMES or a.tag in ['{'+M+'}oMath','{'+M+'}oMathPara']]
                for node in owned+ancestors:
                    name=core.local(node);kind='OMML' if node.tag in ['{'+M+'}oMath','{'+M+'}oMathPara'] else OBJECT_NAMES.get(name)
                    if not kind:continue
                    oid=locator_id('o',part,tree.getpath(node));obj={'id':oid,'kind':kind,'paragraph_id':pid,'part':part,'xpath':tree.getpath(node),'sha256':core.digest(c14n(node)),'attributes':dict(node.attrib),'projection_range':None,'verification':'extracted_from_source_docx_canonical_xml'}
                    if oid in object_registry:obj=object_registry[oid]
                    else:obj['paragraph_ids']=[];object_registry[oid]=obj
                    if pid not in obj['paragraph_ids']:obj['paragraph_ids'].append(pid)
                    if kind=='OMML':obj['equation_mode']='display' if name=='oMathPara' or any(a.tag=='{'+M+'}oMathPara' for a in node.iterancestors()) else 'inline'
                    if kind=='hyperlink':obj['relationship']=relations.get(node.get('{'+R+'}id'));obj['anchor']=node.get(Q('anchor'))
                    if kind in ['simple_field','field_instruction']:obj['instruction']=node.get(Q('instr')) if kind=='simple_field' else node.text
                    by_element[node]=obj;local_objects.append(obj)
                run_nodes=[r for r in p.iter(Q('r')) if owner(r) is p];runs=[];run_by={}
                for ri,r in enumerate(run_nodes):
                    rpath=tree.getpath(r);rp=r.find(Q('rPr'));charstyle=r.find('w:rPr/w:rStyle',NS);character=charstyle.get(Q('val')) if charstyle is not None else None
                    fmt=inspector.cascade('r',sid,rp,character=character,table=table_sid)
                    record={'id':locator_id('r',part,rpath),'paragraph_id':pid,'xpath':rpath,'xml_sha256':core.digest(c14n(r)),'original_text':'','range':None,'text_nodes':[],'direct_rPr_xml':c14n(rp).decode(),'direct_run_attributes':dict(r.attrib),'effective_format':fmt,'format_signature':digest({'rPr':c14n(rp).decode(),'run_attributes':dict(r.attrib),'paragraph_style':sid,'styles_sha256':core.digest(parts['word/styles.xml'])}),'protected_object_ids':[o['id'] for n,o in by_element.items() if r in n.iterancestors()],'safe_text_only':r.getparent() is p and len(r.findall(Q('t')))==1 and all(c.tag in [Q('rPr'),Q('t')] for c in r) and not any(core.local(c) in ['rPrChange','ins','del'] for c in r.iter())}
                    runs.append(record);run_by[r]=record
                chunks=[];offset=0
                def append(value):
                    nonlocal offset
                    start=offset;chunks.append(value);offset+=len(value);return [start,offset]
                def walk(node):
                    if node is not p and node.tag==Q('p'):return
                    name=core.local(node)
                    if node is not p and name in OPAQUE and node in by_element:
                        obj=by_element[node];token='⟦DOCX:'+obj['id']+'⟧';obj['placeholder']=token;obj['projection_range']=append(token);return
                    if node.tag==Q('t'):
                        value=node.text or '';span=append(value);r=next(node.iterancestors(Q('r')),None)
                        if r in run_by:
                            item=run_by[r];item['original_text']+=value;item['text_nodes'].append({'xpath':tree.getpath(node),'range':span,'text':value,'xml_space':node.get('{http://www.w3.org/XML/1998/namespace}space'),'xml_sha256':core.digest(c14n(node))})
                        return
                    if name in ['tab','br','cr','noBreakHyphen','softHyphen'] and any(a.tag==Q('r') for a in node.iterancestors()):append({'tab':'\t','br':'\n','cr':'\n','noBreakHyphen':'\u2011','softHyphen':'\u00ad'}[name]);return
                    if node.tag in [Q('pPr'),Q('rPr')]:return
                    for c in node:
                        if isinstance(c.tag,str):walk(c)
                walk(p);text=''.join(chunks)
                for r in runs:
                    if r['text_nodes']:r['range']=[r['text_nodes'][0]['range'][0],r['text_nodes'][-1]['range'][1]]
                    r['safe_text_only']=bool(r['safe_text_only'] and len(r['text_nodes'])==1)
                role,level,basis=role_of(p,text,sid,pfmt,inspector)
                if any(o['kind']=='OMML' for o in local_objects) and not re.sub(r'[（(]\d+[）)]', '',re.sub(r'⟦DOCX:[^⟧]+⟧','',text)).strip():role,level,basis='equation',None,'standalone_omml_structure'
                direct_body=part=='word/document.xml' and p.getparent().tag==Q('body')
                table=next(p.iterancestors(Q('tbl')),None);textbox=next((a for a in p.iterancestors() if core.local(a)=='txbxContent'),None)
                if direct_body:
                    if role=='references_heading':ref_mode=True
                    elif role in ['heading','title']:ref_mode=False
                    elif ref_mode:role='references';basis='within_references_section'
                    if role in ['heading','references_heading']:
                        sid_section=locator_id('s',part,xpath);actual_level=level or 1
                        while heading_stack and heading_stack[-1]['level']>=actual_level:heading_stack.pop()
                        section={'id':sid_section,'title':text,'heading_paragraph_id':pid,'level':actual_level,'parent_id':heading_stack[-1]['id'] if heading_stack else None,'ancestor_ids':[s['id'] for s in heading_stack]}
                        sections.append(section);heading_stack.append(section)
                section_id=heading_stack[-1]['id'] if heading_stack and part=='word/document.xml' else None
                reasons=set(marks[p])|set(document_guards)
                if part!='word/document.xml':reasons.add('auxiliary_story_preserved')
                if not direct_body:reasons.add('non_body_or_nested_paragraph_preserved')
                if table is not None:reasons.add('table_text_preserved')
                if textbox is not None:reasons.add('text_box_preserved')
                if role!='body':reasons.add('protected_or_unknown_semantic_role:'+role)
                if local_objects:reasons.add('complex_or_protected_objects_preserved')
                if core.dangerous(p):reasons.add('phase3_complex_object_guard')
                if any(c.tag not in [Q('pPr'),Q('r')] for c in p):reasons.add('non_plain_paragraph_children')
                if any(not r['safe_text_only'] for r in runs) or not runs:reasons.add('unsupported_run_structure')
                if any(c in text for c in ['\n','\r','\t']):reasons.add('structural_breaks_in_text')
                if p.find('w:pPr/w:sectPr',NS) is not None:reasons.add('section_boundary_paragraph')
                mapping={'id':pid,'part':part,'xpath':xpath,'ordinal_in_part':pi,'native_para_id':native,'id_basis':'unique_native_paraId' if use_native else 'structural_path_bound_to_source_hash','native_id_status':'unique' if use_native else 'duplicate_ignored' if native else 'absent','text':text,'text_sha256':digest(text),'text_utf8_sha256':core.digest(text.encode()),'xml_sha256':core.digest(c14n(p)),'role':role,'role_basis':basis,'heading_level':level,'section_id':section_id,'container':'table' if table is not None else 'textbox' if textbox is not None else 'body' if direct_body else 'auxiliary_or_nested','paragraph_properties_xml':c14n(p.find(Q('pPr'))).decode(),'paragraph_style_id':sid,'effective_paragraph_format':pfmt,'runs':runs,'protected_object_ids':[o['id'] for o in local_objects],'mapping_editable':not reasons,'mapping_blockers':sorted(reasons)}
                paragraphs.append(mapping);objects.extend(local_objects)
        warnings.extend(sorted(inspector.warnings))
    exported=[]
    for p in paragraphs:
        role='body' if p['mapping_editable'] else 'heading' if p['role'] in ['title','heading','references_heading'] else 'references' if p['role']=='references' else 'caption' if p['role'] in ['figure_caption','table_caption'] else 'equation' if p['role']=='equation' else 'data'
        exported.append({'id':p['id'],'section_id':p['section_id'],'role':role,'text':p['text'],'word_binding':{'part':p['part'],'xpath':p['xpath'],'paragraph_xml_sha256':p['xml_sha256'],'paragraph_style_id':p['paragraph_style_id'],'run_ids':[r['id'] for r in p['runs']],'mapping_editable':p['mapping_editable']}})
    objects=list(object_registry.values())
    protected=[{k:v for k,v in o.items() if k not in ['projection_range','verification']} for o in objects]
    mapped_doc={'data_kind':'read_only_docx_projection_not_scientific_verification','source_binding':{'path':str(path.relative_to(ROOT)),'source_docx_sha256':source_sha},'paragraphs':exported,'sections':sections,'protected_objects':protected}
    # Read-only parsing is checked at both package and input-file levels.
    after,_=core.read_package(path);fidelity=core.compare_snapshots(before,core.snapshot(after))
    if not fidelity['passed'] or core.digest(path.read_bytes())!=source_sha or parts!=after:raise ValueError('Source changed during read-only mapping')
    result={'schema_version':'1.0','kind':'docx_text_map','mapping_contract_version':'docx-map-1.0','source_path':str(path.relative_to(ROOT)),'source_docx_sha256':source_sha,'offset_unit':'Unicode code points; object placeholders occupy logical projection offsets, not Word UTF-16 positions','text_hash_encoding':'polish-1.0 canonical JSON UTF-8 scalar; text_utf8_sha256 is raw UTF-8','paragraphs':paragraphs,'objects':objects,'sections':sections,'stories':story_inventory,'polish_document':mapped_doc,'package_part_hashes':{n:core.digest(data) for n,data in parts.items()},'phase3_fidelity_snapshot':before,'read_only_fidelity':fidelity,'warnings':sorted(set(warnings)),'source_unchanged':True,'docx_write_performed':False,'full_word_schema_validated':False,'word_visual_verified':False}
    if document_guards:result['document_guards']=document_guards
    result['mapping_hash']=digest(result)
    return result

def write_json(path,value):
    path=Path(path).resolve()
    if not path.is_relative_to(OUT) or path.exists() or path.suffix!='.json':raise ValueError('New JSON output within the authorized workspace required')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('--output',required=True);a=p.parse_args()
    try:result=map_docx(a.input);write_json(a.output,result);print('Read-only map:',len(result['paragraphs']),'paragraphs,',len(result['objects']),'objects; no DOCX written.')
    except Exception as e:p.exit(1,str(e)+'\n')
