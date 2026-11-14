#!/usr/bin/env python3
"""Resolve format properties and emit a preview. Never opens a DOCX for writing."""
from workspace_paths import SKILL_ROOT, data_root, output_root, check_input
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from safe_preview import preview_text

ROOT = data_root()
DEFAULTS = SKILL_ROOT/'references/standards/default-style.json'
PRIORITIES = {'teacher_requirements':1, 'teacher_template':2, 'teacher_example':3,
              'user_reference_style':4, 'skill_defaults':5}
RELIABLE = {'verified','explicit','inherited','extracted','theme_resolved','default'}
STATUSES = RELIABLE | {'candidate','unknown'}
PROTECTED = ['body_text','numbers','experimental_data','omml_structure_and_content',
             'reference_content_and_order','image_information_and_media','bookmarks',
             'fields_and_relationships','all_other_nonformat_data']
RESTRICTED = {'caption.figure.numbering','caption.table.numbering','equation.numbering',
              'equation.display','references.citation_style','caption.figure.numbering_format','caption.table.numbering_format','equation.numbering_format'}


def load_json(path):
    path=check_input(path)
    def pairs(items):
        result={}
        for k,v in items:
            if k in result: raise ValueError('Duplicate JSON key: '+k)
            result[k]=v
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite JSON value')))


def number(value):
    if isinstance(value,bool): raise ValueError('Boolean is not a number')
    n=float(value)
    if not math.isfinite(n) or n<0: raise ValueError('Expected finite nonnegative number')
    return n


def normalize(key, value, unit=None):
    """Canonical units are encoded by property name; retain input separately."""
    if key=='equation.tab_stops':
        if unit is not None or not isinstance(value,list) or len(value)!=2:raise ValueError('Equation requires two typed tab stops')
        result=[]
        for tab in value:
            if not isinstance(tab,dict) or set(tab)!={'position','unit','alignment','leader'}:raise ValueError('Invalid tab stop structure')
            if tab['unit']!='char' or tab['leader']!='none' or tab['alignment'] not in ['center','right']:raise ValueError('Tabs require char units, center/right and no leader')
            result.append({**tab,'position':number(tab['position'])})
        if [t['alignment'] for t in result]!=['center','right'] or not 0<result[0]['position']<result[1]['position']:raise ValueError('Invalid equation tab ordering')
        return result
    if key.endswith('.numbering_format'):
        if unit or not isinstance(value,str) or value.count('{n}')!=1 or len(value)>40 or '{' in value.replace('{n}','') or '}' in value.replace('{n}',''):raise ValueError('Number format requires exactly one {n}')
        return value
    if '.font.' in key:
        if unit not in [None,'font_name'] or not isinstance(value,str) or not value.strip():
            raise ValueError('Font must be a nonempty name, without size units')
        return value.strip()
    if key.endswith(('_pt','_cm','_chars')):
        chinese={'五号':10.5,'小四':12,'四号':14,'小三':15,'三号':16,'小二':18,'二号':22}
        if key.endswith('.size_pt') and isinstance(value,str) and value in chinese:
            if unit not in [None,'chinese_size']:raise ValueError('Chinese size with incompatible unit')
            return float(chinese[value])
        if isinstance(value,str):
            match=re.fullmatch(r'\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z_]+)?\s*',value)
            if not match:raise ValueError('Invalid numeric quantity')
            if match[2]:
                if unit and unit!=match[2]:raise ValueError('Conflicting unit declarations')
                unit=match[2]
            value=match[1]
        n=number(value)
        target='pt' if key.endswith('_pt') else 'cm' if key.endswith('_cm') else 'char'
        unit=unit or target
        factors={'pt':{'pt':1,'half_pt':0.5,'twip':0.05,'cm':72/2.54,'mm':72/25.4,'in':72},
                 'cm':{'cm':1,'mm':0.1,'in':2.54,'twip':2.54/1440,'pt':2.54/72},
                 'char':{'char':1,'hundredth_char':0.01}}
        if unit not in factors[target]:raise ValueError('Incompatible unit '+str(unit)+' for '+target)
        n=round(n*factors[target][unit],9)
        if key.endswith('.size_pt') and not 1<=n<=200:raise ValueError('Font size outside 1..200 pt')
        return n
    if key.endswith('.line_spacing'):
        if unit is not None or not isinstance(value,dict) or set(value)!={'rule','value','unit'}:
            raise ValueError('Line spacing requires rule/value/unit object')
        rule=value['rule']
        if rule=='multiple':
            if value['unit']!='multiple':raise ValueError('Multiple line spacing requires multiple unit')
            n=number(value['value'])
        elif rule in ['exact','at_least']:
            n=normalize('spacing_pt',value['value'],value['unit'])
        else:raise ValueError('Unknown line spacing rule')
        if n<=0:raise ValueError('Line spacing must be positive')
        return {'rule':rule,'value':n,'unit':'multiple' if rule=='multiple' else 'pt'}
    if key=='page.size':
        if unit:raise ValueError('Page size units belong inside dimension object')
        if isinstance(value,str) and value in ['A4','Letter']:return value
        if not isinstance(value,dict) or set(value)!={'width','height','unit'}:raise ValueError('Invalid page size')
        dims={k:normalize(k+'_cm',value[k],value['unit']) for k in ['width','height']}
        if not all(1<=v<=100 for v in dims.values()):raise ValueError('Page dimension outside 1..100 cm')
        # Canonical names avoid false conflicts caused by rounded OOXML A4 dimensions.
        if abs(dims['width']-21)<0.01 and abs(dims['height']-29.7)<0.01:return 'A4'
        if abs(dims['width']-21.59)<0.01 and abs(dims['height']-27.94)<0.01:return 'Letter'
        return dims
    if key.endswith(('.bold','.italic')) or key=='equation.preserve_omml':
        if unit:raise ValueError('Boolean cannot have units')
        if isinstance(value,bool):
            if key=='equation.preserve_omml' and not value:raise ValueError('OMML preservation cannot be disabled')
            return value
        if isinstance(value,str) and value in ['true','false','0','1','on','off']:
            converted=value in ['true','1','on']
            if key=='equation.preserve_omml' and not converted:raise ValueError('OMML preservation cannot be disabled')
            return converted
        raise ValueError('Expected explicit boolean')
    if unit:raise ValueError('Unexpected unit for '+key)
    if key.endswith('.color'):
        if value in ['黑色','black']:return '000000'
        if not isinstance(value,str) or not re.fullmatch(r'#?[0-9a-fA-F]{6}',value):raise ValueError('Color must be RGB hex; auto/theme unresolved')
        return value.lstrip('#').upper()
    enums={
        'page.orientation':['portrait','landscape'], 'table.style':['grid','three_line'],
        'equation.display':['standalone','inline','preserve'], 'equation.numbering':['preserve','none','sequential','chapter'],
        'equation.number_position':['left','right'], 'references.citation_style':['numeric','author_year','preserve'],
        'image.resize_policy':['preserve_aspect_ratio'], 'image.max_width':['text_area'],
        'image.quality_policy':['print_clear_vector_or_high_resolution'], 'equation.center_reference':['text_area']}
    if key in ['equation.body_alignment','equation.number_alignment']:options=['left','center','right']
    else:options=enums.get(key)
    if key.endswith('.alignment'):options=['left','right','center','justify']
    if key.endswith('.position'):options=['above','below']
    if key.startswith('caption.') and key.endswith('.numbering'):options=['preserve','none','sequential','chapter']
    if not options or value not in options:raise ValueError('Unsupported value for '+key)
    return value


def extraction_source(data, wrapper):
    """Adapt Phase 3A inventory without re-reading OOXML or promoting candidate roles."""
    if not isinstance(data,dict) or data.get('schema_version')!='1.0' or not isinstance(data.get('profiles'),dict):
        raise ValueError('Unsupported Phase 3A extraction schema')
    integrity=data.get('source',{})
    if not isinstance(integrity,dict) or integrity.get('unchanged') is not True or not re.fullmatch(r'[0-9a-f]{64}',str(integrity.get('sha256_before',''))) or integrity.get('sha256_before')!=integrity.get('sha256_after'):
        raise ValueError('Extraction lacks successful source integrity check')
    props=defaultdict(list)
    def add(k,r,unit=None,role_status=None):
        r=deepcopy(r or {'value':None,'status':'unknown','source':None})
        if r.get('status') not in STATUSES:raise ValueError('Unknown extraction status')
        r.setdefault('original_status',r['status'])
        if role_status=='candidate' and r['status']!='unknown':r['status']='candidate'
        if unit:r['unit']=unit
        if not r.get('source'):r['source']='Phase 3A: missing attribute '+k
        props[k].append(r)
    sections=data.get('pages',[])
    for sec in sections:
        for edge,r in sec.get('margins',{}).items():
            if edge in ['top','bottom','left','right']:add('page.margin.'+edge+'_cm',r,'twip')
            if edge in ['header','footer']:add('page.'+edge+'_distance_cm',r,'twip')
        page=sec.get('page',{})
        w,h=page.get('w',{}),page.get('h',{})
        if w.get('value') is not None and h.get('value') is not None:
            add('page.size',{'value':{'width':w['value'],'height':h['value'],'unit':'twip'},'source':w.get('source'),'status':'extracted'})
        add('page.orientation',page.get('orient'))
    paragraphs={p['index']:p for p in data.get('paragraphs',[])}
    mapping={'body':'body','title':'title','heading_1':'heading.1','heading_2':'heading.2','heading_3':'heading.3',
             'figure_caption':'caption.figure','table_caption':'caption.table','reference_entry':'references'}
    for role,prefix in mapping.items():
        profile=data['profiles'].get(role,{'status':'unknown','value':None})
        if not profile.get('value'):
            add(prefix+'.size_pt',{'value':None,'status':'unknown','source':'profiles.'+role})
            continue
        for idx in profile['value'].get('paragraph_indices',[]):
            p=paragraphs.get(idx)
            if p is None:raise ValueError('Profile references nonexistent paragraph')
            pf=p.get('paragraph',{})
            for raw,key,unit in [('jc','alignment',None),('ind.firstLineChars','first_line_chars','hundredth_char'),
                                 ('ind.hanging','hanging_pt','twip'),('spacing.before','space_before_pt','twip'),('spacing.after','space_after_pt','twip')]:
                r=deepcopy(pf.get(raw,{}))
                if raw=='jc' and r.get('value')=='both':r['value']='justify'
                add(prefix+'.'+key,r,unit,profile['status'])
            line,rule=pf.get('spacing.line',{}),pf.get('spacing.lineRule',{})
            if line.get('value') is not None and rule.get('value') in ['auto','exact','atLeast'] and all(r.get('status') in RELIABLE for r in [line,rule]):
                spacing={'rule':{'auto':'multiple','exact':'exact','atLeast':'at_least'}[rule['value']],
                         'value':float(line['value'])/240 if rule['value']=='auto' else line['value'],
                         'unit':'multiple' if rule['value']=='auto' else 'twip'}
                add(prefix+'.line_spacing',{'value':spacing,'source':line['source'],'status':line['status']},role_status=profile['status'])
            else:add(prefix+'.line_spacing',{'value':None,'status':'unknown','source':p.get('source')})
            for run in p.get('runs',[]):
                rf=run.get('format',{})
                for raw,key,unit in [('rFonts.eastAsia','font.eastAsia',None),('rFonts.ascii','font.latin',None),('rFonts.hAnsi','font.latin',None),('sz','size_pt','half_pt'),('color.val','color',None),('b','bold',None),('i','italic',None)]:
                    r=deepcopy(rf.get(raw,{}))
                    if raw=='color.val' and r.get('value')=='auto':
                        r['original_status']=r['status'];r['status']='unknown';r['reason']='automatic OOXML color has no fixed RGB value'
                    add(prefix+'.'+key,r,unit,profile['status'])
    for group, key in [('images','caption.figure.position'),('tables','caption.table.position')]:
        for item in data.get(group,[]):
            relation=item.get('caption_relation',{})
            pos=(relation.get('value') or {}).get('position')
            add(key,{'value':pos,'status':'candidate' if pos else 'unknown','source':relation.get('source') or 'Phase 3A caption relation'})
    # Combine identical records while keeping every source locator and raw status.
    compact={}
    for k,rs in props.items():
        grouped={}
        for r in rs:
            signature=json.dumps([r.get('value'),r['status'],r.get('unit')],sort_keys=True)
            if signature not in grouped:grouped[signature]={**r,'evidence_sources':[], 'extraction_statuses':[]}
            g=grouped[signature]
            if r['source'] not in g['evidence_sources']:g['evidence_sources'].append(r['source'])
            if r['original_status'] not in g['extraction_statuses']:g['extraction_statuses'].append(r['original_status'])
        compact[k]=list(grouped.values())
    return {**wrapper,'properties':compact,'extraction_source':deepcopy(data['source'])}


def finalize_constraints(effective, pending, conflicts, diagnostics, allowed):
    """Resolve mutually exclusive legacy fields before exposing writer operations."""
    def block(keys, reason):
        for key in keys:
            r=effective[key]
            r.update(apply=False, confirmation_required=key in allowed, resolution_status='needs_confirmation')
            if key in allowed and not any(p['property']==key for p in pending):pending.append({'property':key,'reasons':[reason]})
    for canonical, legacy, alias in [('references.hanging_chars','references.hanging_pt',False),
                                      ('equation.body_alignment','equation.alignment',True),
                                      ('equation.number_alignment','equation.number_position',True)]:
        a,b=effective[canonical],effective[legacy]
        keys=[canonical,legacy]
        for key,other in [(canonical,b),(legacy,a)]:
            r=effective[key]
            optional=[c for c in r['alternatives'] if c['status']=='candidate' and not c.get('confirmed_by_user') and not c.get('excluded_by_confirmation')]
            frozen_other=other['source_id']=='skill-defaults' and any(c['source_id']=='skill-defaults' and c['raw'].get('default_confirmation',{}).get('status')=='user_confirmed' for c in other['alternatives'])
            if frozen_other and r['status']=='default' and optional and all(c['role']=='user_reference_style' and not c['raw'].get('required') for c in optional) and any(p['property']==key and p['reasons']==['candidate_requires_confirmation'] for p in pending):
                r.update(confirmation_required=False,resolution_status='confirmed_equivalent_default')
                pending[:]=[p for p in pending if p['property']!=key]
                diagnostics.append({'kind':'confirmed_equivalent_default','property':key,'reason':'Confirmed canonical default supersedes optional legacy reference candidate'})
        if any(r['status'] in ['invalid','conflict'] or r['confirmation_required'] for r in [a,b]):
            block(keys,'unresolved_equivalent_property');continue
        pa,pb=a['priority'],b['priority']
        if pa is None or pb is None:continue
        prefer_new=pa<pb or pa==pb and (a['value']==b['value'] and alias or a['source_id']==b['source_id']=='skill-defaults')
        if pa==pb and not prefer_new:
            conflicts.append({'kind':'alias_conflict' if alias else 'incompatible_indent_units','properties':keys,'requires_confirmation':True})
            block(keys,'equivalent_property_conflict');continue
        winner,loser=(canonical,legacy) if prefer_new else (legacy,canonical)
        if alias and winner==legacy and canonical in allowed:
            r=deepcopy(b);r.update(authorized=canonical in allowed,apply=canonical in allowed,alternatives=a['alternatives']+b['alternatives'])
            effective[canonical]=r
            winner,loser=canonical,legacy
        effective[loser].update(apply=False,resolution_status='superseded_equivalent_property',superseded_by=winner)
        diagnostics.append({'kind':'exclusive_property_selection','selected':winner,'suppressed':loser,'reason':'Source priority; character and physical units never guessed equivalent'})
    first=effective['references.first_line_chars']
    for key in ['references.hanging_chars','references.hanging_pt']:
        hanging=effective[key]
        if not hanging['apply'] or not hanging['value']:continue
        if not first['value']:
            first.update(apply=False,resolution_status='neutral_indent_omitted',superseded_by=key)
        elif first['priority']<hanging['priority']:
            hanging.update(apply=False,resolution_status='superseded_equivalent_property',superseded_by='references.first_line_chars')
        elif first['priority']>hanging['priority']:
            first.update(apply=False,resolution_status='superseded_equivalent_property',superseded_by=key)
        else:
            conflicts.append({'kind':'incompatible_indent_directions','properties':['references.first_line_chars',key],'requires_confirmation':True})
            block(['references.first_line_chars',key],'incompatible_indent_directions')
    for key,r in effective.items():
        if key.endswith('.hanging_pt') and r['apply'] and r['value']==0:
            first_key=key[:-len('hanging_pt')]+'first_line_chars'
            first=effective.get(first_key)
            if first and first['value'] and first['status'] not in ['conflict','invalid']:
                r.update(apply=False,resolution_status='neutral_indent_omitted',superseded_by=first_key)
    # A confirmed position in characters is not proof of physical Word geometry.
    keys=['equation.body_alignment','equation.number_alignment','equation.center_reference','equation.tab_stops','equation.alignment','equation.number_position',
          'equation.paragraph.alignment','equation.paragraph.first_line_chars','equation.paragraph.line_spacing',
          'equation.paragraph.space_before_pt','equation.paragraph.space_after_pt']
    active=[k for k in keys if effective[k]['apply']]
    if not active:return []
    for key in active:effective[key].update(apply=False,resolution_status='needs_layout_validation')
    return [{'kind':'equation_geometry','properties':active,'reason':'Validate character tabs against text-area width, font metrics, paragraph indents, rendered OMML center and number right edge; no fixed conversion'}]


def resolve(request, base_dir=ROOT):
    request=deepcopy(request)
    if not isinstance(request,dict) or request.get('schema_version')!='1.0' or request.get('kind')!='style_resolution_request':raise ValueError('Request requires schema_version 1.0')
    if set(request)-{'schema_version','kind','mode','sources','allowed_properties','document','confirmations'}:raise ValueError('Unrecognized request field')
    mode=request.get('mode','create')
    if mode not in ['create','modify','format_only']:raise ValueError('Invalid operation mode')
    defaults=load_json(DEFAULTS)
    known=set(defaults['properties']) | {'table.cell.'+suffix for suffix in ['alignment','first_line_chars','line_spacing','space_before_pt','space_after_pt']}
    scopes=request.get('allowed_properties',None)
    if scopes is not None and (not isinstance(scopes,list) or any(not isinstance(s,str) or not (s in known or s.endswith('.*') and any(k.startswith(s[:-1]) for k in known) or s=='*') for s in scopes)):
        raise ValueError('Invalid authorized property scope')
    if scopes is None:scopes=[] if mode=='modify' else ['*']
    allowed={k for k in known if any(s=='*' or k==s or s.endswith('.*') and k.startswith(s[:-1]) for s in scopes)}
    if mode!='create':allowed-=RESTRICTED
    sources=request.get('sources',[])
    if not isinstance(sources,list):raise ValueError('sources must be a list')
    sources.append(defaults)
    choices=defaultdict(list);diagnostics=[];inputs=[];ids=set()
    for source in sources:
        if not isinstance(source,dict):raise ValueError('Each source must be an object')
        if source.get('schema_version','1.0')!='1.0':raise ValueError('Unsupported source schema version')
        if set(source)-{'schema_version','kind','id','role','source','properties','extraction','priority'}:raise ValueError('Unrecognized source field')
        sid,role,attribution=source.get('id'),source.get('role'),source.get('source')
        if not isinstance(sid,str) or not sid.strip() or sid in ids:raise ValueError('Missing or duplicate source id')
        ids.add(sid)
        if role not in PRIORITIES or not isinstance(attribution,str) or not attribution.strip():raise ValueError('Ambiguous source authority or attribution')
        if 'priority' in source and source['priority']!=PRIORITIES[role]:raise ValueError('Priority must agree with source role')
        if role=='skill_defaults' and sid!='skill-defaults':raise ValueError('Custom inputs cannot impersonate built-in defaults')
        if source.get('extraction'):
            if 'properties' in source:raise ValueError('Source cannot specify both extraction and properties')
            path=(Path(base_dir)/source['extraction']).resolve()
            data=load_json(path)
            source=extraction_source(data,source)
            inputs.append({'id':sid,'role':role,'file':str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'original_source':data.get('source')})
        else:inputs.append({'id':sid,'role':role,'source':attribution})
        props=source.get('properties')
        if not isinstance(props,dict):raise ValueError('Source properties must be an object')
        for key,items in props.items():
            if isinstance(items,list) and not items:raise ValueError('Empty property alternatives: '+key)
            if key not in known:raise ValueError('Unsupported/non-format property: '+key)
            for item in items if isinstance(items,list) else [items]:
                if not isinstance(item,dict) or 'value' not in item or item.get('status') not in STATUSES or not isinstance(item.get('source'),str) or not item['source'].strip():
                    raise ValueError('Property requires value/status/source: '+key)
                if item['status']=='default' and role!='skill_defaults':raise ValueError('default status reserved for built-in defaults')
                c={'source_id':sid,'role':role,'priority':PRIORITIES[role], 'raw':deepcopy(item),'status':item['status'],'source':item['source'],'value':None}
                if item['status']=='unknown':
                    c['reason']='unverified_value_not_used'
                else:
                    try:c['value']=normalize(key,item['value'],item.get('unit'))
                    except (ValueError,TypeError,OverflowError) as e:
                        c['status']='invalid';c['reason']=str(e)
                        diagnostics.append({'kind':'invalid_parameter','property':key,'source_id':sid,'message':str(e),'category':'unit_inconsistency' if 'unit' in str(e).lower() else 'invalid_value'})
                choices[key].append(c)
        if role!='skill_defaults':
            missing=sorted({'page.size','body.font.eastAsia','body.font.latin','body.size_pt'}-set(props))
            if missing:diagnostics.append({'kind':'missing_parameters','source_id':sid,'properties':missing,'message':'Partial source; lower levels may fill absent properties'})
    confirmations=request.get('confirmations',[])
    if not isinstance(confirmations,list):raise ValueError('confirmations must be a list')
    seen_confirmations=set()
    for confirmation in confirmations:
        if not isinstance(confirmation,dict) or confirmation.get('confirmed_by')!='user' or not isinstance(confirmation.get('reason'),str) or not confirmation['reason'].strip():raise ValueError('Confirmation requires explicit user attribution and reason')
        key,sid=confirmation.get('property'),confirmation.get('source_id')
        if key not in known or (key,sid) in seen_confirmations:raise ValueError('Invalid/duplicate confirmation')
        seen_confirmations.add((key,sid))
        value=normalize(key,confirmation.get('value'),confirmation.get('unit'))
        selected_candidates=[c for c in choices[key] if c['source_id']==sid and c['status']=='candidate' and c['value']==value]
        if not selected_candidates:raise ValueError('Confirmation does not match an existing candidate')
        for c in choices[key]:
            if c['source_id']==sid and c['status']=='candidate':
                c['confirmed_by_user']=c['value']==value
                c['excluded_by_confirmation']=c['value']!=value
                c['confirmation_reason']=confirmation['reason']
    effective={};pending=[];conflicts=[]
    for key,options in sorted(choices.items()):
        usable=[c for c in options if c['status'] in RELIABLE or c.get('confirmed_by_user')]
        best=min((c['priority'] for c in usable),default=6)
        at_best=[c for c in usable if c['priority']==best]
        distinct={json.dumps(c['value'],sort_keys=True) for c in at_best}
        invalid=[c for c in options if c['status']=='invalid' and c['priority']<=best]
        candidates=[c for c in options if c['status']=='candidate' and not c.get('confirmed_by_user') and not c.get('excluded_by_confirmation') and c['priority']<=best]
        frozen=next((c for c in at_best if c['source_id']=='skill-defaults' and c['raw'].get('default_confirmation',{}).get('status')=='user_confirmed'),None)
        bypassed=[c for c in candidates if frozen and c['role']=='user_reference_style' and not c['raw'].get('required')]
        for c in bypassed:
            c['nonblocking_reason']='user_confirmed_skill_default_for_optional_reference_candidate'
        candidates=[c for c in candidates if c not in bypassed]
        if bypassed:diagnostics.append({'kind':'confirmed_default_used','property':key,'reason':'Explicitly frozen default; optional reference candidate retains raw status','source_ids':sorted({c['source_id'] for c in bypassed})})
        unresolved_unknown=[c for c in options if c['status']=='unknown' and (c['raw'].get('required') or c['role']=='teacher_requirements') and c['priority']<=best]
        selected=at_best[0] if at_best and len(distinct)==1 and not invalid else None
        state='conflict' if len(distinct)>1 else 'invalid' if invalid else selected['status'] if selected else 'unknown'
        block=bool(len(distinct)>1 or invalid or candidates or unresolved_unknown)
        if len(distinct)>1:
            conflicts.append({'kind':'same_priority_conflict','property':key,'priority':best,'candidates':at_best,'requires_confirmation':True})
        if selected:
            lower=[c for c in usable if c['priority']>best and c['value']!=selected['value']]
            if lower:conflicts.append({'kind':'priority_override','property':key,'winner':selected['source_id'],'overridden':[c['source_id'] for c in lower],'requires_confirmation':False})
        if len({json.dumps(c['value'],sort_keys=True) for c in candidates})>1:
            conflicts.append({'kind':'candidate_disagreement','property':key,'source_ids':sorted({c['source_id'] for c in candidates}),'requires_confirmation':True})
        if candidates:
            diagnostics.append({'kind':'candidate_not_applied','property':key,'source_ids':sorted({c['source_id'] for c in candidates})})
        if block and key in allowed:
            pending.append({'property':key,'reasons':([state] if state in ['conflict','invalid'] else [])+(['candidate_requires_confirmation'] if candidates else [])+(['required_unknown'] if unresolved_unknown else [])})
        effective[key]={'value':None if selected is None else selected['value'],'source':None if selected is None else selected['source'],
                        'source_id':None if selected is None else selected['source_id'],'priority':None if selected is None else selected['priority'],
                        'status':state,'resolution_status':'confirmed_default' if frozen and not block else 'confirmed_by_user' if selected and selected.get('confirmed_by_user') else 'needs_confirmation' if block else 'resolved','authorized':key in allowed,'apply':key in allowed and not block and selected is not None,
                        'confirmation_required':block and key in allowed,'alternatives':deepcopy(options)}
    pending_validation=finalize_constraints(effective,pending,conflicts,diagnostics,allowed)
    documents=request.get('document',{})
    if not isinstance(documents,dict) or any(k not in ['input','output'] for k in documents):raise ValueError('document accepts input/output paths only')
    paths={}
    for key in ['input','output']:
        raw=documents.get(key)
        if raw is not None and (not isinstance(raw,str) or not raw):raise ValueError('Document paths must be strings or null')
        paths[key]=str((Path(base_dir)/raw).resolve()) if raw else None
    if paths['input'] and paths['output'] and paths['input']==paths['output']:raise ValueError('Input/output documents must differ')
    if paths['output']:
        target=Path(paths['output'])
        if not target.is_relative_to(ROOT) or target.suffix.lower()!='.docx' or target.exists():
            raise ValueError('Future output must be a new DOCX path within project')
    future={'input_path':paths['input'],'output_path':paths['output'],'effective_style':{k:v for k,v in effective.items() if v['apply']},
            'allowed_properties':sorted(allowed),'protected_content':PROTECTED,
            'unresolved_conflicts':pending,'expected_validation':['source_hash','original_unchanged','content_equivalence_including_omml_images_fields','authorized_properties_only','style_xml_checks','visual_check_or_explicitly_unverified'],
            'ready_for_writer':not pending and not pending_validation and bool(allowed) and bool(paths['input'] and paths['output']),
            'write_performed':False,'source_docx_sha256':None,
            'contract_version':'1.2','required_capabilities':['typed_character_indents','independent_heading_styles','equation_geometry_validation'],
            'pending_validation':pending_validation,
            'font_mapping':{'eastAsia':'w:rFonts/@w:eastAsia','latin':['w:rFonts/@w:ascii','w:rFonts/@w:hAnsi']},
            'indent_policy':{'character_storage':'hundredths_of_character','character_to_physical_conversion':'forbidden_without_document_metrics','remove_conflicting_indent_attributes':True,'legacy_hanging_pt':'retained_in_audit_only_when_character_field_selected'},
            'semantic_styles':{'title':'Title','heading.1':'Heading1','heading.2':'Heading2','heading.3':'Heading3'},
            'layout_requirements':{'equation':{'center_reference':'entire_text_area','number_reference':'text_area_right_edge','character_to_physical_conversion':'requires_document_metrics_and_render_verification','preserve_editable_omml':True,'on_geometry_conflict':'block_and_report'}},
            'expected_validation_extended':['character_indent_units_and_exclusivity','formula_center_vs_entire_text_area','formula_number_at_text_right_edge','omml_editability_and_structure','image_aspect_ratio_and_text_area_width']}
    # No DOCX interpretation here: optional bytes-only hash for a future input.
    if paths['input']:
        p=Path(paths['input'])
        if not p.is_file():raise ValueError('Input document does not exist')
        if p.suffix.lower()!='.docx':raise ValueError('Input document must be DOCX')
        future['source_docx_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    return {'schema_version':'1.0','kind':'effective_style','resolver_version':'1.2','mode':mode,
            'effective_properties':effective,'apply_properties':{k:v for k,v in effective.items() if v['apply']},
            'allowed_properties':sorted(allowed),'protected_content':PROTECTED,'sources':inputs,
            'pending_validation':pending_validation,'confirmations':confirmations,'conflicts':conflicts,'diagnostics':diagnostics,'pending_confirmation':pending,'writer_contract':future,'write_performed':False}


def preview(config):
    def cell(v):return preview_text(v, 'table')
    lines=['# 排版配置预览','', '仅配置合并，未修改 Word 文件。候选与 unknown 保留在 alternatives，待确认属性不进入 apply_properties。',
           '',f"模式：{preview_text(config['mode'])}；可执行属性：{len(config['apply_properties'])}；待确认：{len(config['pending_confirmation'])}。",'',
           '| 属性 | 最终设置（或预览回退值） | 来源 | 状态 | 可执行 |','| --- | --- | --- | --- | --- |']
    for k,r in config['effective_properties'].items():
        lines.append('| '+' | '.join(cell(v) for v in [k,r['value'],r['source_id'] or '未确定',r['status']+' / '+r['resolution_status']+('；待确认' if r['confirmation_required'] else ''),r['apply']])+' |')
    lines+=['','来源统计（按最终预览选择；可执行性另看表格）：','']
    for role in PRIORITIES:
        keys=[k for k,r in config['effective_properties'].items() if r['source_id'] and any(s['id']==r['source_id'] and s['role']==role for s in config['sources'])]
        lines.append(f'- {role}：{len(keys)} 项。')
    lines+=['','冲突与覆盖：','']
    for c in config['conflicts']:lines.append('- '+preview_text(c))
    if not config['conflicts']:lines.append('- 无已解析值冲突。')
    lines+=['','待确认：','']
    for p in config['pending_confirmation']:lines.append('- '+preview_text(p))
    if not config['pending_confirmation']:lines.append('- 无。')
    lines+=['','未确定及输入诊断：','']
    for k,r in config['effective_properties'].items():
        uncertain=[{'source_id':a['source_id'],'status':a['status'],'value':a['raw']['value']} for a in r['alternatives'] if a['status'] in ['candidate','unknown','invalid']]
        if uncertain:lines.append('- '+preview_text(k)+'：'+preview_text(uncertain))
    for d in config['diagnostics']:lines.append('- '+preview_text(d))
    lines+=['','待布局验证：','']
    for item in config.get('pending_validation',[]):lines.append('- '+preview_text(item))
    lines+=['','写入接口：仅定义，未实现；输入/输出路径及待确认未齐备时 ready_for_writer=false。','']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--preview',type=Path,required=True)
    args=parser.parse_args()
    try:
        outputs=[args.output.resolve(),args.preview.resolve()]
        if outputs[0]==outputs[1] or any(not p.is_relative_to(ROOT) or p.exists() for p in outputs):raise ValueError('Outputs must be distinct, new project files')
        if outputs[0].suffix!='.json' or outputs[1].suffix!='.md':raise ValueError('Output suffixes must be .json and .md')
        config=resolve(load_json(args.request),args.request.resolve().parent)
        for p in outputs:p.parent.mkdir(parents=True,exist_ok=True)
        with outputs[0].open('x',encoding='utf-8') as f:json.dump(config,f,ensure_ascii=False,indent=2,allow_nan=False)
        with outputs[1].open('x',encoding='utf-8') as f:f.write(preview(config))
        print(f"Resolved {len(config['effective_properties'])} properties; {len(config['pending_confirmation'])} pending; no DOCX write.")
    except (ValueError,OSError,TypeError,KeyError,AttributeError,IndexError) as e:parser.exit(1,f'Configuration error: {e}\n')

if __name__=='__main__':main()
