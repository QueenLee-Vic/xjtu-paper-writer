"""Portable figure classification, provenance gates, and host-attested optional skill routing."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import hashlib
import json
from pathlib import Path
import re

ROOT=data_root()
ROLES={'A':'explanatory_schematic','B':'real_data_visualization','C':'experimental_or_simulation_material','D':'external_academic_image'}

def file_evidence(path):
    if not path:return {'present':False,'status':'missing'}
    p=(ROOT/path).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('Source files must be within project')
    if not p.is_file() or not p.stat().st_size:return {'present':False,'status':'missing_or_empty','path':str(p.relative_to(ROOT))}
    return {'present':True,'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'status':'file_present_not_authenticity_verified'}

def inspect_external(capability=None):
    """Never invent shell commands. An agent must review installed instructions and execute via its host."""
    if not capability:return {'name':'baoyu-diagram','ready':False,'status':'not_discovered_or_host_unavailable','actual_execution_verified':False}
    c=capability
    if not isinstance(c,dict):raise ValueError('External capability must be an object')
    path=Path(c.get('skill_path',''))
    if not path.is_file() or path.name!='SKILL.md':return {'name':'baoyu-diagram','ready':False,'status':'instructions_missing','actual_execution_verified':False}
    instructions=path.read_text(encoding='utf-8')
    front=re.match(r'\A---\s*\n(.*?)\n---',instructions,re.S)
    found=bool(front and re.search(r'''^name:\s*["']?baoyu-diagram["']?\s*$''',front[1],re.M))
    checks={'exact_skill_name':found,'instructions_reviewed':c.get('instructions_reviewed') is True,
            'instruction_digest_matches':c.get('instructions_sha256')==hashlib.sha256(path.read_bytes()).hexdigest(),
            'host_invocation_available':c.get('host_invocation_available') is True and bool(c.get('host_interface')) and bool(c.get('host_evidence')),
            'dependencies_checked':isinstance(c.get('dependencies'),list) and all(isinstance(d,dict) and d.get('available') is True and d.get('evidence') for d in c.get('dependencies',[])),
            'academic_light_supported':isinstance(c.get('supported_themes'),list) and 'academic_light' in c['supported_themes'],
            'declared_interface':isinstance(c.get('supported_kinds'),list) and isinstance(c.get('output_formats'),list) and bool(c['output_formats'])}
    ready=all(checks.values())
    return {'name':'baoyu-diagram','skill_path':str(path),'instructions_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'ready':ready,'status':'ready_for_host_invocation' if ready else 'not_ready','checks':checks,
            'supported_kinds':c.get('supported_kinds',[]),'output_formats':c.get('output_formats',[]),
            'supported_themes':c.get('supported_themes',[]),'host_interface':c.get('host_interface'),'simulated':c.get('simulated') is True,
            'verification_status':'host_attestation_only_not_executed_by_this_script','actual_execution_verified':False}

def classify(figure):
    source=figure.get('source',{});text=(figure.get('request','')+' '+figure.get('purpose','')).lower();stype=source.get('source_type','')
    schematic=bool(figure.get('diagram')) or any(k in text for k in ['流程图','路线图','架构图','关系图','原理图','结构图','示意图','flowchart','roadmap','architecture','schematic'])
    if stype=='external_reference' or any(k in text for k in ['文献图片','论文中的图','引用图片','external reference']):return 'D','source_or_reference_intent'
    if stype in ['user_image','experiment_output','simulation_output'] or any(k in text for k in ['截图','装置照片','实验照片','运行结果图','测试结果图','神经网络测试结果','screenshot']):return 'C','actual_result_intent'
    if stype in ['user_data','program_results','public_dataset','synthetic_example','synthetic_test_data'] or any(k in text for k in ['数据曲线','损失曲线','准确率曲线','柱状','散点','误差棒','统计结果','loss curve','scatter','data curve']):return 'B','data_intent'
    if schematic:return 'A','schematic_intent'
    if any(k in text for k in ['matlab','solidworks','mujoco','comsol']):return 'C','software_material_intent'
    return None,'unclassified_requires_context'

def plan(request,capability=None):
    if not isinstance(request,dict) or request.get('schema_version')!='1.0':raise ValueError('Figure request requires schema_version 1.0')
    mode=request.get('mode','create');operation=request.get('operation','figures')
    if mode not in ['create','modify','format_only'] or operation not in ['figures','polish']:raise ValueError('Unsupported mode/operation')
    figures=request.get('figures',[])
    if not isinstance(figures,list) or len(figures)>30:raise ValueError('figures must contain at most 30 records')
    external=inspect_external(capability);records=[];seen=set()
    for f in figures:
        if not isinstance(f,dict):raise ValueError('Figure must be object')
        fid=f.get('image_id')
        if not isinstance(fid,str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,39}',fid) or fid in seen:raise ValueError('Invalid/duplicate image_id')
        seen.add(fid)
        for key in ['request','purpose','section','caption']:
            if key in f and not isinstance(f[key],str):raise ValueError('Figure text fields must be strings')
        if f.get('diagram') is not None and not isinstance(f['diagram'],dict):raise ValueError('Diagram must be an object')
        source=f.get('source',{})
        if not isinstance(source,dict):raise ValueError('source must be object')
        for key in ['source_type','source_path','source_reference','permission']:
            if key in source and source[key] is not None and not isinstance(source[key],str):raise ValueError('Invalid source field '+key)
        kind,reason=classify(f)
        if f.get('image_type') and f['image_type']!=kind:raise ValueError('Declared type conflicts with source/intent')
        need=f.get('need',{})
        if not isinstance(need,dict) or any(type(v)is not bool for v in need.values()):raise ValueError('Need flags must be booleans')
        status='planned';route=None;confirm=[]
        if mode=='format_only':status='skipped_format_only'
        elif operation=='polish':status='skipped_polish_only'
        elif mode=='modify' and fid not in request.get('authorized_image_ids',[]):status='blocked_not_authorized'
        elif not any(need.get(k,False) for k in ['user_requested','teacher_required','helps_explain']):status='skipped_not_needed'
        elif not kind:status='needs_confirmation';confirm=['image_type_or_purpose_unclear']
        evidence=file_evidence(source.get('source_path')) if status=='planned' else {'present':False,'status':'not_read_for_skipped_task'}
        if status=='planned':
            if kind=='A':
                if not f.get('diagram') or not source.get('source_reference'):status='blocked_missing_basis';confirm=['diagram_structure_and_reliable_basis_needed']
                else:
                    dkind=f['diagram'].get('kind')
                    if external['ready'] and dkind in external.get('supported_kinds',[]):status='awaiting_external_host';route='baoyu-diagram'
                    else:status='ready_builtin';route='builtin_svg'
            elif kind=='B':
                route='phase4a2_data_plot_interface'
                if source.get('source_type')=='synthetic_example':status='blocked_synthetic_not_experiment'
                elif not evidence['present'] or not source.get('source_reference'):status='blocked_missing_real_data';confirm=['real_data_and_provenance_needed']
                elif Path(evidence['path']).suffix.lower() not in ['.csv','.tsv','.xlsx','.xlsm','.json']:status='blocked_invalid_data_format'
                else:status='deferred_data_validation_and_plotting'
            elif kind=='C':
                route='preserve_supplied_material'
                if not evidence['present'] or not source.get('source_reference'):status='blocked_missing_experimental_material';confirm=['actual_material_and_provenance_needed']
                else:status='material_registered_authenticity_unverified'
            elif kind=='D':
                route='reference_and_permission_review'
                if not source.get('source_reference') or source.get('permission') not in ['user_attested_authorized','public_license_reported']:status='needs_confirmation';confirm=['citation_and_permission_needed']
                else:status='reference_registered_permission_attested_not_verified'
        caption=f.get('caption') or ('图{n} '+f.get('purpose','')+('（示意图）' if kind=='A' else ''))
        if kind=='A' and '示意图' not in caption:caption+='（示意图）'
        records.append({'image_id':fid,'image_type':kind,'classification_reason':reason,'section':f.get('section'),'purpose':f.get('purpose'),
                        'source_type':'agent_authored_explanatory_schematic' if kind=='A' else source.get('source_type'),
                        'source_path':source.get('source_path'),'source_reference':source.get('source_reference'),'source_evidence':evidence,
                        'source_status':'knowledge_basis_supplied_not_experimental_evidence' if kind=='A' else 'not_independently_verified',
                        'generation_method':route,'status':status,'needs_confirmation':bool(confirm),'confirmation_reasons':confirm,
                        'caption':caption,'verification_status':'not_generated_or_validated','output_formats':external.get('output_formats',[]) if route=='baoyu-diagram' else ['svg','png_optional'] if kind=='A' else [],
                        'external_task':{'diagram':f.get('diagram'),'purpose':f.get('purpose'),'section':f.get('section'),'diagram_kind':f.get('diagram',{}).get('kind'),'theme':'academic_light','caption':caption,'source_reference':source.get('source_reference'),'execution':'host must read actual installed instructions; no universal shell command'} if route=='baoyu-diagram' else None})
    for record in records:
        if record['image_type'] in ['C','D'] and record['source_evidence'].get('present') and record['status'] in ['material_registered_authenticity_unverified','reference_registered_permission_attested_not_verified']:
            path=Path(record['source_evidence']['path']);ext=path.suffix.lower()
            if ext in ['.png','.jpg','.jpeg']:
                record['output_hashes']={'png' if ext=='.png' else 'jpeg':record['source_evidence']['sha256']}
                record['docx_interface']={'image_path':str(path),'image_type':record['image_type'],'suggested_width_cm':14,'preserve_aspect_ratio':True,'caption':record['caption'],'source_reference':record['source_reference'],'insertion_authorized':False,'quality_status':'material_requires_actual_image_review'}
                if record['image_type']=='D':record['permission_status']='attested_not_independently_verified'
    return {'schema_version':'1.0','kind':'figure_plan','mode':mode,'operation':operation,'external_capability':external,'figures':records,'docx_write_performed':False}
