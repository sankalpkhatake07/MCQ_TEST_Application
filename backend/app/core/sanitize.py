"""HTML sanitiser for rich-text questions (whitelist based, no external deps)."""
import html
import re
from html.parser import HTMLParser

ALLOWED = {"p", "br", "b", "strong", "i", "em", "u", "s", "sub", "sup", "ul", "ol", "li",
           "code", "pre", "blockquote", "h3", "h4", "span", "div", "img"}
VOID = {"br", "img"}
DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math"}
MEDIA_RE = re.compile(r"^/api/media/[a-f0-9]{32}\.(png|jpe?g|gif|webp)$")
LANG_RE = re.compile(r"^language-[a-z0-9+#-]{1,20}$")
HTML_HINT = re.compile(r"<(p|b|i|u|br|code|pre|img|ul|ol|li|strong|em|span|div|blockquote|h3|h4|sub|sup)\b", re.I)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED:
            return
        a = dict(attrs)
        if tag == "img":
            src = (a.get("src") or "").strip()
            if not MEDIA_RE.match(src):
                return
            parts = [f'src="{src}"', f'alt="{html.escape((a.get("alt") or "")[:200], quote=True)}"']
            for k in ("width", "height"):
                v = (a.get(k) or "").strip()
                if v.isdigit() and 0 < int(v) <= 2000:
                    parts.append(f'{k}="{int(v)}"')
            self.out.append("<img " + " ".join(parts) + ">")
            return
        cls = ""
        if tag in ("code", "pre") and LANG_RE.match((a.get("class") or "").strip()):
            cls = f' class="{a["class"].strip()}"'
        self.out.append(f"<{tag}{cls}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in DROP_CONTENT:
            return
        self.handle_starttag(tag, attrs)
        if tag in ALLOWED and tag not in VOID and tag in self.stack:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED or tag in VOID or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize_html(raw: str) -> str:
    p = _Sanitizer()
    p.feed(raw or "")
    p.close()
    return p.result()


def plain_to_html(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    paras = [x for x in re.split(r"\n\s*\n", text) if x.strip()]
    return "".join("<p>" + html.escape(x.strip()).replace("\n", "<br>") + "</p>" for x in paras)


def to_rich(text: str) -> str:
    """Accepts plain text or HTML; always returns safe HTML."""
    text = text or ""
    return sanitize_html(text) if HTML_HINT.search(text) else plain_to_html(text)


class _Stripper(HTMLParser):
    BLOCK = {"p", "br", "div", "li", "h3", "h4", "pre", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, d):
        if not self.skip:
            self.parts.append(d)


def strip_tags(raw: str) -> str:
    s = _Stripper()
    s.feed(raw or "")
    s.close()
    return re.sub(r"\n{2,}", "\n", "".join(s.parts)).strip()
