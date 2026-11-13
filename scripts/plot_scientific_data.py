#!/usr/bin/env python3
"""Reproducible scientific plots from explicitly sourced tabular files; never invent observations."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import statistics
from zipfile import ZipFile
from lxml import etree as E
from figure_plan import ROOT, file_evidence

OUT=output_root('figures')

def read_records(path, sheet=None):
    """Deliberately narrow XLSX reader: literal strings/numbers only, no formula/date inference."""
    suffix=path.suffix.lower()
    if suffix in ['.csv','.tsv']:
        reader=csv.DictReader(io.StringIO(path.read_text(encoding='utf-8-sig')),delimiter='\t' if suffix=='.tsv' else ',')
        headers=reader.fieldnames or [];rows=list(reader)
        if len(set(headers))!=len(headers) or None in headers or any(None in r for r in rows):raise ValueError('Duplicate headers or ragged CSV')
    elif suffix in ['.json','.jsonl']:
        raw=[json.loads(s) for s in path.read_text().splitlines() if s.strip()] if suffix=='.jsonl' else json.loads(path.read_text())
        rows=raw.get('records') if isinstance(raw,dict) else raw
    elif suffix=='.xlsx':
        from format_docx import parse
        n={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        with ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist())>30_000_000:raise ValueError('XLSX too large')
            wb=parse(z.read('xl/workbook.xml'));sheets=wb.findall('s:sheets/s:sheet',n)
            selected=[s for s in sheets if s.get('name')==sheet] if sheet else sheets
            if len(selected)!=1:raise ValueError('Select one unambiguous XLSX sheet')
            relations=parse(z.read('xl/_rels/workbook.xml.rels'));target=next((r.get('Target') for r in relations if r.get('Id')==selected[0].get('{'+rel+'}id') and not r.get('TargetMode')),None)
            if not target or '..' in target:raise ValueError('Unsafe XLSX target')
            name=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            strings=[]
            if 'xl/sharedStrings.xml' in z.namelist():strings=[''.join(s.itertext()) for s in parse(z.read('xl/sharedStrings.xml')).findall('s:si',n)]
            values=[]
            for row in parse(z.read(name)).findall('s:sheetData/s:row',n):
                cols={}
                for cell in row.findall('s:c',n):
                    if cell.find('s:f',n) is not None or cell.get('s','0')!='0':raise ValueError('XLSX formulas/styled dates or numbers require explicit export to CSV')
                    m=re.fullmatch('([A-Z]+)[0-9]+',cell.get('r',''))
                    if not m:raise ValueError('Invalid XLSX address')
                    ci=0
                    for c in m[1]:ci=ci*26+ord(c)-64
                    v=cell.find('s:v',n);v=v.text if v is not None else None;t=cell.get('t','n')
                    if t=='s':v=strings[int(v)]
                    elif t=='inlineStr':v=''.join(cell.find('s:is',n).itertext())
                    elif t not in ['n','str']:raise ValueError('Unsupported XLSX cell type')
                    cols[ci-1]=v
                values.append(cols)
        if not values:raise ValueError('Empty worksheet')
        headers=[values[0].get(i) for i in range(max(values[0])+1)]
        if any(not isinstance(h,str) or not h for h in headers) or len(set(headers))!=len(headers):raise ValueError('Invalid XLSX header')
        if any(any(i>=len(headers) for i in r) for r in values[1:]):raise ValueError('Ragged XLSX')
        rows=[{h:r.get(i) for i,h in enumerate(headers)} for r in values[1:]]
    else:raise ValueError('Use CSV/TSV, XLSX literals, JSON records or JSONL; free-text logs are not guessed')
    if not isinstance(rows,list) or not 1<=len(rows)<=100000 or any(not isinstance(r,dict) for r in rows):raise ValueError('Need 1..100000 object records')
    return rows

def prepare(config):
    if config.get('schema_version')!='1.0' or config.get('chart_type') not in ['line','scatter','bar','errorbar','multi_line']:raise ValueError('Invalid schema/chart_type')
    fid=config.get('figure_id','')
    if not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,39}',fid):raise ValueError('Invalid figure_id')
    source=config.get('source',{});stype=source.get('source_type')
    if stype not in ['user_data','program_results','public_dataset','synthetic_test_data'] or not source.get('source_reference'):raise ValueError('Explicit data provenance required')
    if stype=='synthetic_test_data' and config.get('allow_synthetic_test_data') is not True:raise ValueError('Synthetic data requires explicit test permission')
    evidence=file_evidence(source.get('source_path'))
    if not evidence.get('present'):raise ValueError('Data file missing')
    path=ROOT/evidence['path'];rows=read_records(path,config.get('sheet'))
    x=config.get('x_column');ys=config.get('y_columns');units=config.get('units',{})
    if not isinstance(x,str) or not isinstance(ys,list) or not ys or len(set(ys))!=len(ys) or len(ys)>8:raise ValueError('Explicit x_column/y_columns needed')
    if config['chart_type']=='multi_line' and len(ys)<2:raise ValueError('multi_line needs multiple series')
    if len(ys)>1 and (not isinstance(config.get('labels',{}).get('y'),str) or not config['labels']['y'].strip()):raise ValueError('Multiple series require explicit common y-axis physical quantity; never infer it from a series name')
    error=config.get('error',{});ecol=error.get('column');columns=[x]+ys+([ecol] if ecol else [])
    if any(not isinstance(units.get(c),str) or not units[c].strip() for c in [x]+ys):raise ValueError('Declare units (use dimensionless where appropriate)')
    if any(any(c not in r for c in columns) for r in rows):raise ValueError('Column missing')
    prep=config.get('preprocessing',{});allowed={'drop_missing','sort_x'}
    if set(prep)-allowed or any(type(v)is not bool for v in prep.values()):raise ValueError('Only explicit drop_missing/sort_x supported; no interpolation/smoothing')
    clean=[];dropped=[];bar=config['chart_type']=='bar'
    for i,r in enumerate(rows):
        if any(r[c] is None or r[c]=='' for c in columns):
            if not prep.get('drop_missing'):raise ValueError('Missing data; no implicit filling/removal')
            dropped.append(i);continue
        record={}
        for c in columns:
            if c==x and bar:
                if not isinstance(r[c],(str,int,float)):raise ValueError('Invalid bar category')
                record[c]=str(r[c]);continue
            if isinstance(r[c],bool):raise ValueError('Boolean is not numeric data')
            try:value=float(r[c])
            except (ValueError,TypeError):raise ValueError('Non-numeric field '+c)
            if not math.isfinite(value):raise ValueError('NaN/infinity rejected')
            record[c]=value
        clean.append(record)
    if not clean:raise ValueError('No usable observations')
    duplicate_count=len(clean)-len({json.dumps(r,sort_keys=True) for r in clean});warnings=[]
    if duplicate_count:warnings.append('duplicate_records_preserved:'+str(duplicate_count))
    if prep.get('sort_x'):clean.sort(key=lambda r:r[x])
    elif config['chart_type'] in ['line','multi_line','errorbar'] and any(a[x]>b[x] for a,b in zip(clean,clean[1:])):raise ValueError('Unordered x: explicitly authorize sort_x or use scatter')
    series=[];stat={'method':'none','normalization':'none','sample_count':len(clean)}
    for y in ys:
        data={'column':y,'label':config.get('series_labels',{}).get(y,y if len(ys)>1 else config.get('labels',{}).get(y,y)),'x':[r[x] for r in clean],'y':[r[y] for r in clean]}
        if config['chart_type']=='errorbar':
            meaning=error.get('meaning')
            if meaning not in ['sample_standard_deviation','standard_error','confidence_interval','provided_uncertainty']:raise ValueError('Declare error-bar statistical meaning')
            if error.get('method')=='replicates':
                if meaning not in ['sample_standard_deviation','standard_error']:raise ValueError('Only sample SD/SEM computed; no implicit CI')
                groups={v:[r[y] for r in clean if r[x]==v] for v in dict.fromkeys(r[x] for r in clean)}
                if any(len(v)<2 for v in groups.values()):raise ValueError('Replicates need at least two observations per x')
                data.update(x=list(groups),y=[statistics.mean(v) for v in groups.values()],yerr=[statistics.stdev(v)/(math.sqrt(len(v)) if meaning=='standard_error' else 1) for v in groups.values()],n=[len(v) for v in groups.values()])
                stat={'method':'arithmetic_mean_and_'+meaning,'meaning':meaning,'ddof':1,'sample_count':len(clean),'normalization':'none'}
            elif error.get('method')=='provided' and ecol:
                if units.get(ecol)!=units[y]:raise ValueError('Error units must match y')
                data['yerr']=[r[ecol] for r in clean]
                if any(v<0 for v in data['yerr']):raise ValueError('Negative error magnitude')
                if meaning=='confidence_interval' and not 0<float(error.get('confidence_level',0))<1:raise ValueError('Provide confidence_level')
                stat={'method':'provided_errors_not_recomputed','meaning':meaning,'sample_count':len(clean),'normalization':'none','confidence_level':error.get('confidence_level')}
            else:raise ValueError('Explicit provided error column or replicate method required')
        # Conservative flag only; no data removed or normalized.
        vals=data['y']
        if len(vals)>=4:
            med=statistics.median(vals);mad=statistics.median(abs(v-med) for v in vals)
            if mad and any(abs(v-med)>10*mad for v in vals):warnings.append(y+':large_deviation_review_only_no_removal')
        series.append(data)
    if len({units[y] for y in ys})!=1:raise ValueError('Mixed y units require separate plots')
    if bar and len({r[x] for r in clean})!=len(clean):raise ValueError('Repeated bar category; explicit aggregation required')
    return path,evidence,series,stat,{'requested':prep,'dropped_row_indices':dropped,'original_row_count':len(rows),'retained_row_count':len(clean),'warnings':warnings}

def plot(config,output):
    output=Path(output).resolve()
    if not any(output.is_relative_to(p) for p in [OUT,output_root('polishing'),output_root('workflow')]) or output.exists():raise ValueError('New output directory within an authorized workspace output root required')
    path,evidence,series,stat,processing=prepare(config);original=path.read_bytes()
    if hashlib.sha256(original).hexdigest()!=evidence['sha256']:raise ValueError('Data source changed during validation')
    output.mkdir(parents=True);os.environ.setdefault('MPLCONFIGDIR',str(OUT/'matplotlib-cache'))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt, font_manager as fm
    import subprocess
    fonts={}
    for name in ['Times New Roman','宋体']:
        lines=subprocess.run(['fc-match','-f','%{family}\n%{file}',name],capture_output=True,text=True,check=True).stdout.splitlines()
        fm.fontManager.addfont(lines[-1]);fonts[name]={'actual_family':lines[0],'path':lines[-1],'substitution':name not in lines[0] and not (name=='宋体' and 'SimSun' in lines[0])}
    families=[fm.FontProperties(fname=fonts[n]['path']).get_name() for n in fonts]
    with plt.rc_context({'font.family':families,'font.size':10,'axes.unicode_minus':False,'svg.hashsalt':'xjtu-paper-writer-v1','axes.spines.top':False,'axes.spines.right':False}):
        fig,ax=plt.subplots(figsize=(5.5,3.5),layout='constrained');artist_values=[];styles=['-','--','-.',':'];markers=['o','s','^','D'];colors=['#1f4e79','#985f16','#31704b','#7b477d']
        for i,s in enumerate(series):
            common={'label':s['label'],'color':colors[i%4]};kind=config['chart_type']
            if kind in ['line','multi_line']:
                artist,=ax.plot(s['x'],s['y'],linestyle=styles[i%4],marker=markers[i%4],linewidth=1.3,markersize=4,**common);observed={'x':list(artist.get_xdata()),'y':list(artist.get_ydata())}
            elif kind=='scatter':
                artist=ax.scatter(s['x'],s['y'],marker=markers[i%4],s=23,**common);offsets=artist.get_offsets();observed={'x':list(offsets[:,0]),'y':list(offsets[:,1])}
            elif kind=='bar':
                width=.8/len(series);positions=[j-.4+width*(i+.5) for j in range(len(s['x']))];bars=ax.bar(positions,s['y'],width=width,edgecolor='black',linewidth=.6,hatch=['','//','..','xx'][i%4],**common);ax.set_xticks(range(len(s['x'])),s['x']);observed={'x':s['x'],'y':[b.get_height() for b in bars]}
            else:
                artist=ax.errorbar(s['x'],s['y'],yerr=s['yerr'],fmt=markers[i%4]+'-',capsize=3,linewidth=1.2,**common);observed={'x':list(artist.lines[0].get_xdata()),'y':list(artist.lines[0].get_ydata())}
                segments=artist.lines[2][0].get_segments()
                if any(not math.isclose(float(seg[1][1]-seg[0][1]),2*err,abs_tol=1e-10) for seg,err in zip(segments,s['yerr'])):raise ValueError('Error-bar artist differs from computed error')
            if observed!={'x':s['x'],'y':s['y']}:raise ValueError('Rendered artist data differs from requested data')
            artist_values.append({'column':s['column'],**observed})
        labels=config.get('labels',{});x=config['x_column'];y=config['y_columns'][0];units=config['units']
        ax.set_xlabel(labels.get('x',x)+' ['+units[x]+']');ax.set_ylabel(labels.get('y',y)+' ['+units[y]+']');ax.grid(True,alpha=.2)
        if len(series)>1:ax.legend(loc='best',frameon=False)
        title=config.get('title','')
        synthetic=config['source']['source_type']=='synthetic_test_data'
        heading=(title+'\n' if title else '')+('Synthetic test data — not experimental results' if synthetic else '')
        if config['chart_type']=='errorbar':
            desc={'sample_standard_deviation':'sample SD','standard_error':'SEM','confidence_interval':'confidence interval','provided_uncertainty':'provided uncertainty'}[config['error']['meaning']]
            if config['error']['meaning']=='confidence_interval':desc=str(100*config['error']['confidence_level'])+'% '+desc
            if config['error'].get('method')=='replicates':desc+='; n/group='+','.join(map(str,series[0]['n']))+'; ddof=1'
            heading+='\nError bars: '+desc
        ax.set_title(heading.strip(),fontsize=10)
        from matplotlib.text import Text
        from matplotlib.ft2font import FT2Font
        # Older Matplotlib lacks per-glyph family fallback: explicitly choose a font for each label.
        for t in fig.findobj(Text):
            name='宋体' if re.search(r'[\u2e80-\u9fff]',t.get_text()) else 'Times New Roman'
            fontpath=fonts[name]['path'];prop=fm.FontProperties(fname=fontpath,size=t.get_fontsize());t.set_fontproperties(prop)
            missing={c for c in t.get_text() if not c.isspace() and ord(c) not in FT2Font(fontpath).get_charmap()}
            if missing:plt.close(fig);raise ValueError('Missing font glyphs: '+str(missing))
        fig.canvas.draw();renderer=fig.canvas.get_renderer();fw,fh=fig.canvas.get_width_height()
        visible_ticks=[t for v,t in zip(ax.get_xticks(),ax.get_xticklabels()) if min(ax.get_xlim())<=v<=max(ax.get_xlim())]+[t for v,t in zip(ax.get_yticks(),ax.get_yticklabels()) if min(ax.get_ylim())<=v<=max(ax.get_ylim())]
        checked_text=[ax.title,ax.xaxis.label,ax.yaxis.label,*visible_ticks]+(ax.get_legend().get_texts() if ax.get_legend() else [])
        overflow=[t.get_text() for t in checked_text if t.get_text() and (t.get_window_extent(renderer).x0<0 or t.get_window_extent(renderer).y0<0 or t.get_window_extent(renderer).x1>fw or t.get_window_extent(renderer).y1>fh)]
        if overflow:plt.close(fig);raise ValueError('Text exceeds figure canvas: '+str(overflow))
        fid=config['figure_id'];png=output/(fid+'.png');svg=output/(fid+'.svg')
        fig.savefig(png,dpi=300,metadata={'Software':'xjtu-paper-writer'});fig.savefig(svg,metadata={'Date':None,'Creator':'xjtu-paper-writer'});plt.close(fig)
    if path.read_bytes()!=original:raise ValueError('Source changed during plotting')
    caption=config.get('caption',config.get('title',fid))
    if synthetic and '合成测试数据' not in caption:caption+='（合成测试数据，非真实实验）'
    if config['chart_type']=='errorbar':caption+='；误差棒：'+{'sample_standard_deviation':'样本标准差','standard_error':'均值标准误','confidence_interval':'置信区间','provided_uncertainty':'来源声明的不确定度'}[config['error']['meaning']]
    record={'tool_fingerprint':{'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'matplotlib_version':matplotlib.__version__},'generation_method':'reproducible_matplotlib','config_hash':hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'schema_version':'1.0','figure_id':fid,'image_id':fid,'image_type':'B','chart_type':config['chart_type'],'source_type':config['source']['source_type'],'source_file':evidence['path'],'source_hash':evidence['sha256'],'source_reference':config['source']['source_reference'],'x_column':x,'y_columns':config['y_columns'],'units':units,'labels':labels,'preprocessing':processing,'statistical_method':stat,'output_file':str(png.relative_to(ROOT)),'output_format':['png','svg'],'output_hashes':{p.suffix[1:]:hashlib.sha256(p.read_bytes()).hexdigest() for p in [png,svg]},'generation_timestamp':datetime.now(timezone.utc).isoformat(),'fonts':fonts,'font_policy':'CJK-containing labels use SimSun as a whole; Latin-only labels use Times New Roman. Mixed-label Latin glyphs are SimSun on this Matplotlib version. No per-glyph fallback claim.','caption':caption,'verification_status':{'file_exists':True,'structure_valid':True,'plotted_values_recorded':True,'artist_data_matches':True,'data_authenticity':'synthetic_test_data_not_experiment' if synthetic else 'source_attested_not_independently_verified','canvas_bounds':'passed_current_renderer','agent_visual_review':'pending','manual_visual_confirmation':False},'docx_interface':{'image_path':str(png.relative_to(ROOT)),'source_svg':str(svg.relative_to(ROOT)),'image_type':'B','suggested_width_cm':13.97,'preserve_aspect_ratio':True,'caption':'图{n} '+caption,'source_reference':config['source']['source_reference'],'insertion_authorized':False}}
    for name,value in [('plot-config.json',config),('plotted-values.json',series),('artist-values.json',artist_values),('figure-record.json',record)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return record

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True,type=Path);p.add_argument('--output-dir',required=True,type=Path);a=p.parse_args()
    try:plot(json.loads(a.config.read_text()),a.output_dir);print('Plotted supplied data; provenance and exact plotted values recorded; visual review required.')
    except Exception as e:p.exit(1,str(e)+'\n')
