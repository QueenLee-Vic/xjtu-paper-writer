#!/usr/bin/env python3
"""LibreOffice PDF/PNG renderer and bounded PDF text geometry measurements."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from xml.etree import ElementTree as E
ROOT=data_root();OUT=output_root('render')

def run(args,env=None):
    r=subprocess.run(args,capture_output=True,text=True,timeout=60,env=env)
    if r.returncode:raise RuntimeError('Tool failed: '+args[0]+': '+r.stderr[-1500:])
    return r.stdout

def inspect_layout(pages,checks):
    checks=checks or {};ns='{http://www.w3.org/1999/xhtml}'
    occurrences={}
    for token in checks.get('tokens',[]):
        occurrences[token]=[i+1 for i,p in enumerate(pages) if token in ''.join((w.text or '') for w in p.iter(ns+'word'))]
    relations=[]
    for relation in checks.get('same_page',[]):
        matches=[occurrences.get(t,[]) for t in relation['tokens']]
        ok=bool(matches) and all(len(v)==1 for v in matches) and len({v[0] for v in matches if v})==1
        relations.append({'id':relation['id'],'pages':matches,'passed':ok})
    regions=[]
    for region in checks.get('formula_regions',[]):
        hits=[]
        for pi,page in enumerate(pages):
            words=list(page.iter(ns+'word'))
            start=[w for w in words if w.text==region['start']];end=[w for w in words if w.text==region['end']]
            if len(start)!=1 or len(end)!=1:continue
            y1=float(start[0].get('yMax'));y2=float(end[0].get('yMin'))
            body=[w for w in words if float(w.get('yMin'))>=y1-1 and float(w.get('yMax'))<=y2+1]
            if not body:continue
            xmin=min(float(w.get('xMin')) for w in body);xmax=max(float(w.get('xMax')) for w in body)
            left=region.get('left_pt',90);right=float(page.get('width'))-region.get('right_pt',90)
            hits.append({'page':pi+1,'visible_width_pt':round(xmax-xmin,3),'text_area_width_pt':round(right-left,3),'center_error_pt':round((xmin+xmax-left-right)/2,3),'exceeds_text_area':xmin<left-2 or xmax>right+2})
        regions.append({'case':region['case'],'measurements':hits,'status':'measured_visible_bbox_only' if hits else 'unverified_region_not_uniquely_located'})
    widths=[]
    for spec in checks.get('overflow_formula_tokens',[]):
        for pi,page in enumerate(pages):
            words=list(page.iter(ns+'word'));seen=[]
            for word in words:
                y=float(word.get('yMin'))
                if any(abs(y-v)<3 for v in seen):continue
                seen.append(y);row=sorted([w for w in words if abs(float(w.get('yMin'))-y)<3],key=lambda w:float(w.get('xMin')))
                if spec['token'] not in ''.join(w.text or '' for w in row):continue
                xmin=min(float(w.get('xMin')) for w in row);xmax=max(float(w.get('xMax')) for w in row)
                right=float(page.get('width'))-spec.get('right_pt',90);left=spec.get('left_pt',90)
                widths.append({'case':spec['case'],'page':pi+1,'visible_width_lower_bound_pt':round(xmax-xmin,3),'text_area_width_pt':round(right-left,3),'overflow_at_least_pt':round(max(0,left-xmin,xmax-right),3),'exceeds_page':xmax>float(page.get('width')),'handling':'preserved_omml; no_safe_automatic_reflow; complete_layout_blocked'})
    return {'observed_formula_rows':widths,'token_pages':occurrences,'same_page_checks':relations,'formula_regions':regions,'limits':'Visible PDF text bounding boxes only; clipped glyphs, image geometry and overlap need review'}

def render(path,output,formula_checks=None,layout_checks=None):
    path=Path(path).resolve();output=Path(output).resolve()
    if not any(output.is_relative_to(p) for p in [OUT,output_root('pagination'),output_root('figures'),output_root('polishing_writer'),output_root('workflow'),output_root('experiment_report')]) or output.exists():raise ValueError('Render directory must be new and within an authorized workspace output root')
    for t in ['libreoffice','pdftoppm','pdftotext','pdffonts','fc-match']:
        if not shutil.which(t):raise ValueError('Missing renderer dependency: '+t)
    before=hashlib.sha256(path.read_bytes()).hexdigest();output.mkdir(parents=True)
    env=dict(os.environ,DCONF_PROFILE='',GSETTINGS_BACKEND='memory',SAL_USE_VCLPLUGIN='svp',DISPLAY='',SAL_DISABLE_OPENCL='1',SAL_DISABLEGL='1',XDG_CACHE_HOME=str(output/'cache'),TMPDIR=str(output/'temp'),OSL_SOCKET_PATH=str(output/'temp'))
    (output/'temp').mkdir()
    profile=output/'lo-profile'
    log=run(['libreoffice','-env:UserInstallation='+profile.as_uri(),'--headless','--convert-to','pdf','--outdir',str(output),str(path)],env)
    pdf=output/(path.stem+'.pdf')
    if not pdf.is_file():raise RuntimeError('LibreOffice returned without a PDF: '+log)
    run(['pdftoppm','-r','85','-png',str(pdf),str(output/'page')],env)
    xml=run(['pdftotext','-bbox',str(pdf),'-'],env)
    pages=list(E.fromstring(xml).iter('{http://www.w3.org/1999/xhtml}page'))
    fonts=run(['pdffonts',str(pdf)],env)
    matches={name:run(['fc-match','-f','%{family}\n%{file}',name],env) for name in ['宋体','Times New Roman','Cambria Math']}
    geometry=[]
    for check in formula_checks or []:
        hits=[]
        for pi,page in enumerate(pages):
            words=list(page.iter('{http://www.w3.org/1999/xhtml}word'))
            bodies=[w for w in words if (w.text or '')==check['token']]
            numbers=[w for w in words if (w.text or '').replace('（','(').replace('）',')')==check['number']]
            for body in bodies:
                cy=(float(body.get('yMin'))+float(body.get('yMax')))/2
                adjacent=sorted([w for w in words if float(w.get('xMin'))>float(body.get('xMax')) and abs((float(w.get('yMin'))+float(w.get('yMax')))/2-cy)<3],key=lambda w:float(w.get('xMin')))
                combined=''.join(w.text or '' for w in adjacent).replace('（','(').replace('）',')')
                candidates=list(numbers)
                if combined==check['number'] and not candidates:
                    merged=E.Element('word',dict(adjacent[0].attrib));merged.set('xMax',adjacent[-1].get('xMax'));candidates.append(merged)
                for num in candidates:
                    by=(float(body.get('yMin'))+float(body.get('yMax')))/2;ny=(float(num.get('yMin'))+float(num.get('yMax')))/2
                    if abs(by-ny)>12:continue
                    cx=(float(body.get('xMin'))+float(body.get('xMax')))/2
                    center=(float(page.get('width'))+check['left_pt']-check['right_pt'])/2
                    edge=float(page.get('width'))-check['right_pt']
                    hits.append({'page':pi+1,'center_error_pt':round(cx-center,3),'right_edge_error_pt':round(float(num.get('xMax'))-edge,3),'baseline_region_error_pt':round(by-ny,3)})
        ok=len(hits)==1 and abs(hits[0]['center_error_pt'])<=2 and abs(hits[0]['right_edge_error_pt'])<=2
        geometry.append({'case':check['case'],'matches':hits,'passed':ok,'tolerance_pt':2})
    assert before==hashlib.sha256(path.read_bytes()).hexdigest()
    overflow=sum(1 for page in pages for word in page.iter('{http://www.w3.org/1999/xhtml}word') if float(word.get('xMin'))<0 or float(word.get('xMax'))>float(page.get('width'))+1 or float(word.get('yMax'))>float(page.get('height'))+1)
    layout=inspect_layout(pages,layout_checks)
    report={'source_sha256':before,'layout_checks':layout,'full_layout_passed':False,'layout_blockers':(['page_overflow_detected'] if overflow else [])+['manual_visual_verification_outstanding'],'detected_out_of_page_words':overflow,'page_overflow_status':'potential_overflow' if overflow else 'no_bbox_overflow_detected_not_a_complete_layout_check','renderer':'LibreOffice (not Microsoft Word)','log':log,'pdf':str(pdf.relative_to(ROOT)),
            'page_images':[str(p.relative_to(ROOT)) for p in sorted(output.glob('page-*.png'))],
            'page_count':len(pages),'page_sizes_pt':[{'width':p.get('width'),'height':p.get('height')} for p in pages],
            'fontconfig_matches':matches,'pdf_fonts':fonts,'formula_geometry':geometry,
            'render_generation_passed':True,'formula_geometry_passed':bool(geometry) and all(g['passed'] for g in geometry),
            'font_metrics_limits':'Fontconfig match is not proof every glyph uses that font; inspect PDF embedded font list',
            'manual_visual_confirmation':False,'microsoft_word_verified':False,'source_unchanged':True,
            'manual_checks':['margins/body font/line spacing','heading/caption placement','table borders','image aspect ratio','pagination/overflow','complex equations']}
    (output/'render-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('--output',required=True);p.add_argument('--checks');p.add_argument('--layout-checks');a=p.parse_args()
    try:r=render(a.input,a.output,json.loads(Path(a.checks).read_text()) if a.checks else None,json.loads(Path(a.layout_checks).read_text()) if a.layout_checks else None);print('Rendered',r['page_count'],'pages; formula geometry:',r['formula_geometry_passed'])
    except Exception as e:p.exit(1,str(e)+'\n')
