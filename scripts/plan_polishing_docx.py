#!/usr/bin/env python3
"""Build a read-only, source-bound DOCX polishing preview. There is no DOCX writing path."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse
from copy import deepcopy
import difflib
from safe_preview import preview_text
import json
from pathlib import Path
import re
from map_docx_text import ROOT,OUT,map_docx,write_json
from protect_academic_text import digest,load_json
from review_polishing_diff import review
import format_docx as core


def resolve_scope(mapping,scope):
    if not isinstance(scope,dict):raise ValueError('Explicit scope object required')
    by={p['id']:p for p in mapping['paragraphs']};kind=scope.get('kind');ranges={}
    if kind=='document':ids=[p['id'] for p in mapping['paragraphs'] if p['part']=='word/document.xml']
    elif kind=='paragraphs':ids=scope.get('paragraph_ids',[])
    elif kind=='sections':
        ids_section=scope.get('section_ids',[]);sections=mapping['sections']
        if scope.get('section_titles'):
            if ids_section:raise ValueError('Choose section IDs or titles')
            ids_section=[]
            for title in scope['section_titles']:
                matches=[s['id'] for s in sections if s['title']==title]
                if len(matches)!=1:raise ValueError('Ambiguous or missing semantic section title')
                ids_section+=matches
        if not isinstance(ids_section,list) or not ids_section or len(set(ids_section))!=len(ids_section) or any(s not in {v['id'] for v in sections} for s in ids_section):raise ValueError('Invalid section selection')
        include=scope.get('include_subsections',True)
        if type(include)is not bool:raise ValueError('include_subsections must be boolean')
        expanded=set(ids_section)|{s['id'] for s in sections if include and set(s['ancestor_ids'])&set(ids_section)}
        ids=[p['id'] for p in mapping['paragraphs'] if p['part']=='word/document.xml' and p['section_id'] in expanded]
    elif kind=='ranges':
        entries=scope.get('ranges')
        if not isinstance(entries,list) or not entries:raise ValueError('Nonempty text ranges required')
        for r in entries:
            if not isinstance(r,dict) or r.get('paragraph_id') not in by:raise ValueError('Unknown range paragraph')
            pid=r['paragraph_id'];a=r.get('start');b=r.get('end');allow=r.get('allow_end_insertion',False)
            if type(a)is not int or type(b)is not int or not 0<=a<b<=len(by[pid]['text']) or type(allow)is not bool:raise ValueError('Invalid Unicode code-point range')
            ranges.setdefault(pid,[]).append({'start':a,'end':b,'allow_end_insertion':allow})
        for pid,values in ranges.items():
            values.sort(key=lambda r:r['start'])
            if any(a['end']>b['start'] for a,b in zip(values,values[1:])):raise ValueError('Overlapping ranges require one explicit union')
        ids=list(ranges)
    else:raise ValueError('Unsupported scope')
    if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids) or any(pid not in by for pid in ids):raise ValueError('Unknown/duplicate/empty paragraph scope')
    for pid in ids:
        if pid not in ranges:ranges[pid]=[{'start':0,'end':len(by[pid]['text']),'allow_end_insertion':True}]
    return ids,ranges

def within_ranges(before,after,ranges):
    for tag,a,b,c,d in difflib.SequenceMatcher(None,before,after).get_opcodes():
        if tag=='equal':continue
        if tag=='insert':ok=any(r['start']<=a<r['end'] or a==r['end'] and r['allow_end_insertion'] for r in ranges)
        else:ok=any(r['start']<=a and b<=r['end'] for r in ranges)
        if not ok:return False
    return True

def allocate_runs(paragraph,new_text):
    """Uniform runs retain every node; mixed formatting permits only one unambiguous local run edit."""
    runs=paragraph['runs'];old=paragraph['text']
    if not paragraph['mapping_editable']:return {'safe':False,'reason':'paragraph_mapping_blocked','blockers':paragraph['mapping_blockers'],'patches':[]}
    if any(c in new_text for c in ['\r','\n','\t','\ufffe','\uffff']):return {'safe':False,'reason':'new_text_requires_structural_or_invalid_xml_characters','patches':[]}
    if ''.join(r['original_text'] for r in runs)!=old or any(not r['safe_text_only'] for r in runs):return {'safe':False,'reason':'incomplete_plain_text_run_coverage','patches':[]}
    signatures={r['format_signature'] for r in runs};allocation=[]
    if len(signatures)==1:
        cursor=0
        for i,r in enumerate(runs):
            value=new_text[cursor:cursor+len(r['original_text'])] if i<len(runs)-1 else new_text[cursor:]
            allocation.append((r,value));cursor+=len(value)
        reason='uniform_run_properties_preserve_all_existing_nodes'
    else:
        possibilities=[]
        for r in runs:
            a,b=r['range'];prefix=old[:a];suffix=old[b:]
            if not r['original_text'] or len(new_text)<len(prefix)+len(suffix):continue
            if new_text.startswith(prefix) and new_text.endswith(suffix):
                value=new_text[len(prefix):len(new_text)-len(suffix) if suffix else len(new_text)]
                if value and value!=r['original_text']:possibilities.append((r,value))
        if len(possibilities)!=1:return {'safe':False,'reason':'mixed_format_attribution_ambiguous_or_cross_run_reorganization','candidate_run_count':len(possibilities),'patches':[]}
        changed,value=possibilities[0];allocation=[(r,value if r['id']==changed['id'] else r['original_text']) for r in runs];reason='single_local_run_edit_with_all_other_format_anchors_frozen'
    if ''.join(value for _,value in allocation)!=new_text:raise ValueError('Run allocation does not reproduce exact proposed text')
    patches=[]
    for run,value in allocation:
        if value==run['original_text']:continue
        node=run['text_nodes'][0];space='preserve' if value and (value[0].isspace() or value[-1].isspace()) else node['xml_space']
        patches.append({'operation':'proposed_replace_existing_w_t_text','run_id':run['id'],'part':paragraph['part'],'text_xpath':node['xpath'],'old_text':node['text'],'new_text':value,'old_text_node_xml_sha256':node['xml_sha256'],'old_run_xml_sha256':run['xml_sha256'],'required_format_signature':run['format_signature'],'original_xml_space':node['xml_space'],'proposed_xml_space':space,'preserve_run_and_text_nodes':True})
    return {'safe':True,'reason':reason,'patches':patches,'unchanged_run_ids':[r['id'] for r,v in allocation if v==r['original_text']],'no_paragraph_reconstruction':True,'format_semantics_limit':'Local structural attribution, not a Microsoft Word visual verification'}

def semantic_task_binding(request,b1_report):
    return digest({'mode':b1_report['plan']['mode'],'operation':b1_report['plan']['operation'],'intensity':b1_report['plan']['intensity'],'scope':request['scope'],'policy_sha256':b1_report['plan']['policy_sha256'],'protected_terms':request.get('protected_terms',[]),'extra_units':request.get('extra_units',[]),'term_corrections':request.get('term_corrections',[]),'cross_paragraph_edits':request.get('cross_paragraph_edits',[])})

def build_plan(input_docx,mapping,request,candidate,semantic_reviews=None,upstream_review=None):
    if mapping.get('schema_version')!='1.0' or mapping.get('mapping_contract_version')!='docx-map-1.0':raise ValueError('Unsupported DOCX mapping schema')
    cached=deepcopy(mapping);declared=cached.pop('mapping_hash',None)
    if digest(cached)!=declared:raise ValueError('Mapping content/hash changed')
    actual=map_docx(input_docx)
    if actual['mapping_hash']!=declared:raise ValueError('Mapping is stale or belongs to another source DOCX')
    if request.get('mapping_hash')!=declared:raise ValueError('Request must bind the exact mapping_hash')
    if request.get('document')!=actual['polish_document']:raise ValueError('Original text/metadata/objects must exactly match verified DOCX projection')
    if request.get('docx_interface',{}).get('input_docx') and (ROOT/request['docx_interface']['input_docx']).resolve()!=Path(input_docx).resolve():raise ValueError('polish-1.0 input path differs from mapped source')
    selected,ranges=resolve_scope(actual,request.get('scope'));normalized=deepcopy(request);normalized['scope']={'kind':'paragraphs','paragraph_ids':selected}
    result=review(normalized,candidate,semantic_reviews)
    task_hash=semantic_task_binding(request,result)
    if upstream_review is not None:
        if upstream_review.get('source_hash')!=result['source_hash'] or upstream_review.get('candidate_hash')!=result['candidate_hash'] or upstream_review.get('docx_interface',{}).get('contract_version')!='polish-1.0':raise ValueError('Upstream review binding mismatch')
        # A supplied ready flag is never trusted: the entire semantic review is recomputed above.
    authorization=request.get('authorization',{})
    authorized=isinstance(authorization,dict) and authorization.get('granted') is True and authorization.get('source_docx_sha256')==actual['source_docx_sha256'] and authorization.get('scope_sha256')==digest(request['scope']) and isinstance(authorization.get('basis'),str) and bool(authorization['basis'].strip())
    old={p['id']:p for p in actual['paragraphs']};new={p['id']:p for p in candidate['paragraphs']};semantic={e['unit_id']:e for e in result['semantic_review']};cross_ids={pid for g in request.get('cross_paragraph_edits',[]) for pid in g['paragraph_ids']}
    edits=[];global_blockers=[]
    if not result['automatic_checks_passed']:global_blockers.append('phase4b1_automatic_protection_or_scope_failed')
    if result['status']=='rejected':global_blockers.append('phase4b1_review_rejected')
    for pid in result['changed_paragraph_ids']:
        p=old[pid];text=new[pid]['text'];allowed=ranges.get(pid,[]);blockers=[]
        if not authorized:blockers.append('missing_source_and_scope_bound_authorization')
        if request.get('mode')=='format_only':blockers.append('format_only_forbids_polishing')
        if request.get('operation','polish')=='check_language':blockers.append('check_language_forbids_editing')
        if pid not in selected or not within_ranges(p['text'],text,allowed):blockers.append('change_outside_authorized_text_range')
        allocation=allocate_runs(p,text)
        if not allocation['safe']:blockers.append(allocation['reason']);blockers.extend(allocation.get('blockers',[]))
        if pid in cross_ids:blockers.append('cross_paragraph_run_attribution_not_supported')
        units=[u for u in result['review_units'] if pid in u['paragraph_ids']]
        semantic_ok=bool(units) and all(semantic.get(u['unit_id'],{}).get('state')=='attested_preserved' and u['automatic_invariants_passed'] for u in units)
        context_records={r.get('unit_id'):r for r in semantic_reviews or []}
        context_bound=bool(units) and all(context_records.get(u['unit_id'],{}).get('docx_source_sha256')==actual['source_docx_sha256'] and context_records.get(u['unit_id'],{}).get('mapping_hash')==actual['mapping_hash'] and context_records.get(u['unit_id'],{}).get('source_document_hash')==digest(request['document']) and context_records.get(u['unit_id'],{}).get('candidate_document_hash')==digest(candidate) and context_records.get(u['unit_id'],{}).get('task_hash')==task_hash and context_records.get(u['unit_id'],{}).get('simulated') is False for u in units)
        if semantic_ok and not context_bound:blockers.append('semantic_evidence_not_bound_to_docx_mapping_and_whole_candidate')
        semantic_ok=semantic_ok and context_bound
        if not semantic_ok:blockers.append('semantic_review_missing_uncertain_simulated_or_rejected')
        blockers.extend(global_blockers);eligible=not blockers
        edits.append({'paragraph_id':pid,'part':p['part'],'xpath':p['xpath'],'old_text':p['text'],'old_text_sha256':p['text_sha256'],'old_paragraph_xml_sha256':p['xml_sha256'],'new_text':text,'new_text_sha256':digest(text),'allowed_ranges':allowed,'run_mapping':allocation,'involved_run_ids':[r['run_id'] for r in allocation['patches']],'preserve_format':{'paragraph_properties_xml':p['paragraph_properties_xml'],'all_original_run_format_signatures':{r['id']:r['format_signature'] for r in p['runs']},'styles_part_sha256':actual['package_part_hashes']['word/styles.xml'],'all_other_parts_sha256':{n:h for n,h in actual['package_part_hashes'].items() if n!='word/document.xml'}},'protected_objects':p['protected_object_ids'],'semantic_review_verified':semantic_ok,'risk_level':'blocked' if not eligible else 'bounded_local_mapping','eligible_for_future_simple_run_patch':eligible,'write_allowed_this_phase':False,'pending_items':sorted(set(blockers))})
    eligible=bool(edits) and all(e['eligible_for_future_simple_run_patch'] for e in edits)
    if global_blockers:status='blocked_preview'
    elif not edits:status='skipped_format_only' if request.get('mode')=='format_only' else 'suggestions_only' if request.get('operation')=='check_language' else 'no_changes'
    else:status='preview_ready_for_future_revalidation' if eligible else 'blocked_preview'
    future=deepcopy(result['docx_interface']);future.update(mapping_extension='docx-map-1.0',source_docx_sha256=actual['source_docx_sha256'],mapping_hash=actual['mapping_hash'],locator_policy='Re-enumerate source paragraph/run/text locators in the exact bound package and match IDs, paths and hashes; never locate by text or evaluate an untrusted cached XPath alone.',paragraph_mapping_verified=True,simple_scope_mapping_eligible=eligible,allowed_xml_changes=['existing w:t text','xml:space on those w:t only when whitespace requires it'],forbidden_xml_changes=['pPr','rPr','run or paragraph node reconstruction','object subtrees','relationships','styles','media','all other package parts'],expected_validation=['exact source byte hash','mapping hash and locators','original paragraph/run/text node hashes','authorization scope','full fresh Phase 4B-1 semantic evidence','unchanged rPr/pPr/objects and all nontext parts','only authorized w:t changes and required xml:space','render check or explicit unverified'],docx_write_ready=False,docx_write_performed=False,final_publish_status='preview_only_phase4b2a')
    outcome={'schema_version':'1.0','kind':'docx_polishing_plan','mapping_contract_version':'docx-map-1.0','source_path':actual['source_path'],'source_docx_sha256':actual['source_docx_sha256'],'mapping_hash':actual['mapping_hash'],'requested_scope':request['scope'],'normalized_phase4b1_scope':normalized['scope'],'authorization_verified':authorized,'intensity':result['plan']['intensity'],'status':status,'edits':edits,'all_planned_edits_mapping_eligible':eligible,'full_text_delivery_ready':result['text_delivery_ready'],'phase4b1_review':result,'scope_readiness_note':'Per-edit mapping eligibility does not clear global protected-object reassembly or permit a DOCX write. A future writer must revalidate every binding.','current_phase_write_allowed':False,'docx_write_performed':False,'source_unchanged':True,'read_only_fidelity':actual['read_only_fidelity'],'future_writer_contract':future,'blocked_or_unmodified_objects_preserved':True,'word_visual_verified':False}
    if core.digest(Path(input_docx).read_bytes())!=actual['source_docx_sha256']:raise ValueError('Source changed during planning')
    outcome['semantic_task_hash']=task_hash
    return outcome

def preview(plan):
    def cell(v):return preview_text(v, 'table')
    lines=['# DOCX 润色修改预览','',f"状态：{preview_text(plan['status'])}。本阶段只读，不允许写入 DOCX。",'', '| 段落 ID | 原文 | 候选 | Run 映射 | 语义审查 | 下一阶段局部候选 | 本阶段写入 |','| --- | --- | --- | --- | --- | --- | --- |']
    for e in plan['edits']:lines.append('| '+' | '.join(cell(v) for v in [e['paragraph_id'],e['old_text'],e['new_text'],e['run_mapping']['reason'],e['semantic_review_verified'],e['eligible_for_future_simple_run_patch'],False])+' |')
    lines+=['','## 待处理事项','']
    for e in plan['edits']:
        if e['pending_items']:lines.append('- '+preview_text(e['paragraph_id'])+'：'+preview_text('; '.join(e['pending_items'])))
    if not plan['edits']:lines.append('没有正文修改操作；仍需查看完整保护审查状态。检查模式只交建议，未生成 DOCX。')
    lines.append('实际 DOCX 写入与输出保真留待 4B-2B；须重新校验源文件、Run/对象及全部审查证据。本阶段没有写入许可。')
    lines+=['','完整正文交付状态与局部映射可行性分开；复杂对象占位、语义未审及格式归属不明不会被清除。Microsoft Word 与页面视觉效果未验证。','']
    return '\n'.join(lines)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('--mapping',required=True);p.add_argument('--request',required=True);p.add_argument('--candidate',required=True);p.add_argument('--semantic-reviews');p.add_argument('--upstream-review');p.add_argument('--output-dir',required=True);a=p.parse_args()
    try:
        out=Path(a.output_dir).resolve()
        if not out.is_relative_to(OUT) or out.exists():raise ValueError('New preview directory within the authorized workspace required')
        r=build_plan(a.input,load_json(a.mapping),load_json(a.request),load_json(a.candidate),load_json(a.semantic_reviews) if a.semantic_reviews else None,load_json(a.upstream_review) if a.upstream_review else None)
        out.mkdir(parents=True);write_json(out/'plan.json',r)
        with (out/'preview.md').open('x',encoding='utf-8') as f:f.write(preview(r))
        print(r['status'],'; no DOCX written.')
    except Exception as e:p.exit(1,str(e)+'\n')
