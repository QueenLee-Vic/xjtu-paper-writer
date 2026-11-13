#!/usr/bin/env python3
"""Read-only OOXML format inventory. No document text or media is exported."""
from workspace_paths import SKILL_ROOT, data_root, output_root
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
      'v': 'urn:schemas-microsoft-com:vml'}
W = '{' + NS['w'] + '}'
PROJECT = data_root()

def attrs(node):
    return {} if node is None else {k.split('}')[-1]: v for k, v in node.attrib.items()}

def find(node, path):
    return None if node is None else node.find(path, NS)

def val(node, path, key='val'):
    return attrs(find(node, path)).get(key)

def record(value=None, source=None, status=None, **extra):
    return dict(value=value, source=source, status=status or ('extracted' if value is not None else 'unknown'), **extra)

def text(node):
    # Used only in memory for structural role classification, never serialized.
    return ''.join(t.text or '' for t in node.iter(W + 't'))

def properties(node, kind):
    """Flatten only formatting attributes; never include w:t or field instructions."""
    out = {}
    paths = ({'rFonts': ['ascii', 'hAnsi', 'eastAsia', 'cs', 'asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme'],
              'color': ['val', 'themeColor', 'themeTint', 'themeShade'], 'lang': ['val', 'eastAsia', 'bidi']}
             if kind == 'r' else {'spacing': ['before', 'after', 'beforeLines', 'afterLines', 'line', 'lineRule', 'beforeAutospacing', 'afterAutospacing'],
              'ind': ['left', 'right', 'start', 'end', 'firstLine', 'hanging', 'firstLineChars', 'hangingChars', 'leftChars', 'rightChars']})
    singles = (['sz', 'szCs', 'b', 'bCs', 'i', 'iCs', 'u', 'spacing', 'kern', 'position', 'vertAlign', 'rtl']
               if kind == 'r' else ['jc', 'outlineLvl', 'keepNext', 'keepLines', 'pageBreakBefore', 'widowControl', 'contextualSpacing', 'bidi', 'textAlignment'])
    for tag, keys in paths.items():
        data = attrs(find(node, 'w:' + tag))
        out.update({tag + '.' + k: data[k] for k in keys if k in data})
    for tag in singles:
        e = find(node, 'w:' + tag)
        if e is not None:
            out[tag] = attrs(e).get('val', 'true')
    tabs = find(node, 'w:tabs')
    if tabs is not None:
        out['tabs'] = [attrs(e) for e in tabs]
    num = find(node, 'w:numPr')
    if num is not None:
        for key in ['numId', 'ilvl']:
            v = val(num, 'w:' + key)
            if v is not None:
                out['numPr.' + key] = v
    return out

RKEYS = ['rFonts.ascii', 'rFonts.hAnsi', 'rFonts.eastAsia', 'sz', 'color.val', 'b', 'i', 'u', 'spacing']
PKEYS = ['jc', 'ind.firstLine', 'ind.hanging', 'ind.left', 'ind.right', 'spacing.line', 'spacing.lineRule',
         'spacing.before', 'spacing.after', 'keepNext', 'keepLines', 'pageBreakBefore', 'widowControl']

class Inspector:
    def __init__(self, package):
        self.z = package
        self.warnings = set()
        self.invalid_styles = set()
        self.styles_xml = self.xml('word/styles.xml')
        self.styles = {s.get(W + 'styleId'): s for s in self.styles_xml.findall('w:style', NS)}
        self.defaults = {k: next((sid for sid, s in self.styles.items()
                         if s.get(W + 'type') == k and s.get(W + 'default') == '1'), None)
                         for k in ['paragraph', 'character', 'table']}
        self.theme = self.xml('word/theme/theme1.xml')
        self.numbering = self.xml('word/numbering.xml')

    def xml(self, name):
        if name not in self.z.namelist():
            return ET.Element('empty')
        data = self.z.read(name)
        if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
            raise ValueError('DTD/entity declarations are not supported')
        return ET.fromstring(data)

    def chain(self, sid):
        result, seen = [], set()
        while sid:
            if sid in seen:
                self.invalid_styles.update(seen)
                self.warnings.add('style_cycle:' + sid)
                break
            seen.add(sid)
            s = self.styles.get(sid)
            if s is None:
                self.invalid_styles.update(seen)
                self.warnings.add('missing_style:' + sid)
                break
            result.append((sid, s))
            sid = val(s, 'w:basedOn')
        return result[::-1]

    def cascade(self, kind, sid, direct=None, character=None, table=None):
        default = find(self.styles_xml, f'w:docDefaults/w:{kind}PrDefault/w:{kind}Pr')
        layers = [('word/styles.xml/docDefaults/' + kind + 'Pr', default, False)]
        if table:
            for tid, t in self.chain(table):
                layers.append((f'word/styles.xml/style[{tid}]/{kind}Pr', find(t, 'w:' + kind + 'Pr'), True))
        for tid, s in self.chain(sid):
            layers.append((f'word/styles.xml/style[{tid}]/{kind}Pr', find(s, 'w:' + kind + 'Pr'), True))
        if kind == 'r' and character:
            for tid, s in self.chain(character):
                layers.append((f'word/styles.xml/style[{tid}]/rPr', find(s, 'w:rPr'), True))
        layers.append(('direct', direct, False))
        out = {}
        for source, node, style_layer in layers:
            props = properties(node, kind)
            # A font/theme choice supersedes the lower-layer choice as a pair.
            for literal, themed in [('ascii', 'asciiTheme'), ('hAnsi', 'hAnsiTheme'), ('eastAsia', 'eastAsiaTheme'), ('cs', 'cstheme')]:
                for current, opposite in [(literal, themed), (themed, literal)]:
                    if 'rFonts.' + current in props:
                        out.pop('rFonts.' + opposite, None)
            if 'color.val' in props and 'color.themeColor' not in props:
                for key in ['color.themeColor', 'color.themeTint', 'color.themeShade']:
                    out.pop(key, None)
            for key, value in props.items():
                previous = out.get(key)
                if key in ['b', 'bCs', 'i', 'iCs'] and style_layer:
                    enabled = value not in ['0', 'false', 'off']
                    old = previous and previous['value'] not in ['0', 'false', 'off']
                    if enabled:
                        value = 'false' if old else 'true'
                    elif previous:
                        continue  # style-level false is not a toggle
                out[key] = record(value, source, 'explicit' if source == 'direct' else 'inherited')
        for key in (RKEYS if kind == 'r' else PKEYS):
            out.setdefault(key, record())
        if table:
            # Conditional table styles depend on tblLook, grid position, merges and precedence.
            if any(s.find('w:tblStylePr', NS) is not None for _, s in self.chain(table)):
                for item in out.values():
                    if item['source'] != 'direct':
                        item.update(status='unknown', reason='conditional_table_style_not_resolved')
        if any(s in self.invalid_styles for s in [sid, character, table]):
            # Do not claim a partial style chain is a fully resolved effective value.
            for item in out.values():
                if item['source'] != 'direct' and item['value'] is not None:
                    item.update(status='unknown', reason='incomplete_style_graph')
        if kind == 'r':
            for slot, theme_slot in [('ascii', 'asciiTheme'), ('hAnsi', 'hAnsiTheme'), ('eastAsia', 'eastAsiaTheme')]:
                key = 'rFonts.' + slot
                theme_value = out.get('rFonts.' + theme_slot)
                if theme_value:
                    token = theme_value['value']
                    family = 'majorFont' if token.startswith('major') else 'minorFont' if token.startswith('minor') else None
                    script = 'latin' if token.endswith('Ascii') or token.endswith('HAnsi') else 'ea'
                    font = find(self.theme, f'a:themeElements/a:fontScheme/a:{family}/a:{script}') if family else None
                    resolved = attrs(font).get('typeface')
                    out[key] = record(resolved or None, theme_value['source'], 'theme_resolved' if resolved else 'unknown',
                                      theme_token=token, theme_source='word/theme/theme1.xml',
                                      reason='theme_slot_only; script-specific fallback not inferred')
            c = out.get('color.themeColor')
            if c:
                out['color.val'] = record(None, c['source'], 'unknown', theme_token=c['value'], reason='theme_color_not_resolved')
        return out

    def role(self, p, sid, fmt):
        t = text(p).strip()
        if re.fullmatch(r'(?:\d+[.、]?\s*)?(?:参\s*考\s*文\s*献|references)\s*[:：]?', t, re.I):
            return 'references_heading', 'text_marker'
        names = [(val(s, 'w:name') or '').lower() for _, s in self.chain(sid)]
        if any(n in ['title', '标题'] for n in names):
            return 'title', 'style'
        level = fmt.get('outlineLvl', {}).get('value')
        if level in ['0', '1', '2']:
            return 'heading_' + str(int(level) + 1), 'outline_level'
        for name in names[::-1]:
            m = re.fullmatch(r'(?:heading|标题)\s*([1-3])', name)
            if m:
                return 'heading_' + m[1], 'style'
        t = text(p).strip()
        if re.fullmatch(r'(?:\d+[.、]?\s*)?(?:参\s*考\s*文\s*献|references)\s*[:：]?', t, re.I):
            return 'references_heading', 'text_marker'
        if re.match(r'^(图|Fig(?:ure)?\.?)[\s\d０-９一二三四五六七八九十]', t, re.I):
            return 'figure_caption', 'text_pattern_candidate'
        if re.match(r'^(表|Table)[\s\d０-９一二三四五六七八九十]', t, re.I):
            return 'table_caption', 'text_pattern_candidate'
        return 'body', 'unclassified_nonempty' if t else 'empty'

    def numbering_info(self, fmt, p):
        nid = fmt.get('numPr.numId', {}).get('value')
        level = fmt.get('numPr.ilvl', {}).get('value') or '0'
        if nid and nid != '0':
            num = next((n for n in self.numbering.findall('w:num', NS) if n.get(W+'numId') == nid), None)
            aid = val(num, 'w:abstractNumId')
            abstract = next((a for a in self.numbering.findall('w:abstractNum', NS) if a.get(W+'abstractNumId') == aid), None)
            lvl = next((n for n in ([] if abstract is None else abstract.findall('w:lvl', NS)) if n.get(W+'ilvl') == level), None)
            override = None if num is None else next((n for n in num.findall('w:lvlOverride', NS) if n.get(W+'ilvl') == level), None)
            if find(override, 'w:lvl') is not None:
                lvl = find(override, 'w:lvl')
            return record({'numId': nid, 'level': level, 'format': val(lvl, 'w:numFmt'),
                           'level_pPr': properties(find(lvl, 'w:pPr'), 'p')}, 'word/numbering.xml',
                          'extracted' if lvl is not None else 'unknown')
        t = text(p).strip()
        return record('[n]' if re.match(r'^\[\d+\]', t) else 'n.' if re.match(r'^\d+[.、]', t) else None,
                      'paragraph_prefix_pattern', 'candidate')

    def analyze(self):
        d = self.xml('word/document.xml')
        if d.tag != W + 'document':
            raise ValueError('Missing document.xml or unsupported OOXML namespace')
        parents = {c: p for p in d.iter() for c in p}
        def ancestor(e, tag):
            while e in parents:
                e = parents[e]
                if e.tag == W + tag:
                    return e
            return None
        table_nodes = list(d.iter(W+'tbl'))
        paragraph_nodes = list(d.iter(W+'p'))
        paragraph_indices = {p: i for i,p in enumerate(paragraph_nodes)}
        paragraphs, equations, images = [], [], []
        ref_mode = False
        for index, p in enumerate(paragraph_nodes):
            loc = f'word/document.xml/p[{index}]'
            sid = val(p, 'w:pPr/w:pStyle') or self.defaults['paragraph']
            table_node = ancestor(p, 'tbl')
            table_sid = val(table_node, 'w:tblPr/w:tblStyle') or (self.defaults['table'] if table_node is not None else None)
            pf = self.cascade('p', sid, find(p, 'w:pPr'), table=table_sid)
            role, evidence = self.role(p, sid, pf)
            if role == 'references_heading':
                ref_mode = True
            elif role.startswith('heading_') or role == 'title':
                ref_mode = False
            elif ref_mode and text(p).strip():
                role, evidence = 'reference_entry', 'following_references_heading_candidate'
            runs = []
            for ri, r in enumerate(p.iter(W+'r')):
                # Nested text-box paragraphs have their own record.
                if ancestor(r, 'p') is not p:
                    continue
                if find(r, 'w:t') is None:
                    continue
                rf = self.cascade('r', sid, find(r, 'w:rPr'), val(r, 'w:rPr/w:rStyle'), table_sid)
                for group in [rf]:
                    for item in group.values():
                        if item['source'] == 'direct': item['source'] = loc + f'/r[{ri}]/rPr'
                runs.append({'run_index': ri, 'format': rf})
            for item in pf.values():
                if item['source'] == 'direct': item['source'] = loc + '/pPr'
            rec = {'index': index, 'source': loc, 'style_id': sid, 'role': role, 'role_status': evidence,
                   'in_table': table_node is not None, 'nonempty': bool(text(p).strip()), 'paragraph': pf, 'runs': runs}
            if role == 'reference_entry':
                rec['numbering'] = self.numbering_info(pf, p)
            paragraphs.append(rec)
            maths = list(p.iter('{' + NS['m'] + '}oMath'))
            if maths:
                outside = ''.join(e.text or '' for r in p.findall('w:r', NS) for e in r.iter(W+'t'))
                equations.append({'paragraph_index': index, 'objects': len(maths),
                                  'display': bool(list(p.iter('{' + NS['m'] + '}oMathPara'))),
                                  'number_pattern': record('(n)' if re.search(r'[（(]\d+(?:[.\-]\d+)*[)）]\s*$', outside) else None,
                                                           loc, 'candidate'), 'paragraph': pf,
                                  'math_paragraph_properties': [{x.tag.split('}')[-1]:attrs(x)} for mp in p.iter('{' + NS['m'] + '}oMathParaPr') for x in mp],
                                  'content_exported': False})
            for drawing in p.findall('.//w:drawing', NS):
                if not drawing.findall('.//a:blip', NS):
                    continue
                extent = drawing.find('.//wp:extent', NS)
                images.append({'paragraph_index': index, 'kind': 'drawingml', 'legacy_object_preview': ancestor(drawing, 'object') is not None, 'blip_count': len(drawing.findall('.//a:blip', NS)),
                               'extent_emu': record(attrs(extent) or None, loc, 'explicit' if extent is not None else 'unknown'),
                               'floating': drawing.find('wp:anchor', NS) is not None})
            for pict in p.findall('.//w:pict', NS):
                for shape in pict.findall('.//v:shape', NS):
                    if shape.find('v:imagedata', NS) is not None:
                        dims = {k.strip(): v.strip() for item in shape.get('style', '').split(';') if ':' in item for k,v in [item.split(':',1)] if k.strip() in ['width','height']}
                        images.append({'paragraph_index': index, 'kind': 'vml', 'legacy_object_preview': ancestor(shape, 'object') is not None, 'dimensions': record(dims or None, loc), 'floating': True})
        sections = []
        for i, sec in enumerate(d.iter(W+'sectPr')):
            loc = f'word/document.xml/sectPr[{i}]'
            page = attrs(find(sec, 'w:pgSz')); margin = attrs(find(sec, 'w:pgMar'))
            sections.append({'index': i, 'break_type': record(val(sec, 'w:type'), loc),
                             'page': {k: record(page.get(k), loc+'/pgSz') for k in ['w','h','orient']},
                             'margins': {k: record(margin.get(k), loc+'/pgMar') for k in ['top','bottom','left','right','header','footer','gutter']},
                             'columns': record(attrs(find(sec, 'w:cols')) or None, loc+'/cols'),
                             'grid': record(attrs(find(sec, 'w:docGrid')) or None, loc+'/docGrid')})
        tables = []
        for ti, t in enumerate(table_nodes):
            sid = val(t, 'w:tblPr/w:tblStyle') or self.defaults['table']
            layers = [(f'word/styles.xml/style[{s}]', find(node, 'w:tblPr')) for s,node in self.chain(sid)]
            layers.append((f'word/document.xml/tbl[{ti}]/tblPr', find(t, 'w:tblPr')))
            tf = {}
            for loc, prop in layers:
                if prop is not None:
                    for e in prop:
                        if e.tag == W+'tblBorders':
                            for border in e:
                                tf['borders.'+border.tag.split('}')[-1]] = record(attrs(border),loc+'/tblBorders')
                        elif e.tag.split('}')[-1] in ['tblW','jc','tblLayout','tblLook','tblInd','tblCellMar']:
                            tf[e.tag.split('}')[-1]] = record(attrs(e),loc)
            rows = []
            for row_index, row in enumerate(t.findall('w:tr', NS)):
                cells=[]
                for cell_index, cell in enumerate(row.findall('w:tc', NS)):
                    cp=find(cell,'w:tcPr')
                    cell_source=f'word/document.xml/tbl[{ti}]/tr[{row_index}]/tc[{cell_index}]'
                    cells.append({'width':record(attrs(find(cp,'w:tcW')) or None,cell_source+'/tcPr/tcW'),
                                  'vertical_align':record(val(cp,'w:vAlign'),cell_source+'/tcPr/vAlign'),
                                  'grid_span':record(val(cp,'w:gridSpan'),cell_source+'/tcPr/gridSpan'),
                                  'vertical_merge':record(attrs(find(cp,'w:vMerge')).get('val','continue') if find(cp,'w:vMerge') is not None else None,cell_source+'/tcPr/vMerge'),
                                  'horizontal_merge':record(attrs(find(cp,'w:hMerge')).get('val','continue') if find(cp,'w:hMerge') is not None else None,cell_source+'/tcPr/hMerge'),
                                  'borders':{b.tag.split('}')[-1]:record(attrs(b),cell_source+'/tcPr/tcBorders') for b in ([] if find(cp,'w:tcBorders') is None else find(cp,'w:tcBorders'))},
                                  'paragraph_indices':[paragraph_indices[p] for p in cell.findall('w:p',NS)]})
                rows.append({'repeat_header':record(val(row,'w:trPr/w:tblHeader') or ('true' if find(row,'w:trPr/w:tblHeader') is not None else None),f'word/document.xml/tbl[{ti}]/tr[{row_index}]/trPr/tblHeader'),
                             'grid_before':record(val(row,'w:trPr/w:gridBefore'),f'word/document.xml/tbl[{ti}]/tr[{row_index}]/trPr/gridBefore'), 'cells':cells})
            tp=[paragraph_indices[p] for p in t.iter(W+'p')]
            candidates=[p['index'] for p in paragraphs if p['role']=='table_caption' and tp and min(abs(p['index']-min(tp)),abs(p['index']-max(tp)))<=2]
            tables.append({'caption_relation': record({'candidates':candidates, 'position':'above' if len(candidates)==1 and candidates[0]<min(tp) else 'below' if len(candidates)==1 and candidates[0]>max(tp) else None},f'word/document.xml/tbl[{ti}]','candidate',reason='XML proximity only; not rendered layout'), 'index':ti,'style_id':sid,'row_count':len(rows),
                           'grid_columns_twips':[attrs(c).get('w') for c in t.findall('w:tblGrid/w:gridCol',NS)],
                           'properties':tf,'rows':rows,'appearance_status':'unknown: cell/conditional borders may override table borders',
                           'conditional_styles':[{ 'condition':attrs(c).get('type'),
                                                   'paragraph':properties(find(c,'w:pPr'),'p'), 'run':properties(find(c,'w:rPr'),'r'),
                                                   'borders':{b.tag.split('}')[-1]:attrs(b) for b in c.findall('w:tcPr/w:tcBorders/*',NS)}}
                                                 for _,s in self.chain(sid) for c in s.findall('w:tblStylePr',NS)]})
        for image in images:
            pi=image['paragraph_index']
            candidates=[p['index'] for p in paragraphs if p['role']=='figure_caption' and abs(pi-p['index'])<=2]
            image['caption_relation']=record({'candidates':candidates,'position':'below' if len(candidates)==1 and candidates[0]>pi else 'above' if len(candidates)==1 else None},
                                             f'word/document.xml/p[{pi}]','candidate',reason='XML proximity only; floating/page layout not resolved')
        styles=[]
        for sid,s in self.styles.items():
            names=(val(s,'w:name') or '').lower()
            if re.fullmatch(r'(?:heading|标题)\s*[1-3]|title|标题',names):
                styles.append({'style_id':sid,'role_name':names,'defined_only':not any(p['style_id']==sid for p in paragraphs),
                               'paragraph':self.cascade('p',sid),'run':self.cascade('r',sid)})
        def summary(role):
            candidates=[p for p in paragraphs if p['role']==role and p['nonempty'] and not p['in_table']]
            counts=Counter(p['style_id'] for p in candidates)
            if not counts: return record(None,status='unknown',reason='no_reliable_matching_paragraph')
            selected=counts.most_common(1)[0][0]
            return record({'style_id':selected,'paragraph_indices':[p['index'] for p in candidates if p['style_id']==selected],
                           'all_style_counts':dict(counts)},'paragraph_inventory','candidate',reason='most frequent classified style; per-run variation retained')
        ignored=[n for n in self.z.namelist() if re.match(r'word/(header|footer|footnotes|endnotes|comments).*\.xml$',n)]
        self.warnings.update(['No rendered layout/font availability verification',
                              'Numbering-level paragraph formatting retained separately, not merged into effective paragraph format',
                              'Paragraph style rPr affects text; paragraph mark rPr is not applied to text runs',
                              'Unclassified paragraphs are body candidates, not proven body text',
                              'Legacy OLE objects are not decoded; preview images are not independent experimental images',
                              'DrawingML image occurrences may include groups; no media or relationship targets exported',
                              'Header/footer/notes/comments parts are listed but not analyzed; text boxes may be inventoried without layout resolution'])
        return {'schema_version':'1.0','source_role':'user_reference_style','priority':4,
                'pages':sections,'paragraphs':paragraphs,'tables':tables,'images':images,'equations':equations,
                'heading_definitions':styles,'profiles':{r:summary(r) for r in ['body','title','heading_1','heading_2','heading_3','figure_caption','table_caption','references_heading','reference_entry']},
                'counts':{'paragraphs':len(paragraphs),'tables':len(tables),'image_occurrences':len(images),'math_objects':sum(x['objects'] for x in equations),
                          'legacy_embedded_objects':len(list(d.iter(W+'object')))},
                'scope':{'analyzed':'word/document.xml including table paragraphs','not_analyzed_parts':ignored},
                'uncertainties':sorted(self.warnings), 'content_exported':False,
                'skill_defaults':{k:record(v,'Skill custom convention','default') for k,v in {
                    'body.font.eastAsia':'宋体','body.font.latin':'Times New Roman','body.size_pt':10.5,
                    'body.color':'000000','page.size':'A4','caption.figure.position':'below','caption.table.position':'above'}.items()}}

def inspect(path):
    path=Path(path)
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    with ZipFile(path,'r') as z:
        if sum(i.file_size for i in z.infolist())>100_000_000:
            raise ValueError('Package exceeds 100 MB uncompressed limit')
        result=Inspector(z).analyze()
    after=hashlib.sha256(path.read_bytes()).hexdigest()
    if before!=after: raise ValueError('Source changed during inspection')
    result['source']={'file':path.name,'sha256_before':before,'sha256_after':after,'unchanged':True}
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('docx',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(PROJECT) or output==args.docx.resolve() or output.suffix.lower()!='.json':
        parser.error('Output must be a new JSON file within this project')
    if output.exists(): parser.error('Refusing to overwrite existing output')
    try:
        result=inspect(args.docx)
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('x',encoding='utf-8') as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
        print('Inspection complete; source SHA256 unchanged; no text exported.')
    except (OSError,ValueError,BadZipFile,ET.ParseError) as e:
        parser.exit(1,f'Inspection failed: {type(e).__name__}: {e}\n')

if __name__=='__main__':
    main()
