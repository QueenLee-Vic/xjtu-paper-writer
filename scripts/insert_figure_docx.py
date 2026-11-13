#!/usr/bin/env python3
"""Insert explicitly authorized figures; verify exact authorized additions before atomic publication."""
from workspace_paths import SKILL_ROOT, data_root, output_root, publish_text
import argparse
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import re
import tempfile
from zipfile import ZipFile
from lxml import etree as E
from PIL import Image
import format_docx as core
from figure_plan import ROOT, file_evidence

OUT=output_root('figures')
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PK='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
WP='http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
PIC='http://schemas.openxmlformats.org/drawingml/2006/picture'
Q=core.Q;NS=core.NS

def node_hash(node):return core.digest(E.tostring(node,method='c14n',exclusive=True))
def child(parent,tag,attrs=None,text=None):
    e=E.SubElement(parent,tag,attrs or {})
    if text is not None:e.text=text
    return e

def anchor_index(d,position):
    body=d.find(Q('body'));ps=body.findall(Q('p'));kind=position.get('kind');value=position.get('value')
    if kind=='paragraph_index':
        if type(value)is not int or not 0<=value<len(ps):raise ValueError('Invalid direct-body paragraph index')
        matches=[ps[value]]
    elif kind=='paragraph_id':matches=[p for p in ps if p.get('{http://schemas.microsoft.com/office/word/2010/wordml}paraId')==value]
    elif kind=='bookmark':matches=[p for p in ps if any(e.get(Q('name'))==value for e in p.iter(Q('bookmarkStart')))]
    elif kind=='exact_reference':matches=[p for p in ps if ''.join(p.itertext())==value]
    elif kind=='section_end':
        styles=position.get('_styles');levels={}
        for s in styles.findall(Q('style')):
            outline=s.find('w:pPr/w:outlineLvl',NS);name=s.find(Q('name'))
            if outline is not None:levels[s.get(Q('styleId'))]=int(outline.get(Q('val')))
            elif name is not None and re.fullmatch(r'heading\s+[1-3]',name.get(Q('val'),'').lower()):levels[s.get(Q('styleId'))]=int(name.get(Q('val'))[-1])-1
        def level(p):
            sid=p.find('w:pPr/w:pStyle',NS);return levels.get(sid.get(Q('val'))) if sid is not None else None
        headings=[p for p in ps if ''.join(p.itertext())==value and level(p) is not None]
        if len(headings)!=1:raise ValueError('Section heading is ambiguous or lacks semantic style')
        p=headings[0];index=body.index(p)+1
        while index<len(body) and body[index].tag!=Q('sectPr') and not (body[index].tag==Q('p') and level(body[index]) is not None and level(body[index])<=level(p)):index+=1
        return index
    else:raise ValueError('Use explicit paragraph_index, paragraph_id, bookmark, exact_reference or section_end')
    if len(matches)!=1:raise ValueError('Insertion position is not unique')
    p=matches[0]
    if core.dangerous(p):raise ValueError('Cannot insert adjacent to complex reference container')
    if p.find('w:pPr/w:sectPr',NS) is not None:raise ValueError('Section boundary requires a different explicit anchor')
    return body.index(p)+1

def caption_paragraph(parts,config,text):
    if not isinstance(text,str) or not text.strip() or len(text)>1000 or any(ord(c)<32 for c in text):raise ValueError('Invalid caption')
    d=E.Element(Q('document'),nsmap={'w':core.W});b=child(d,Q('body'));p=child(b,Q('p'));r=child(p,Q('r'));child(r,Q('t'),text=text)
    mini=dict(parts);mini['word/document.xml']=E.tostring(d)
    scope=[k for k in config.get('allowed_properties',[]) if k.startswith('caption.figure.')]
    needed={'caption.figure.font.eastAsia','caption.figure.font.latin','caption.figure.size_pt','caption.figure.alignment','caption.figure.line_spacing','caption.figure.space_before_pt','caption.figure.space_after_pt'}
    if not needed<=set(scope):raise ValueError('Caption format scope incomplete')
    if config['effective_properties'].get('caption.figure.position',{}).get('value')!='below':raise ValueError('Only below-image captions supported by this insertion operation')
    for key in needed:
        item=config['effective_properties'][key]
        if not item.get('apply') or item.get('confirmation_required') or not item.get('authorized'):raise ValueError('Caption style unresolved/unauthorized')
    changed,report=core.format_package(mini,config,scope=scope,role_map={'0':'caption.figure'})
    p=deepcopy(core.parse(changed['word/document.xml']).find('w:body/w:p',NS))
    styles=core.parse(parts['word/styles.xml']);dedicated=[];generic=[]
    for style in styles.findall(Q('style')):
        name=style.find(Q('name'));name=name.get(Q('val'),'').lower() if name is not None else ''
        if name in ['figure caption','figcaption','图题']:dedicated.append(style)
        elif name in ['caption','题注']:generic.append(style)
    choices=dedicated or generic
    if len(choices)==1 and choices[0].find('w:pPr/w:numPr',NS) is None:
        core.ensure(core.ensure(p,'pPr'),'pStyle',core.P_ORDER).set(Q('val'),choices[0].get(Q('styleId')))
    core.ensure(core.ensure(p,'pPr'),'keepLines',core.P_ORDER).set(Q('val'),'1')
    return p,report['applied_properties']

def image_paragraph(data,rid,width_cm,doc_id,name,alignment):
    with Image.open(io.BytesIO(data)) as image:w,h=image.size;image.verify()
    if w<=0 or h<=0 or w*h>40_000_000:raise ValueError('Invalid/oversized raster')
    cx=round(width_cm*360000);cy=round(cx*h/w)
    p=E.Element(Q('p'));pr=core.ensure(p,'pPr')
    for tag,val in [('keepNext','1'),('keepLines','1'),('jc',alignment)]:core.ensure(pr,tag,core.P_ORDER).set(Q('val'),val)
    core.ensure(pr,'spacing',core.P_ORDER).attrib.update({Q('before'):'0',Q('after'):'0',Q('line'):'240',Q('lineRule'):'auto'})
    drawing=child(child(p,Q('r')),Q('drawing'))
    inline=child(drawing,'{'+WP+'}inline',{'distT':'0','distB':'0','distL':'0','distR':'0'})
    child(inline,'{'+WP+'}extent',{'cx':str(cx),'cy':str(cy)});child(inline,'{'+WP+'}docPr',{'id':str(doc_id),'name':name})
    graphic=child(inline,'{'+A+'}graphic');gd=child(graphic,'{'+A+'}graphicData',{'uri':PIC});pic=child(gd,'{'+PIC+'}pic')
    nv=child(pic,'{'+PIC+'}nvPicPr');child(nv,'{'+PIC+'}cNvPr',{'id':'0','name':name});child(nv,'{'+PIC+'}cNvPicPr')
    fill=child(pic,'{'+PIC+'}blipFill');child(fill,'{'+A+'}blip',{'{'+R+'}embed':rid});child(child(fill,'{'+A+'}stretch'),'{'+A+'}fillRect')
    sp=child(pic,'{'+PIC+'}spPr');tr=child(sp,'{'+A+'}xfrm');child(tr,'{'+A+'}off',{'x':'0','y':'0'});child(tr,'{'+A+'}ext',{'cx':str(cx),'cy':str(cy)})
    child(child(sp,'{'+A+'}prstGeom',{'prst':'rect'}),'{'+A+'}avLst')
    return p,{'cx':cx,'cy':cy,'original_pixels':[w,h]}

def verify_additions(original,actual,journal):
    restored=dict(actual);d=core.parse(actual['word/document.xml']);b=d.find(Q('body'))
    for item in sorted(journal,key=lambda i:i['body_index'],reverse=True):
        index=item['body_index']
        pair=list(b)[index:index+2]
        if len(pair)!=2 or [node_hash(p) for p in pair]!=item['block_hashes']:raise ValueError('Authorized figure blocks were changed/moved')
        for p in pair:b.remove(p)
    # Exact canonical restoration catches all old text, formatting, objects and ordering.
    if core.canonical(d)!=core.canonical(core.parse(original['word/document.xml'])):raise ValueError('Unauthorized document change')
    restored['word/document.xml']=original['word/document.xml']
    relpart='word/_rels/document.xml.rels';rels=core.parse(actual[relpart]);types=core.parse(actual['[Content_Types].xml'])
    for item in journal:
        nodes=[e for e in rels if e.get('Id')==item['relationship_id']]
        if len(nodes)!=1 or node_hash(nodes[0])!=item['relationship_hash']:raise ValueError('Unexpected added relationship')
        rels.remove(nodes[0]);media=item['media_part']
        if core.digest(restored.pop(media,b''))!=item['image_sha256']:raise ValueError('New image changed')
        entry=[e for e in types if e.get('PartName')=='/'+media]
        if len(entry)!=1 or node_hash(entry[0])!=item['content_type_hash']:raise ValueError('Unexpected added content type')
        types.remove(entry[0])
    if relpart in original:
        if core.canonical(rels)!=core.canonical(core.parse(original[relpart])):raise ValueError('Original relationships changed')
        restored[relpart]=original[relpart]
    else:
        if len(rels):raise ValueError('Unexpected relations')
        restored.pop(relpart)
    if core.canonical(types)!=core.canonical(core.parse(original['[Content_Types].xml'])):raise ValueError('Original content types changed')
    restored['[Content_Types].xml']=original['[Content_Types].xml']
    if set(restored)!=set(original) or any(restored[k]!=v for k,v in original.items()):raise ValueError('Unauthorized package part change')
    result=core.compare_snapshots(core.snapshot(original),core.snapshot(restored))
    if not result['passed']:raise ValueError('Original snapshot fidelity failed')
    return {**result,'authorized_additions':len(journal),'exact_original_package_restoration':True,'original_media_and_relationships':'unchanged','visual_verification':'pending_renderer_review'}

def insert_figures(input_path,output_path,manifest,request,config):
    inp=Path(input_path).resolve();out=Path(output_path).resolve()
    if not inp.is_relative_to(ROOT) or inp==out or out.exists() or not any(out.is_relative_to(p) for p in [OUT,output_root('workflow')]) or out.suffix.lower()!='.docx':raise ValueError('New DOCX within an authorized workspace output root; never overwrite inputs')
    if request.get('schema_version')!='1.0' or request.get('mode') not in ['create','modify']:raise ValueError('Insertion forbidden in format_only or unknown mode')
    if config.get('mode')=='format_only':raise ValueError('Style contract format_only cannot authorize new content')
    if request.get('source_docx_sha256')!=core.digest(inp.read_bytes()):raise ValueError('Bind authorization to exact input DOCX hash')
    contract=config.get('writer_contract',{})
    if contract.get('input_path') and Path(contract['input_path']).resolve()!=inp:raise ValueError('Style contract input differs')
    if contract.get('output_path') and Path(contract['output_path']).resolve()!=out:raise ValueError('Style contract output differs')
    if contract.get('source_docx_sha256') and contract['source_docx_sha256']!=request['source_docx_sha256']:raise ValueError('Style contract source hash differs')
    parts,infos=core.read_package(inp);source_hash=core.digest(inp.read_bytes());d=core.parse(parts['word/document.xml']);body=d.find(Q('body'))
    if any(e.tag==Q('documentProtection') and e.get(Q('enforcement'),'1') not in ['0','false'] for e in core.parse(parts.get('word/settings.xml',b'<settings/>')).iter()):raise ValueError('Protected document requires explicit unlock outside insertion')
    original_media_validation=[]
    for name,data in parts.items():
        if name.startswith('word/media/'):
            state='not_raster_or_unsupported_preserved'
            if Path(name).suffix.lower() in ['.png','.jpg','.jpeg','.gif','.bmp','.tif','.tiff']:
                try:
                    with Image.open(io.BytesIO(data)) as im:im.verify()
                    state='raster_decode_check_passed'
                except Exception:state='raster_decode_failed_original_preserved_visual_risk'
            original_media_validation.append({'part':name,'sha256':core.digest(data),'status':state})
    records=manifest.get('figures') if 'figures' in manifest else [manifest]
    if not isinstance(records,list) or len({r.get('image_id') for r in records})!=len(records):raise ValueError('Invalid/duplicate manifest IDs')
    by={r['image_id']:r for r in records};specs=request.get('insertions',[])
    if not isinstance(specs,list) or not 1<=len(specs)<=20 or len({s.get('image_id') for s in specs})!=len(specs):raise ValueError('Unique explicit insertion list required')
    # SEQ fields/complex numbering need a field-aware numbering engine, not a guessed counter.
    if any('SEQ' in (e.text or '').upper() and re.search(r'图|FIGURE',e.text or '',re.I) for e in d.iter(Q('instrText'))) or any('SEQ' in e.get(Q('instr'),'').upper() for e in d.iter(Q('fldSimple'))):raise ValueError('Complex caption numbering field: safe numbering unavailable')
    captions=[''.join(p.itertext()) for p in d.iter(Q('p'))];numbers=[]
    for t in captions:
        if re.match(r'^\s*图\s*\d+[-.．]',t):raise ValueError('Unsupported existing chapter-based numbering scheme')
        m=re.match(r'^\s*图\s*(\d+)(?=\s|[^\d-]|$)',t)
        if m:numbers.append(int(m[1]))
        elif re.match(r'^\s*(图\s*[\d一二三四五六七八九十]+[-.．]|Fig(?:ure)?\s*\d)',t,re.I):raise ValueError('Unsupported existing numbering scheme')
    if len(set(numbers))!=len(numbers):raise ValueError('Existing duplicate figure numbers require confirmation')
    numbering=config.get('effective_properties',{}).get('caption.figure.numbering',{}).get('value')
    number_format=config.get('effective_properties',{}).get('caption.figure.numbering_format',{}).get('value')
    if numbering!='sequential' or number_format!='图{n}':raise ValueError('Only verified sequential 图{n} numbering supported; teacher override needs compatible adapter')
    next_number=max(numbers,default=0)+1
    relpart='word/_rels/document.xml.rels';rels=core.parse(parts[relpart]) if relpart in parts else E.Element('{'+PK+'}Relationships',nsmap={None:PK});types=core.parse(parts['[Content_Types].xml'])
    doc_ids=[int(e.get('id')) for e in d.iter('{'+WP+'}docPr') if (e.get('id') or '').isdigit()];doc_id=max(doc_ids,default=0)+1
    prepared=[];journal=[];changed=dict(parts)
    for order,spec in enumerate(specs):
        fid=spec.get('image_id');record=by.get(fid);marker='xjtu_figure_'+core.digest(str(fid).encode())[:16]
        if not record or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,39}',fid or ''):raise ValueError('Unknown figure ID')
        if fid not in request.get('authorized_image_ids',[]) or spec.get('authorized') is not True or spec.get('needed') is not True or spec.get('quality_approved') is not True or not spec.get('quality_review_basis'):raise ValueError('Need explicit per-image authorization, necessity and quality review')
        if any(e.get('name')==marker for e in d.iter('{'+WP+'}docPr')):raise ValueError('Figure already inserted; no duplicate rerun')
        interface=record.get('docx_interface',{});path=(ROOT/interface.get('image_path','')).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or path.suffix.lower() not in ['.png','.jpg','.jpeg']:raise ValueError('Use checked PNG/JPEG; retain SVG source separately')
        data=path.read_bytes();ext='png' if path.suffix.lower()=='.png' else 'jpeg'
        if record.get('output_hashes',{}).get('png' if ext=='png' else 'jpeg')!=core.digest(data):raise ValueError('Image hash absent/mismatch')
        if not record.get('source_reference'):raise ValueError('Missing knowledge/data/material source')
        kind=record.get('image_type')
        if kind=='A' and record.get('status')!='generated_schematic':raise ValueError('Schematic not generated/registered')
        elif kind=='B':
            evidence=file_evidence(record.get('source_file'))
            if not evidence.get('present') or evidence['sha256']!=record.get('source_hash') or not record.get('verification_status',{}).get('structure_valid'):raise ValueError('Data source changed/unvalidated')
            if record.get('source_type')=='synthetic_test_data' and request.get('allow_synthetic_test_data') is not True:raise ValueError('Test charts cannot be used as experiment results')
        elif kind in ['C','D']:
            evidence=file_evidence(record.get('source_path'))
            if not evidence.get('present') or evidence['sha256']!=core.digest(data) or record.get('source_evidence',{}).get('sha256')!=evidence['sha256']:raise ValueError('Original material hash mismatch')
            if kind=='C' and record.get('status')!='material_registered_authenticity_unverified':raise ValueError('Actual experiment material required')
            if kind=='D' and (record.get('status')!='reference_registered_permission_attested_not_verified' or record.get('permission_status')!='attested_not_independently_verified'):raise ValueError('External image citation/permission required')
        elif kind not in ['A','B']:raise ValueError('Unsupported image type')
        position={**spec.get('position',{}),'_styles':core.parse(parts['word/styles.xml'])};index=anchor_index(d,position)
        section=next((sec for element in list(body)[index:] for sec in element.iter(Q('sectPr'))),None)
        if section is None:raise ValueError('Missing explicit section page geometry')
        pg=section.find(Q('pgSz'));mar=section.find(Q('pgMar'));cols=section.find(Q('cols'))
        if pg is None or mar is None or cols is not None and int(cols.get(Q('num'),'1'))!=1:raise ValueError('Unsupported/missing section geometry')
        width_tw=int(pg.get(Q('w')))-int(mar.get(Q('left')))-int(mar.get(Q('right')))-int(mar.get(Q('gutter'),'0'))
        body_width=width_tw*2.54/1440
        width=spec.get('width_cm',interface.get('suggested_width_cm'))
        if type(width) not in [int,float] or not 0<width<=50:raise ValueError('Invalid image width')
        width=min(width,body_width)
        with Image.open(io.BytesIO(data)) as im:
            if im.format!=('PNG' if ext=='png' else 'JPEG'):raise ValueError('Raster extension/format mismatch')
            pixels=im.size
        available_h=(int(pg.get(Q('h')))-int(mar.get(Q('top')))-int(mar.get(Q('bottom'))))*2.54/1440
        if width*pixels[1]/pixels[0]>available_h-1:raise ValueError('Image/caption pair exceeds page height; explicit resizing needed')
        caption=interface.get('caption',record.get('caption',''))
        if '{n}' in caption:caption=caption.replace('{n}',str(next_number))
        else:caption='图'+str(next_number)+' '+caption
        if kind=='A' and '示意图' not in caption:caption+='（示意图）'
        if record.get('source_type')=='synthetic_test_data' and '合成测试数据' not in caption:caption+='（合成测试数据，非真实实验）'
        rid='rIdXjtu'+core.digest((fid+source_hash).encode())[:20]
        if any(e.get('Id')==rid for e in rels):raise ValueError('Relationship ID collision')
        media='word/media/'+marker+'.'+ext
        if media in changed:raise ValueError('Image resource collision')
        relation=child(rels,'{'+PK+'}Relationship',{'Id':rid,'Type':R+'/image','Target':'media/'+marker+'.'+ext})
        ct=child(types,'{'+CT+'}Override',{'PartName':'/'+media,'ContentType':'image/'+ext})
        image_rule=config.get('effective_properties',{}).get('image.alignment',{})
        if not image_rule.get('apply') or not image_rule.get('authorized') or image_rule.get('confirmation_required') or config.get('apply_properties',{}).get('image.alignment')!=image_rule or 'image.alignment' not in config.get('allowed_properties',[]):raise ValueError('Image alignment unresolved/unauthorized')
        alignment=image_rule.get('value')
        if alignment not in ['center','left','right']:raise ValueError('Image alignment unresolved/unauthorized')
        ip,dimensions=image_paragraph(data,rid,width,doc_id,marker,alignment);cp,props=caption_paragraph(parts,config,caption)
        # Reuse the existing native pagination module on NEW blocks only.
        from pagination_layout import apply as protect_pagination
        mini=E.Element(Q('document'));mb=child(mini,Q('body'));mb.extend([ip,cp])
        def set_format(parent,tag,attrs,key,order=None):
            node=core.ensure(parent,tag,order)
            for k,v in attrs.items():node.set(Q(k),str(v))
        protect_pagination(mini,{'paragraph_groups':[[0,1]]},lambda p,t:core.ensure(p,t,core.P_ORDER),set_format)
        prepared.append((index,order,ip,cp,{'image_id':fid,'caption':caption,'figure_number':next_number,'media_part':media,'relationship_id':rid,'relationship_hash':node_hash(relation),'content_type_hash':node_hash(ct),'image_sha256':core.digest(data),'display_width_cm':width,'effective_dpi':round(pixels[0]/(width/2.54),1),'dimensions':dimensions,'caption_applied_properties':props,'quality_review_basis':spec['quality_review_basis']}))
        changed[media]=data;next_number+=1;doc_id+=1
    # Apply from end so locations are resolved against the original document only.
    for index,order,ip,cp,item in sorted(prepared,key=lambda s:(s[0],s[1]),reverse=True):body.insert(index,ip);body.insert(index+1,cp)
    for _,_,ip,cp,item in prepared:item.update(body_index=body.index(ip),block_hashes=[node_hash(ip),node_hash(cp)]);journal.append(item)
    changed['word/document.xml']=E.tostring(d,xml_declaration=True,encoding='UTF-8',standalone=True);changed[relpart]=E.tostring(rels,xml_declaration=True,encoding='UTF-8');changed['[Content_Types].xml']=E.tostring(types,xml_declaration=True,encoding='UTF-8')
    out.parent.mkdir(parents=True,exist_ok=True);fd,name=tempfile.mkstemp(dir=out.parent,suffix='.pending');os.close(fd);temp=Path(name)
    try:
        with ZipFile(temp,'w') as z:
            for info in infos:z.writestr(info,changed[info.filename])
            for key in sorted(set(changed)-set(parts)):z.writestr(key,changed[key])
        actual,_=core.read_package(temp);fidelity=verify_additions(parts,actual,journal)
        if core.digest(inp.read_bytes())!=source_hash:raise ValueError('Input changed during insertion')
        os.link(temp,out)
    finally:temp.unlink(missing_ok=True)
    final_numbers=[int(m[1]) for p in d.iter(Q('p')) if (m:=re.match(r'^图\s*(\d+)', ''.join(p.itertext())))]
    numbering_review=[] if final_numbers==sorted(final_numbers) else ['New numbers append after highest original number; document order is not numeric order. Existing captions/fields were not renumbered. User review required.']
    return {'numbering_policy':'append_after_highest_existing_without_renumbering','numbering_review':numbering_review,'schema_version':'1.0','source_sha256':source_hash,'source_unchanged':True,'output':str(out.relative_to(ROOT)),'write_performed':True,'authorized_additions':journal,'fidelity':fidelity,'package_structure_valid':True,'original_media_validation':original_media_validation,'full_schema_validated':False,'rendering':'pending','microsoft_word_verified':False,'existing_content_modified':False,'full_ready_for_writer':config['writer_contract']['ready_for_writer']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('--output',required=True);p.add_argument('--manifest',required=True);p.add_argument('--request',required=True);p.add_argument('--config',required=True);p.add_argument('--report',required=True);a=p.parse_args()
    try:
        report_path=Path(a.report).resolve()
        if not any(report_path.is_relative_to(p) for p in [OUT,output_root('workflow')]) or report_path.exists() or report_path.suffix!='.json' or report_path==Path(a.output).resolve():raise ValueError('New report within an authorized workspace output root required')
        load=lambda p:json.loads(Path(p).read_text())
        report=insert_figures(a.input,a.output,load(a.manifest),load(a.request),load(a.config));publish_text(report_path,json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('Inserted authorized figures; original-package restoration fidelity passed.')
    except Exception as e:p.exit(1,str(e)+'\n')
