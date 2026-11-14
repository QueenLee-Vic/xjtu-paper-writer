"""Display-only output encoding. Never apply these functions to source documents.

Markdown data uses fixed code elements, entity encoding and reversible control
escapes. HTML text is a different context. JSON remains json.dumps/json.dump.
"""
import json
import html

def preview_text(value, context='paragraph'):
    """Encode untrusted data as literal text, never as Markdown syntax.

    Entity decoding occurs after Markdown block/inline recognition. Encode '&'
    too so user entities cannot become a second layer of HTML. Keep raw data in
    JSON unchanged. Code display uses a fixed HTML code element, not user fences.
    """
    import string, re
    if context not in ('table', 'paragraph', 'code'):
        raise ValueError('Unknown preview text context')
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    # Visible reversible control escapes survive renderers normalizing CR/LF.
    text = text.replace('\\', '\\\\').replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t')
    # Markdown renderers may collapse repeated spaces; retain their count visibly.
    text = re.sub(r' {2,}', lambda m: '\\s' * len(m[0]), text)
    encoded = ''.join('&#'+str(ord(c))+';' if c in string.punctuation or (c.isspace() and c != ' ') else c for c in text)
    # Fixed wrapper supplies code styling; smart typography is renderer-dependent.
    return '<code>'+encoded+'</code>'


def html_text(value):
    """HTML text-node context only; not attributes, scripts or Markdown."""
    return html.escape(str(value), quote=True)
