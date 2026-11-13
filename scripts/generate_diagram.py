#!/usr/bin/env python3
"""Plan academic figures and generate only small explanatory DAGs as safe SVG/optional PNG."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse
from collections import defaultdict,deque
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import unicodedata
from xml.etree import ElementTree as E
from figure_plan import ROOT,plan
SVG='http://www.w3.org/2000/svg';E.register_namespace('',SVG)
FONT_SIZE=24;NODE_WIDTH=220;PAD=16

def text(value):
    if not isinstance(value,str) or not value.strip() or len(value)>500:raise ValueError('Labels require 1..500 characters')
    if any(ord(c)<32 and c not in ['\n','\t'] or 0xD800<=ord(c)<=0xDFFF or ord(c) in [0xFFFE,0xFFFF] for c in value):raise ValueError('Invalid XML label character')
    return value

def font_capability():
    try:
        from PIL import ImageFont
        r=subprocess.run(['fc-match','-f','%{family}\n%{file}','宋体'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()
        font=ImageFont.truetype(r[-1],FONT_SIZE)
        return font,{'family':r[0],'font_file':r[-1],'load_passed':True,'font_embedded_or_distributed':False}
    except (ImportError,OSError,subprocess.SubprocessError,IndexError):return None,{'family':'generic CJK serif','load_passed':False,'font_embedded_or_distributed':False}

def measure(s,font):return font.getlength(s) if font else sum(1 if unicodedata.east_asian_width(c) in ['W','F'] else .62 for c in s)*FONT_SIZE

def wrap(label,font):
    lines=[]
    for line in text(label).splitlines():
        current=''
        for char in line.replace('\t',' '):
            if current and measure(current+char,font)>NODE_WIDTH-2*PAD:lines.append(current);current=char
            else:current+=char
        lines.append(current)
    return lines

def layout(diagram,font):
    if not isinstance(diagram,dict) or diagram.get('kind') not in ['flowchart','roadmap','relationship']:raise ValueError('Unsupported basic diagram kind')
    nodes=diagram.get('nodes');edges=diagram.get('edges')
    if not isinstance(nodes,list) or not 2<=len(nodes)<=16 or not isinstance(edges,list):raise ValueError('Basic diagrams require 2..16 nodes and edge list')
    by={};incoming={};children=defaultdict(list);pairs=set()
    for node in nodes:
        if not isinstance(node,dict) or set(node)-{'id','label','type'}:raise ValueError('Invalid node fields')
        nid=node.get('id')
        if not isinstance(nid,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,31}',nid) or nid in by:raise ValueError('Invalid/duplicate node id')
        ntype=node.get('type','process')
        if ntype not in ['start_end','process','decision','input_output','junction']:raise ValueError('Unknown explicit node type')
        lines=wrap(node['label'],font)
        by[nid]={'id':nid,'label':text(node.get('label')),'lines':lines,'type':ntype};incoming[nid]=0
    for edge in edges:
        if not isinstance(edge,dict) or not {'from','to'}<=set(edge) or set(edge)-{'from','to','kind','direction'}:raise ValueError('Invalid edge fields')
        if edge.get('kind','forward') not in ['forward','data','control','feedback'] or edge.get('direction','forward') not in ['forward','both']:raise ValueError('Unknown edge semantics')
        a,b=edge['from'],edge['to']
        if a not in by or b not in by or a==b or (a,b) in pairs:raise ValueError('Invalid or duplicate connection')
        pairs.add((a,b))
        if edge.get('kind')!='feedback':children[a].append(b);incoming[b]+=1
    if not pairs:raise ValueError('At least one meaningful connection needed')
    ranks={n:0 for n in by};queue=deque(n for n in by if incoming[n]==0);count=0
    while queue:
        a=queue.popleft();count+=1
        for b in children[a]:
            ranks[b]=max(ranks[b],ranks[a]+1);incoming[b]-=1
            if incoming[b]==0:queue.append(b)
    if count!=len(by):raise ValueError('Cycles need external/manual layout; unsupported in basic DAG renderer')
    if any(ranks[e['to']]!=ranks[e['from']]+1 for e in edges if e.get('kind')!='feedback'):raise ValueError('Skip-layer connections need external/manual layout')
    layers=defaultdict(list)
    for n in by:layers[ranks[n]].append(n)
    if diagram['kind']=='flowchart' and (any(len(v)!=1 for v in layers.values()) or len(pairs)!=len(nodes)-1):raise ValueError('Linear flowchart needs one node per layer')
    if len(edges)>24 or any(len(v)>4 for v in layers.values()):raise ValueError('Dense graph needs manual/external layout')
    feedback=[e for e in edges if e.get('kind')=='feedback']
    if len(feedback)>2 or any(ranks[e['to']]>=ranks[e['from']] for e in feedback):raise ValueError('Only up to two explicit backward feedback edges supported')
    for n in by.values():
        width=max(80,max(measure(line,font) for line in n['lines'])+2*PAD)
        n['width']=width*2 if n['type']=='decision' else width+24 if n['type']=='input_output' else width
        n['height']=max(54,30*len(n['lines'])+32)*(2 if n['type']=='decision' else 1)
    row_widths={k:sum(by[n]['width'] for n in ids)+48*(len(ids)-1) for k,ids in layers.items()}
    feedback_margin=36*len(feedback)
    width=max(row_widths.values())+56+feedback_margin;y=28
    for level in sorted(layers):
        ids=layers[level];height=max(by[n]['height'] for n in ids);cursor=(width-feedback_margin-row_widths[level])/2
        for n in ids:
            by[n].update(x=cursor,y=y+(height-by[n]['height'])/2);cursor+=by[n]['width']+48
        y+=height+72
    height=y-72+28
    if width>2000 or height>2600:raise ValueError('Canvas too large for basic print diagram')
    recommended=min(14,22*width/height,10.5*width/(FONT_SIZE*28.3464567))
    print_pt=FONT_SIZE*recommended*28.3464567/width
    risks=[]
    if print_pt<9:risks.append('print_font_below_9pt_at_recommended_width')
    if not font:risks.append('font_metrics_and_cjk_font_unverified')
    for n in by.values():
        if any(measure(s,font)>n['width']-2*PAD+.1 for s in n['lines']):raise ValueError('Label exceeds node')
        if n['x']<0 or n['y']<0 or n['x']+n['width']>width or n['y']+n['height']>height:raise ValueError('Node exceeds canvas')
    routed=[]
    for e in edges:
        a,b=by[e['from']],by[e['to']]
        if e.get('kind')=='feedback':
            lane=width-20-36*feedback.index(e)
            points=[[a['x']+a['width'],a['y']+a['height']/2],[lane,a['y']+a['height']/2],[lane,b['y']+b['height']/2],[b['x']+b['width']+4,b['y']+b['height']/2]]
        else:
            outs=sorted(v['to'] for v in edges if v['from']==e['from'] and v.get('kind')!='feedback');ins=sorted(v['from'] for v in edges if v['to']==e['to'] and v.get('kind')!='feedback')
            sx=a['x']+a['width']*(outs.index(e['to'])+1)/(len(outs)+1);tx=b['x']+b['width']*(ins.index(e['from'])+1)/(len(ins)+1)
            # Diamonds have a sloping outline; attach every branch at its bottom vertex.
            if a['type']=='decision':sx=a['x']+a['width']/2
            if b['type']=='decision':tx=b['x']+b['width']/2
            y1=a['y']+a['height']+2;y2=b['y']-5;mid=(y1+y2)/2
            points=[[sx,y1],[sx,mid],[tx,mid],[tx,y2]]
        routed.append({**e,'points':points})
    if len(edges)>len(nodes):risks.append('branched_feedback_routes_need_visual_review')
    return {'nodes':list(by.values()),'edges':routed,'width':width,'height':height,'recommended_width_cm':round(recommended,3),'print_font_pt':round(print_pt,2),'risks':risks}

def svg_bytes(shape,family):
    root=E.Element('{'+SVG+'}svg',{'width':str(shape['width']),'height':str(shape['height']),'viewBox':f"0 0 {shape['width']} {shape['height']}",'role':'img'})
    def element(tag,attrs,parent=root,content=None):
        e=E.SubElement(parent,'{'+SVG+'}'+tag,{k:str(v) for k,v in attrs.items()})
        if content is not None:e.text=content
        return e
    defs=element('defs',{});marker=element('marker',{'id':'arrow','viewBox':'0 0 10 10','refX':9,'refY':5,'markerWidth':8,'markerHeight':8,'orient':'auto'},defs);element('path',{'d':'M 0 0 L 10 5 L 0 10 z','fill':'#475569'},marker)
    element('rect',{'x':0,'y':0,'width':shape['width'],'height':shape['height'],'fill':'white'})
    for edge in shape['edges']:
        attrs={'points':' '.join(f'{x},{y}' for x,y in edge['points']),'fill':'none','stroke':'#475569','stroke-width':2,'marker-end':'url(#arrow)'}
        if edge.get('direction')=='both':attrs['marker-start']='url(#reverse-arrow)'
        if edge.get('kind')=='control':attrs['stroke-dasharray']='6 4'
        element('polyline',attrs)
    rev=element('marker',{'id':'reverse-arrow','viewBox':'0 0 10 10','refX':1,'refY':5,'markerWidth':8,'markerHeight':8,'orient':'auto'},defs);element('path',{'d':'M 10 0 L 0 5 L 10 10 z','fill':'#475569'},rev)
    for n in shape['nodes']:
        x,y,w,h=n['x'],n['y'],n['width'],n['height'];attrs={'id':n['id'],'fill':'#f8fafc','stroke':'#334155','stroke-width':2}
        if n['type'] in ['decision','input_output']:
            points=[(x+w/2,y),(x+w,y+h/2),(x+w/2,y+h),(x,y+h/2)] if n['type']=='decision' else [(x+12,y),(x+w,y),(x+w-12,y+h),(x,y+h)]
            element('polygon',{**attrs,'points':' '.join(f'{a},{b}' for a,b in points)})
        else:element('rect',{**attrs,'x':x,'y':y,'width':w,'height':h,'rx':h/2 if n['type']=='start_end' else 8})
        for i,line in enumerate(n['lines']):element('text',{'x':x+w/2,'y':y+(h-len(n['lines'])*30)/2+FONT_SIZE+i*30,'text-anchor':'middle','font-family':family+', serif','font-size':FONT_SIZE,'fill':'#111827'},content=line)
    return E.tostring(root,encoding='utf-8',xml_declaration=True)

def png_bytes(shape,font):
    if font is None:return None
    from PIL import Image,ImageDraw,ImageFont
    scale=max(2,math.ceil(300*shape['recommended_width_cm']/2.54/shape['width']))
    if shape['width']*shape['height']*scale*scale>24_000_000:return None
    image=Image.new('RGB',(math.ceil(shape['width']*scale),math.ceil(shape['height']*scale)),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype(font.path,FONT_SIZE*scale)
    def arrow(tip,previous):
        x2,y2=tip;angle=math.atan2(y2-previous[1],x2-previous[0]);draw.polygon([tip,(x2-10*scale*math.cos(angle-.45),y2-10*scale*math.sin(angle-.45)),(x2-10*scale*math.cos(angle+.45),y2-10*scale*math.sin(angle+.45))],fill='#475569')
    for edge in shape['edges']:
        pts=[(x*scale,y*scale) for x,y in edge['points']]
        # PNG and SVG share the same explicitly declared edge semantics.
        if edge.get('kind')=='control':
            for a,b in zip(pts,pts[1:]):
                length=math.dist(a,b)
                if not length:continue
                for start in range(0,math.ceil(length),10*scale):
                    end=min(length,start+6*scale)
                    draw.line([(a[0]+(b[0]-a[0])*v/length,a[1]+(b[1]-a[1])*v/length) for v in [start,end]],fill='#475569',width=2*scale)
        else:draw.line(pts,fill='#475569',width=2*scale)
        arrow(pts[-1],next(p for p in reversed(pts[:-1]) if p!=pts[-1]))
        if edge.get('direction')=='both':arrow(pts[0],next(p for p in pts[1:] if p!=pts[0]))
    for n in shape['nodes']:
        x,y,w,h=[n[k]*scale for k in ['x','y','width','height']]
        if n['type'] in ['decision','input_output']:
            pts=[(x+w/2,y),(x+w,y+h/2),(x+w/2,y+h),(x,y+h/2)] if n['type']=='decision' else [(x+12*scale,y),(x+w,y),(x+w-12*scale,y+h),(x,y+h)]
            draw.polygon(pts,fill='#f8fafc');draw.line(pts+[pts[0]],fill='#334155',width=2*scale)
        else:draw.rounded_rectangle((x,y,x+w,y+h),radius=h/2 if n['type']=='start_end' else 8*scale,fill='#f8fafc',outline='#334155',width=2*scale)
        for i,line in enumerate(n['lines']):draw.text((x+w/2,y+(h-len(n['lines'])*30*scale)/2+i*30*scale),line,font=font,anchor='mt',fill='#111827')
    buf=io.BytesIO();image.save(buf,format='PNG',dpi=(300,300));return buf.getvalue()

def generate(request,output,capability=None,png=False):
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT) or output.exists():raise ValueError('Output directory must be new and within project')
    result=plan(request,capability);font,cap=font_capability();prepared=[];by={f['image_id']:f for f in request.get('figures',[])}
    for record in result['figures']:
        if record['status']!='ready_builtin':continue
        shape=layout(by[record['image_id']]['diagram'],font);svg=svg_bytes(shape,cap['family']);raster=png_bytes(shape,font) if png else None
        fid=record['image_id'];record.update(status='generated_schematic',verification_status='structural_layout_checks_passed_visual_review_required',generation_method='builtin_svg_dag',output_path=str((output/(fid+'.svg')).relative_to(ROOT)),output_formats=['svg']+(['png'] if raster else []),quality={'bounds_and_label_metrics':'passed_with_current_font' if font else 'estimated_only','font':cap,'risks':shape['risks'],'manual_visual_confirmation':False,'semantic_review':'required','png_status':'generated' if raster else 'not_requested_or_unavailable'})
        record['docx_interface']={'image_path':str((output/(fid+'.png' if raster else fid+'.svg')).relative_to(ROOT)),'source_svg':record['output_path'],'image_type':'A','suggested_width_cm':shape['recommended_width_cm'],'preserve_aspect_ratio':True,'caption':record['caption'],'insertion_section':record['section'],'source_reference':record['source_reference'],'quality_status':record['verification_status'],'insertion_authorized':False,'display_alignment':'center','caption_position':'below','style_source':'existing frozen default-style.json; no override','requires_docx_content_fidelity':True}
        record['output_hashes']={'svg':hashlib.sha256(svg).hexdigest(),**({'png':hashlib.sha256(raster).hexdigest()} if raster else {})}
        prepared.append((fid,svg,raster,shape))
    output.mkdir(parents=True,exist_ok=False)
    for fid,svg,raster,shape in prepared:
        (output/(fid+'.svg')).write_bytes(svg)
        if raster:(output/(fid+'.png')).write_bytes(raster)
        (output/(fid+'-layout.json')).write_text(json.dumps(shape,ensure_ascii=False,indent=2))
    (output/'figure-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True,type=Path);p.add_argument('--output-dir',required=True,type=Path);p.add_argument('--capabilities',type=Path);p.add_argument('--png',action='store_true');a=p.parse_args()
    try:r=generate(json.loads(a.request.read_text()),a.output_dir,json.loads(a.capabilities.read_text()) if a.capabilities else None,a.png);print('Planned',len(r['figures']),'figures; SVG outputs:',sum(f['status']=='generated_schematic' for f in r['figures']))
    except (ValueError,TypeError,KeyError,OSError) as e:p.exit(1,'Figure generation stopped: '+str(e)+'\n')
