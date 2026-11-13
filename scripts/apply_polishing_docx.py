#!/usr/bin/env python3
"""Apply freshly revalidated local w:t patches; atomically publish only after exact delta fidelity."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile
from lxml import etree as E
import format_docx as core
from map_docx_text import ROOT,c14n
from plan_polishing_docx import build_plan
from protect_academic_text import digest,load_json

OUT=output_root('polishing_writer');MAIN='word/document.xml';SPACE='{http://www.w3.org/XML/1998/namespace}space'

def tree_c14n(root):return E.tostring(root.getroottree(),method='c14n',with_comments=True)
def nodes_by_path(root):return {root.getroottree().getpath(n):n for n in root.iter() if isinstance(n.tag,str)}

def patch_package(parts,plan,mapping):
    """All original locators and hashes are checked before any in-memory XML edit."""
    if {k:core.digest(v) for k,v in parts.items()}!=mapping['package_part_hashes']:raise ValueError('Package parts differ from verified source mapping')
    root=core.parse(parts[MAIN]);nodes=nodes_by_path(root);known={p['id']:p for p in mapping['paragraphs']};prepared=[];seen=set();journal=[]
    for edit in plan['edits']:
        p=known[edit['paragraph_id']];element=nodes.get(edit['xpath'])
        if element is None or element.tag!=core.Q('p') or core.digest(c14n(element))!=edit['old_paragraph_xml_sha256']:raise ValueError('Original paragraph hash/location mismatch')
        runs={r['id']:r for r in p['runs']}
        for op in edit['run_mapping']['patches']:
            if op['operation']!='proposed_replace_existing_w_t_text' or op['part']!=MAIN or op['text_xpath'] in seen:raise ValueError('Unsupported or duplicate patch operation')
            node=nodes.get(op['text_xpath']);run=runs.get(op['run_id']);re=nodes.get(run['xpath']) if run else None
            if node is None or node.tag!=core.Q('t') or len(node) or re is None or node.getparent() is not re or re.getparent() is not element:raise ValueError('Target is not one plain existing w:t in the original run')
            if core.digest(c14n(node))!=op['old_text_node_xml_sha256'] or core.digest(c14n(re))!=op['old_run_xml_sha256'] or (node.text or '')!=op['old_text']:raise ValueError('Original Run/text content or hash changed')
            if run['format_signature']!=op['required_format_signature'] or node.get(SPACE)!=op['original_xml_space']:raise ValueError('Original format/space binding mismatch')
            seen.add(op['text_xpath']);prepared.append((node,op));journal.append({'paragraph_id':edit['paragraph_id'],**deepcopy(op)})
    if not prepared:raise ValueError('No actual authorized text patches')
    for node,op in prepared:
        node.text=op['new_text']
        if op['proposed_xml_space'] is None:node.attrib.pop(SPACE,None)
        else:node.set(SPACE,op['proposed_xml_space'])
    changed=dict(parts);changed[MAIN]=E.tostring(root.getroottree(),xml_declaration=True,encoding='UTF-8',standalone=True)
    return changed,journal

def verify_polishing_delta(before,after,plan,journal):
    if set(before)!=set(after):raise ValueError('Package part set changed')
    unexpected=[n for n in before if n!=MAIN and before[n]!=after[n]]
    if unexpected:raise ValueError('Unauthorized package part change: '+','.join(unexpected))
    original=core.parse(before[MAIN]);actual=core.parse(after[MAIN]);restored=core.parse(after[MAIN]);a=nodes_by_path(original);b=nodes_by_path(actual);restore_nodes=nodes_by_path(restored)
    expected=[{'paragraph_id':e['paragraph_id'],**op} for e in plan['edits'] for op in e['run_mapping']['patches']]
    if journal!=expected:raise ValueError('Patch journal differs from revalidated plan')
    text_changes=[]
    for op in journal:
        path=op['text_xpath'];old=a.get(path);new=b.get(path);target=restore_nodes.get(path)
        if old is None or new is None or target is None or old.tag!=core.Q('t') or new.tag!=core.Q('t'):raise ValueError('Planned text node missing or structurally moved')
        if (old.text or '')!=op['old_text'] or (new.text or '')!=op['new_text']:raise ValueError('Output text differs from exact authorized candidate')
        if new.get(SPACE)!=op['proposed_xml_space']:raise ValueError('Output xml:space differs from exact plan')
        attrs=dict(old.attrib)
        if op['proposed_xml_space'] is None:attrs.pop(SPACE,None)
        else:attrs[SPACE]=op['proposed_xml_space']
        if dict(new.attrib)!=attrs or len(new)!=len(old):raise ValueError('Unapproved text-node attribute/structure change')
        target.text=old.text
        if old.get(SPACE) is None:target.attrib.pop(SPACE,None)
        else:target.set(SPACE,old.get(SPACE))
        text_changes.append({'paragraph_id':op['paragraph_id'],'run_id':op['run_id'],'xpath':path,'before':op['old_text'],'after':op['new_text'],'xml_space_before':old.get(SPACE),'xml_space_after':new.get(SPACE)})
    if tree_c14n(restored)!=tree_c14n(original):raise ValueError('Unauthorized main XML content, format, object or structure change')
    for edit in plan['edits']:
        p=b.get(edit['xpath'])
        if p is None or ''.join(t.text or '' for r in p.findall(core.Q('r')) for t in r.findall(core.Q('t')))!=edit['new_text']:raise ValueError('Output paragraph does not reproduce the complete proposed text')
    # Substitute original bytes only AFTER complete canonical inverse restoration equality.
    restored_parts=dict(after);restored_parts[MAIN]=before[MAIN]
    layered=core.compare_snapshots(core.snapshot(before),core.snapshot(restored_parts))
    if not layered['passed']:raise ValueError('Restored Phase 3 fidelity layers failed')
    def fingerprints(root,tag):return [core.digest(c14n(e)) for e in root.iter(tag)]
    checks={label:fingerprints(original,tag)==fingerprints(actual,tag) for label,tag in [('run_properties',core.Q('rPr')),('paragraph_properties',core.Q('pPr')),('section_properties',core.Q('sectPr')),('tables',core.Q('tbl')),('drawings',core.Q('drawing')),('legacy_pictures',core.Q('pict'))]}
    checks['omml_objects_and_order']=core.snapshot(before)['formula_objects']==core.snapshot(after)['formula_objects']
    checks['complex_subtrees']=core.snapshot(before)['protected_subtrees']==core.snapshot(after)['protected_subtrees']
    if not all(checks.values()):raise ValueError('Format or protected object fingerprint changed')
    return {'passed':True,'authorized_text_changes':text_changes,'exact_authorized_candidate_verified':True,'main_xml_inverse_restoration_equal':True,'other_package_parts_byte_equal':True,'all_package_parts_preserved':True,'original_format_and_objects':checks,'phase3_restored_snapshot':layered,'academic_protection':'Fresh Phase 4B-1 protection and bound semantic reviews passed before write; actual output text matches that candidate','layout_unchanged':False,'layout_status':'unverified; text length may change line/page breaks','microsoft_word_verified':False,'full_ecma_schema_validated':False}

def apply_polishing(input_docx,output_docx,plan,mapping,request,candidate,semantic_reviews):
    inp=Path(input_docx).resolve();rawout=Path(output_docx).absolute();out=rawout.resolve()
    if rawout.is_symlink() or inp==out or out.exists() or not any(out.is_relative_to(p) for p in [OUT,output_root('workflow')]) or out.suffix.lower()!='.docx':raise ValueError('Output must be a new DOCX within an authorized workspace output root; input must never be overwritten')
    if request.get('docx_interface',{}).get('output_docx') and (ROOT/request['docx_interface']['output_docx']).resolve()!=out:raise ValueError('Output differs from bound polish-1.0 contract')
    fresh=build_plan(inp,mapping,request,candidate,semantic_reviews)
    if digest(plan)!=digest(fresh):raise ValueError('Supplied plan differs from fresh source/authorization/protection/semantic review')
    if request.get('mode')=='format_only' or request.get('operation')=='check_language' or not fresh['edits']:
        if fresh['status'] not in ['skipped_format_only','suggestions_only','no_changes']:raise ValueError('Read-only request contains rejected changes')
        return {'schema_version':'1.0','execution_contract_version':'polish-write-1.0','status':fresh['status'],'write_performed':False,'source_unchanged':True,'output_published':False,'preflight_plan_hash':digest(fresh),'rendering':'not_applicable_no_output'}
    if not fresh['all_planned_edits_mapping_eligible'] or not fresh['authorization_verified']:raise ValueError('Polishing blocked: '+json.dumps([{'paragraph_id':e['paragraph_id'],'reasons':e['pending_items']} for e in fresh['edits']],ensure_ascii=False))
    source_sha=fresh['source_docx_sha256'];parts,infos=core.read_package(inp)
    if core.digest(inp.read_bytes())!=source_sha:raise ValueError('Source changed after preflight')
    changed,journal=patch_package(parts,fresh,mapping)
    if set(changed)!=set(parts):raise ValueError('Patch attempted to add or remove package parts')
    out.parent.mkdir(parents=True,exist_ok=True);fd,name=tempfile.mkstemp(dir=out.parent,suffix='.pending.docx');os.close(fd);temp=Path(name)
    try:
        with ZipFile(inp) as source:comment=source.comment
        with ZipFile(temp,'w') as z:
            z.comment=comment
            for info in infos:z.writestr(info,changed[info.filename])
        actual,_=core.read_package(temp);fidelity=verify_polishing_delta(parts,actual,fresh,journal)
        if core.digest(inp.read_bytes())!=source_sha:raise ValueError('Source changed before publication')
        output_sha=core.digest(temp.read_bytes());os.link(temp,out)
    finally:temp.unlink(missing_ok=True)
    return {'schema_version':'1.0','execution_contract_version':'polish-write-1.0','status':'published_structurally_verified_render_pending','input':str(inp.relative_to(ROOT)),'output':str(out.relative_to(ROOT)),'source_sha256':source_sha,'output_sha256':output_sha,'source_unchanged':True,'write_performed':True,'output_published':True,'preflight_plan_hash':digest(fresh),'mapping_hash':mapping['mapping_hash'],'semantic_task_hash':fresh['semantic_task_hash'],'preview_flags_unchanged':{'current_phase_write_allowed':plan['current_phase_write_allowed'],'preview_docx_write_ready':plan['future_writer_contract']['docx_write_ready']},'execution_authorization':'Explicit Phase 4B-2B invocation plus freshly verified source/scope-bound authorization; preview flags were not changed','journal':journal,'fidelity':fidelity,'semantic_evidence_limit':'Hash binding identifies the reviewed version; Agent judgment is not independent scientific truth verification','rendering':'pending','microsoft_word_verified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('--output',required=True);p.add_argument('--plan',required=True);p.add_argument('--mapping',required=True);p.add_argument('--request',required=True);p.add_argument('--candidate',required=True);p.add_argument('--semantic-reviews',required=True);p.add_argument('--report',required=True);a=p.parse_args()
    try:
        report=Path(a.report).resolve()
        if not any(report.is_relative_to(p) for p in [OUT,output_root('workflow')]) or report.exists() or report.suffix!='.json' or report==Path(a.output).resolve():raise ValueError('New JSON execution report within an authorized workspace output root required')
        result=apply_polishing(a.input,a.output,load_json(a.plan),load_json(a.mapping),load_json(a.request),load_json(a.candidate),load_json(a.semantic_reviews))
        report.parent.mkdir(parents=True,exist_ok=True)
        with report.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
        print(result['status'])
    except Exception as e:p.exit(1,type(e).__name__+': '+str(e)+'\n')
