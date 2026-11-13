#!/usr/bin/env python3
"""Review proposed academic edits: mechanical invariants plus itemized semantic attestation."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse
from collections import Counter
from copy import deepcopy
import difflib
import hashlib
from pathlib import Path
import re
from protect_academic_text import POLICY,MARKER,ROOT,clean_text,digest,inventory,plan,validate_document,write_new,load_json


def counter_rows(counter):return [{'kind':k,'value':v,'count':n} for (k,v),n in sorted(counter.items())]

def text_diff(before,after):
    return [{'operation':tag,'before_start':a,'before_end':b,'after_start':c,'after_end':d,'before':before[a:b],'after':after[c:d]} for tag,a,b,c,d in difflib.SequenceMatcher(None,before,after).get_opcodes() if tag!='equal']

def semantic_flags(before,after):
    flags=[]
    for category,values in POLICY['semantic_cues'].items():
        a={v:before.count(v) for v in values if v in before};b={v:after.count(v) for v in values if v in after}
        if a!=b:flags.append({'kind':'semantic_cue_change','category':category,'before':a,'after':b,'meaning':'lexical signal only; assess actual relations in context'})
    if any(c['operation'] in ['delete','replace'] and c['before'].strip() for c in text_diff(before,after)):flags.append({'kind':'information_loss_or_paraphrase_review','meaning':'removed wording may contain independent information; not automatically classified as redundant'})
    if len(after)>len(before):flags.append({'kind':'possible_new_information_or_expansion','meaning':'more characters do not prove new facts; compare claims'})
    return flags

def review_semantics(unit,records):
    matches=[r for r in records if r.get('unit_id')==unit['unit_id']]
    if len(matches)!=1:return {'state':'pending','reason':'one itemized semantic review required','unit_id':unit['unit_id']}
    record=matches[0]
    if record.get('source_text_sha256')!=digest(unit['before']) or record.get('candidate_text_sha256')!=digest(unit['after']):return {'state':'rejected','reason':'semantic review hash binding mismatch','unit_id':unit['unit_id']}
    if record.get('reviewer_kind') not in ['agent','human'] or not isinstance(record.get('reviewer'),str) or not record['reviewer'].strip():return {'state':'rejected','reason':'reviewer identity/kind required','unit_id':unit['unit_id']}
    assessments=record.get('assessments',{})
    if not isinstance(assessments,dict):return {'state':'rejected','reason':'invalid assessments','unit_id':unit['unit_id']}
    required=set(POLICY['semantic_dimensions']);missing=required-set(assessments)
    if missing:return {'state':'pending','reason':'missing dimensions: '+','.join(sorted(missing)),'unit_id':unit['unit_id']}
    reasons=[];pending=False
    cue_dimensions={'uncertainty':'conclusion_strength','certainty':'conclusion_strength','negation':'negation','causality':'causality_and_correlation','conditions_scope':'conditions_and_scope','completion_time':'completion_and_time','comparison_attribution':'comparison_and_attribution'}
    relevant={cue_dimensions[k] for k,words in POLICY['semantic_cues'].items() if any(w in unit['before'] or w in unit['after'] for w in words)}
    for dimension in POLICY['semantic_dimensions']:
        item=assessments[dimension]
        if not isinstance(item,dict):reasons.append('malformed '+dimension);continue
        if item.get('status') not in ['preserved','changed','uncertain','not_applicable'] or not isinstance(item.get('rationale'),str) or not item['rationale'].strip():reasons.append('invalid status/rationale '+dimension);continue
        a=item.get('before_quote');b=item.get('after_quote')
        if not isinstance(a,str) or not a or a not in unit['before'] or not isinstance(b,str) or not b or b not in unit['after']:reasons.append('evidence not in exact text '+dimension)
        if item['status']=='changed':reasons.append('meaning changed: '+dimension)
        if item['status']=='uncertain':pending=True
        if item['status']=='not_applicable' and dimension in relevant|{'facts','independent_information','author_intent','intensity_boundary'}:reasons.append('cannot bypass '+dimension)
    if unit.get('structural_operation'):
        structural=record.get('structural_review',{})
        if structural.get('operation')!=unit['structural_operation'] or structural.get('preserves_each_information_unit') is not True or not structural.get('rationale'):pending=True
    return {'unit_id':unit['unit_id'],'state':'rejected' if reasons else 'uncertain' if pending else 'simulated_only' if record.get('simulated') is True else 'attested_preserved','reasons':reasons,'verification':'hash-bound reviewer attestation, not independent proof of scientific truth','reviewer':record['reviewer'],'reviewer_kind':record['reviewer_kind'],'all_dimensions_checked':not reasons and not pending}

def review(request,candidate,semantic_reviews=None,capability=None):
    task=plan(request,capability);original=request['document'];validate_document(candidate,allow_markers=True)
    records=semantic_reviews or []
    if not isinstance(records,list) or any(not isinstance(r,dict) for r in records):raise ValueError('Semantic reviews must be objects')
    if len({r.get('unit_id') for r in records})!=len(records):raise ValueError('Duplicate semantic review unit')
    violations=[];issues=[];units=[];changed=[];corrections=request.get('term_corrections',[])
    if not isinstance(corrections,list):raise ValueError('term_corrections must be a list')
    replacements={}
    for item in corrections:
        if not isinstance(item,dict) or item.get('authorized') is not True or not item.get('basis') or not isinstance(item.get('from'),str) or not item['from'] or not isinstance(item.get('to'),str) or not item['to'] or item['from'] in replacements:raise ValueError('Explicit term correction requires unique from/to, authorization and basis')
        if any(c.isdigit() for c in item['from']+item['to']) or re.search(r'[$\\\[\]=±]',item['from']+item['to']):raise ValueError('Term correction cannot authorize data/formula/citation edits')
        replacements[item['from']]=item['to']
    # Only paragraph text may differ. All identities, metadata, sections and opaque Word objects stay frozen.
    def without_text(doc):
        copy=deepcopy(doc)
        for p in copy['paragraphs']:p.pop('text',None)
        return copy
    if without_text(original)!=without_text(candidate):violations.append({'kind':'document_structure_or_protected_object_changed'})
    old={p['id']:p for p in original['paragraphs']};new={p['id']:p for p in candidate['paragraphs']}
    if set(old)!=set(new):violations.append({'kind':'paragraph_added_or_deleted'})
    terms=request.get('protected_terms',[]);extra_units=request.get('extra_units',[])
    if not isinstance(terms,list) or not isinstance(extra_units,list):raise ValueError('Terms/units must be lists')
    for pid,p in old.items():
        if pid not in new:continue
        a=p['text'];b=new[pid]['text']
        if MARKER in b:violations.append({'kind':'unrestored_formula_placeholder','paragraph_id':pid})
        if a!=b:
            changed.append(pid)
            if pid not in task['editable_paragraph_ids']:violations.append({'kind':'outside_edit_scope','paragraph_id':pid})
            issues.append({'paragraph_id':pid,'changes':text_diff(a,b),'semantic_risks':semantic_flags(a,b)})
    groups=task['cross_paragraph_edits'];grouped={pid for g in groups for pid in g['paragraph_ids']}
    blocks=[{'unit_id':p['id'],'paragraph_ids':[p['id']]} for p in original['paragraphs'] if p['id'] in changed and p['id'] not in grouped]
    for i,g in enumerate(groups):
        ids=[p['id'] for p in original['paragraphs'] if p['id'] in g['paragraph_ids']]
        if any(pid in changed for pid in ids):blocks.append({'unit_id':'group'+str(i+1),'paragraph_ids':ids,'structural_operation':g['operation']})
    for block in blocks:
        ids=block['paragraph_ids'];a='\n\n'.join(old[pid]['text'] for pid in ids);b='\n\n'.join(new[pid]['text'] for pid in ids)
        expected=a
        for source,target in replacements.items():expected=expected.replace(source,target)
        # Correction permissions apply ONLY to terms, never to formula text, bibliography or numeric values.
        actual_tokens=inventory(b,terms,extra_units);before_tokens=inventory(a,terms,extra_units);expected_tokens=inventory(expected,terms,extra_units)
        expected_tokens=Counter({k:v for k,v in before_tokens.items() if k[0] not in ['term','acronym']})+Counter({k:v for k,v in expected_tokens.items() if k[0] in ['term','acronym']})
        removed=expected_tokens-actual_tokens;added=actual_tokens-expected_tokens
        if removed or added:violations.append({'kind':'protected_item_changed','unit_id':block['unit_id'],'removed':counter_rows(removed),'added':counter_rows(added)})
        unit={**block,'before':a,'after':b,'source_text_sha256':digest(a),'candidate_text_sha256':digest(b),'risk_flags':semantic_flags(a,b),'automatic_invariants_passed':not (removed or added)}
        units.append(unit)
    known_units={u['unit_id'] for u in units}
    if any(r.get('unit_id') not in known_units for r in records):violations.append({'kind':'semantic_review_for_unknown_or_unchanged_unit'})
    evaluations=[review_semantics(u,records) for u in units]
    rejected=any(r['state']=='rejected' for r in evaluations);pending=any(r['state'] in ['pending','uncertain','simulated_only'] for r in evaluations)
    placeholders=any(o.get('placeholder') for o in original.get('protected_objects',[]))
    if violations or rejected:state='rejected'
    elif task['mode']=='format_only':state='skipped_format_only'
    elif task['operation']=='check_language':state='suggestions_only'
    elif pending:state='needs_semantic_review'
    elif placeholders:state='needs_protected_object_reassembly'
    elif not changed:state='unchanged'
    else:state='ready_for_text_delivery_with_attested_review'
    suggestions=request.get('suggestions',[])
    if not isinstance(suggestions,list) or any(not isinstance(s,dict) or s.get('paragraph_id') not in task['selected_paragraph_ids'] or not isinstance(s.get('suggestion'),str) for s in suggestions):raise ValueError('Suggestions must refer to selected paragraphs')
    unresolved=[]
    if pending:unresolved.append('itemized semantic review missing/uncertain')
    if placeholders:unresolved.append('opaque Word objects require Phase 4B-2 protected reassembly; placeholders are not final deliverables')
    if violations:unresolved.append('automatic protection/scope violation')
    if rejected:unresolved.append('semantic reviewer identified a change or invalid attestation')
    future=request.get('docx_interface',{})
    if not isinstance(future,dict):raise ValueError('docx_interface must be object')
    paths={}
    for key in ['input_docx','output_docx']:
        path=future.get(key)
        if path is not None:
            if not isinstance(path,str):raise ValueError('DOCX paths must be strings')
            path=(ROOT/path).resolve()
            if not path.is_relative_to(ROOT) or path.suffix.lower()!='.docx':raise ValueError('Future DOCX path must be within project')
            paths[key]=str(path)
        else:paths[key]=None
    if paths['input_docx'] and paths['input_docx']==paths['output_docx']:raise ValueError('Future DOCX paths must differ')
    if paths['output_docx'] and Path(paths['output_docx']).exists():raise ValueError('Future output must be a new DOCX path')
    interface={'schema_version':'1.0','contract_version':'polish-1.0',**paths,'mode':task['mode'],'operation':task['operation'],'intensity':task['intensity'],'authorized_paragraph_ids':task['editable_paragraph_ids'],'formatting_preservation_status':'not_verified_no_docx_write_in_this_phase','source_docx_sha256':hashlib.sha256(Path(paths['input_docx']).read_bytes()).hexdigest() if paths['input_docx'] and Path(paths['input_docx']).is_file() else None,'source_text_document_hash':digest(original),'candidate_document_hash':digest(candidate),'paragraph_edits':[{'paragraph_id':pid,'original_text':old[pid]['text'],'proposed_text':new[pid]['text'],'source_metadata':{k:v for k,v in old[pid].items() if k!='text'}} for pid in changed if pid in task['editable_paragraph_ids'] and pid in new],'protected_objects':deepcopy(original.get('protected_objects',[])),'diff_review_status':state,'paragraph_mapping_verified':False,'unresolved':[*unresolved,'Phase 4B-2 must validate source paragraph/run mapping and nontext object fidelity'],'preserve':['fonts','sizes','colors','bold','italic','underline','run_properties','paragraph_properties','section_settings','spacing','heading_hierarchy','images','tables','omml','headers_footers','references','bookmarks','links','footnotes_endnotes','all_nontext_objects'],'reject_unsafe':['complex_runs_without_verified_mapping','fields','revisions','textboxes','unrecognized_objects'],'final_publish_status':'not_implemented_phase4b1','docx_write_ready':False,'docx_write_performed':False}
    return {'schema_version':'1.0','kind':'academic_polishing_review','plan':task,'source_hash':digest(original),'candidate_hash':digest(candidate),'automatic_checks_passed':not violations,'violations':violations,'changed_paragraph_ids':changed,'differences':issues,'review_units':units,'semantic_review':evaluations,'semantic_verification':'reviewer attestation only; automatic checks do not prove meaning/factual equivalence','status':state,'text_delivery_ready':state in ['unchanged','ready_for_text_delivery_with_attested_review'] and task['mode']!='format_only' and task['operation']=='polish','suggestions':suggestions,'unresolved':unresolved,'docx_interface':interface,'source_files_modified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True,type=Path);p.add_argument('--candidate',required=True,type=Path);p.add_argument('--semantic-reviews',type=Path);p.add_argument('--capabilities',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    try:
        r=review(load_json(a.request),load_json(a.candidate),load_json(a.semantic_reviews) if a.semantic_reviews else None,load_json(a.capabilities) if a.capabilities else None);write_new(a.output,r);print(r['status']);raise SystemExit(2 if r['status']=='rejected' else 0)
    except (ValueError,TypeError,KeyError,OSError) as e:p.exit(1,str(e)+'\n')
