#!/usr/bin/env python3
"""Compose NEW experiment-report drafts; reuse Pandoc and the existing style/fidelity writer."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse,copy,json,os,subprocess,tempfile,hashlib,struct
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
import format_docx as core
from resolve_style_config import resolve,PRIORITIES
ROOT=data_root()
OUT=output_root('experiment_report')
TEMPLATE=SKILL_ROOT/'assets/templates/experiment-report-structure.json'

def text(v):
    if not isinstance(v,str) or not v.strip() or len(v)>3000 or any(ord(c)<32 and c not in '\n\t' for c in v):raise ValueError('Nonempty safe text required')
    try:v.encode('utf-8')
    except UnicodeError as exc:raise ValueError('Invalid Unicode text') from exc
    return v.strip()

def local_branding(request,cfg):
    if request.get('badge_path'):raise ValueError('Arbitrary branding paths are not authorized; use the registered local resource')
    badge=cfg['badge']
    enabled=request.get('use_local_branding',badge.get('local_use_enabled',False))
    if not isinstance(enabled,bool):raise ValueError('use_local_branding must be boolean')
    if not enabled:
        return {'kind':'text','reason':'local_branding_disabled'}
    path=(SKILL_ROOT/badge['local_resource']).resolve();manifest=(SKILL_ROOT/badge['local_manifest']).resolve()
    if not path.is_relative_to(SKILL_ROOT/'assets/local/branding') or not manifest.is_relative_to(SKILL_ROOT/'assets/local/branding'):raise ValueError('Branding must stay in local-only assets')
    if not path.is_file() or not manifest.is_file():return {'kind':'text','reason':'local_branding_missing'}
    info=json.loads(manifest.read_text())
    blob=path.read_bytes()
    if hashlib.sha256(blob).hexdigest()!=info['sha256']:raise ValueError('Local branding identity changed')
    if blob[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Expected original PNG branding')
    width,height=struct.unpack('>II',blob[16:24])
    if width<=0 or height<=0 or (width,height)!=(info['width_px'],info['height_px']):raise ValueError('Branding dimensions differ from provenance')
    if not isinstance(info.get('public_redistribution_authorized'),bool):raise ValueError('Explicit branding provenance required')
    return {'kind':'image','path':str(path),'sha256':info['sha256'],'width_cm':badge['width_cm'],'height_cm':badge['width_cm']*info['height_px']/info['width_px'],'width_px':info['width_px'],'height_px':info['height_px'],'public_distributable':info['public_redistribution_authorized']}

def plan(request):
    if not isinstance(request,dict):raise ValueError('Request must be an object')
    cfg=json.loads(TEMPLATE.read_text());kind=request.get('article_type')
    if kind not in cfg['covers']:raise ValueError('Explicit personal_experiment or group_experiment required')
    if request.get('mode','create')!='create':raise ValueError('New reports only; never add covers in modify/format_only')
    if request.get('teacher_cover_template'):raise ValueError('Teacher cover supplied: adapt that cover, do not substitute the default builder')
    info=request.get('cover',{});cover=cfg['covers'][kind]
    if not isinstance(info,dict):raise ValueError('Cover must be an object')
    for field in cover['fields']:
        if field!='members':text(info.get(field))
    if kind=='group_experiment':
        members=info.get('members')
        if not isinstance(members,list) or not members:raise ValueError('Actual member records required')
        for m in members:
            for c in cover['member_columns']:text(m.get(c['key']))
        if len({m['student_id'] for m in members})!=len(members):raise ValueError('Duplicate member identity')
        if len(members)>20:raise ValueError('Cover capacity needs manual layout review; never truncate members')
    questions=request.get('teacher_questions',[]);tasks=request.get('experiment_tasks',[])
    if not isinstance(questions,list) or not isinstance(tasks,list):raise ValueError('Questions/tasks must be explicit lists')
    for q in questions:text(q)
    for t in tasks:text(t['title']);text(t.get('text','[待提供本任务材料]'))
    chapters=copy.deepcopy(cfg['chapters']);source={'role':'skill_defaults','priority':5,'basis':'frozen structure defaults, not source content'}
    choices=[]
    for s in request.get('structure_sources',[]):
        if s.get('role') not in PRIORITIES or s['role']=='skill_defaults' or not s.get('source'):raise ValueError('Attributed structure source required')
        choices.append(s)
    if choices:
        priority=min(PRIORITIES[s['role']] for s in choices);top=[s for s in choices if PRIORITIES[s['role']]==priority]
        if any(s['chapters']!=top[0]['chapters'] for s in top):raise ValueError('Same-priority structure conflict needs confirmation')
        chapters=copy.deepcopy(top[0]['chapters']);source={'role':top[0]['role'],'priority':priority,'basis':top[0]['source']}
    selected=[];pending=[];omitted=[]
    for ch in chapters:
        cid=ch['id'];text(ch['title'])
        if cid=='contributions' and kind!='group_experiment':
            if source['priority']<5:raise ValueError('Personal/group chapter conflict needs confirmation')
            omitted.append({'id':cid,'reason':'personal report'});continue
        if cid=='questions' and not questions and source['priority']==5:omitted.append({'id':cid,'reason':'teacher did not provide questions'});continue
        title=ch['title']
        if cid=='equipment' and request.get('software_only') and source['priority']==5:title=ch['software_title']
        body=request.get('section_text',{}).get(cid)
        if cid=='questions':body='\n'.join(questions) if questions else None
        if cid=='contributions':
            contributions=request.get('member_contributions')
            if contributions:
                expected={m['student_id'] for m in info['members']}
                if not isinstance(contributions,dict) or set(contributions)!=expected:raise ValueError('Contributions must match provided member identities')
                body='\n'.join(m['name']+'：'+text(contributions[m['student_id']]) for m in info['members'])
            else:body=None
        if body is None:body='[待提供：'+title+']';pending.append(cid)
        text(body);selected.append({'id':cid,'title':title,'level':1,'text':body,'children':copy.deepcopy(tasks) if cid=='content' else []})
    if not selected or len({c['id'] for c in selected})!=len(selected):raise ValueError('Unique chapters required')
    return {'article_type':kind,'cover':copy.deepcopy(info),'cover_title':cover['title'],'chapters':selected,'omitted':omitted,'pending_materials':pending,'structure_source':source,'cover_layout':cfg['cover_layout'],'badge':local_branding(request,cfg),'is_final_article':False,'validation':'layout pending actual render; long fields/member lists may need adaptation'}

def S(s):return {'t':'Str','c':s}
def para(s):return {'t':'Para','c':[S(s)]}
def heading(s,level):return {'t':'Header','c':[level,['',[],[]],[S(s)]]}
def write_zip(path,parts,infos):
    with ZipFile(path,'w') as z:
        for info in infos:z.writestr(info,parts[info.filename])

def build(request,directory):
    p=plan(request);out=Path(directory).resolve()
    if not out.is_relative_to(OUT) or out.exists():raise ValueError('New directory within the authorized workspace required')
    out.mkdir(parents=True);cover=p['cover'];brand=p['badge']
    top=para('西安交通大学')
    if brand['kind']=='image':
        attrs=['',[],[['width',str(brand['width_cm'])+'cm'],['height',str(brand['height_cm'])+'cm']]]
        top={'t':'Para','c':[{'t':'Image','c':[attrs,[S('西安交通大学校徽及中英文校名')],[brand['path'],'']]}]}
    blocks=[top,para(cover['course_name']+' · '+p['cover_title']),para('实验项目：'+cover['experiment_name'])]
    if p['article_type']=='personal_experiment':
        for key,label in [('name','姓名'),('major','专业'),('class_name','班级'),('student_id','学号')]:blocks.append(para(label+'：'+cover[key]))
    else:
        headers=[[para(c)] for c in ['班级','学号','姓名']]
        rows=[[[para(m[k])] for k in ['class_name','student_id','name']] for m in cover['members']]
        blocks.append({'t':'Table','c':[[],[{'t':'AlignCenter'}]*3,[1/3]*3,headers,rows]})
    blocks.append(para('日期：'+cover['date']));cover_block_count=len(blocks)
    nums=['一','二','三','四','五','六','七','八','九','十']
    if len(p['chapters'])>len(nums):raise ValueError('More than ten chapters requires explicit numbering support')
    for i,ch in enumerate(p['chapters']):
        blocks.append(heading(nums[i]+'、'+ch['title'],1))
        for part in ch['text'].splitlines():blocks.append(para(part))
        for j,task in enumerate(ch['children'],1):blocks.extend([heading(str(j)+'. '+task['title'],2),para(task.get('text','[待提供本任务材料]'))])
    version=json.loads(subprocess.check_output(['pandoc','-f','markdown','-t','json'],input=b''))['pandoc-api-version']
    if version!=[1,20]:raise ValueError('Only installed audited Pandoc AST 1.20 table schema supported')
    ast={'pandoc-api-version':version,'meta':{},'blocks':blocks};(out/'authored-structure.json').write_text(json.dumps(ast,ensure_ascii=False,indent=2))
    subprocess.run(['pandoc','-f','json',str(out/'authored-structure.json'),'-o',str(out/'raw.docx')],check=True)
    parts,infos=core.read_package(out/'raw.docx');d=core.parse(parts['word/document.xml']);body=d.find(core.Q('body'));body_nodes=[n for n in body if n.tag!=core.Q('sectPr')]
    for pp in [n for n in body_nodes[:cover_block_count] if n.tag==core.Q('p')][:2]:core.ensure(core.ensure(pp,'pPr'),'pStyle',core.P_ORDER).set(core.Q('val'),'Title')
    first_body=body_nodes[cover_block_count];core.ensure(core.ensure(first_body,'pPr'),'pageBreakBefore',core.P_ORDER).set(core.Q('val'),'1')
    # Native cover keep chain is part of newly authored layout, never applied to existing user files.
    cover_ps=[n for n in body_nodes[:cover_block_count] if n.tag==core.Q('p')]
    for node in body_nodes[:cover_block_count]:
        for pp in ([node] if node.tag==core.Q('p') else list(node.iter(core.Q('p')))):
            pr=core.ensure(pp,'pPr');core.ensure(pr,'keepLines',core.P_ORDER).set(core.Q('val'),'1')
            if pp is not cover_ps[-1]:core.ensure(pr,'keepNext',core.P_ORDER).set(core.Q('val'),'1')
    parts['word/document.xml']=E.tostring(d,xml_declaration=True,encoding='UTF-8',standalone=True);write_zip(out/'composed.docx',parts,infos)
    target=out/'styled.docx';cfg=resolve({'schema_version':'1.0','kind':'style_resolution_request','mode':'create','sources':request.get('style_sources',[]),'document':{'input':str(out/'composed.docx'),'output':str(target)}})
    rolemap={str(i):('title' if pp in cover_ps[:2] else 'body') for i,pp in enumerate(d.iter(core.Q('p'))) if pp.find('w:pPr/w:pStyle',core.NS) is None or not pp.find('w:pPr/w:pStyle',core.NS).get(core.Q('val'),'').startswith('Heading')}
    report=core.format_docx(out/'composed.docx',target,cfg,role_map=rolemap)
    # Only cover-position pPr properties may change after the common formatter.
    parts,infos=core.read_package(target);before=core.snapshot(parts);d=core.parse(parts['word/document.xml']);nodes=[n for n in d.find(core.Q('body')) if n.tag!=core.Q('sectPr')];journal=[]
    for index,node in enumerate(nodes[:cover_block_count]):
        if node.tag!=core.Q('p'):continue
        old=copy.deepcopy(node.find(core.Q('pPr')));pr=core.ensure(node,'pPr');core.ensure(pr,'jc',core.P_ORDER).set(core.Q('val'),'center')
        ind=core.ensure(pr,'ind',core.P_ORDER)
        for attr in ['firstLine','hanging','hangingChars']:ind.attrib.pop(core.Q(attr),None)
        ind.set(core.Q('firstLineChars'),'0')
        gap=p['cover_layout']['top_gap_pt'] if index==0 else p['cover_layout']['date_gap_pt'] if node is nodes[cover_block_count-1] else p['cover_layout']['field_gap_pt']
        core.ensure(pr,'spacing',core.P_ORDER).set(core.Q('before'),str(round(gap*20)));journal.append((index,old))
    after=copy.deepcopy(d)
    for index,old in journal:
        node=[n for n in after.find(core.Q('body')) if n.tag!=core.Q('sectPr')][index];node.remove(node.find(core.Q('pPr')))
        if old is not None:node.insert(0,old)
    if core.canonical(after)!=core.canonical(core.parse(parts['word/document.xml'])):raise ValueError('Unexpected non-cover-layout change')
    parts['word/document.xml']=E.tostring(d,xml_declaration=True,encoding='UTF-8',standalone=True)
    fidelity=core.compare_snapshots(before,core.snapshot(parts))
    if not fidelity['passed']:raise ValueError('Cover content fidelity failed')
    fd,tmp=tempfile.mkstemp(dir=out,suffix='.pending');os.close(fd)
    try:
        write_zip(tmp,parts,infos);core.read_package(tmp);os.link(tmp,out/'report.docx')
    finally:Path(tmp).unlink(missing_ok=True)
    for name,value in [('plan.json',p),('effective-style.json',cfg),('formatting-report.json',report),('cover-layout-proof.json',{'inverse_layout_only':True,'content_fidelity':fidelity,'fonts_and_body_styles_unchanged':True,'original_reference_used_as_binary_template':False,'visual_status':'pending_render'})]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return out/'report.docx'

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--request',type=Path,required=True);a.add_argument('--output-dir',type=Path,required=True);args=a.parse_args()
    try:print(build(json.loads(args.request.read_text()),args.output_dir))
    except (ValueError,KeyError,TypeError,subprocess.CalledProcessError) as e:a.exit(1,str(e)+'\n')
if __name__=='__main__':main()
