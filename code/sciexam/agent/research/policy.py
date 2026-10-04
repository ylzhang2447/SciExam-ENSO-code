"""The decision rules of the web research proxy, as pure functions.

This module has no dependency on mitmproxy, so every rule is an ordinary unit test: the
addon (``addon.py``) only feeds it requests and bodies and acts on the answer. It is loaded
two ways, as ``sciexam.agent.research.policy`` on the host and as the plain module
``policy`` next to the addon inside the proxy container, so it imports nothing from the
package.

Three inputs configure it, all JSON:

* the policy of the condition (``policies/<name>.json``): host, path and request-shape
  rules, the data-source refusal of the literature-only condition, TLS passthrough hosts;
* the fingerprints of the prohibited works (``fingerprints/works.json``): the works the task
  blacklist names, stored as sha256 hashes of their normalised identifiers, titles and
  signature phrases, never as text;
* the content fingerprints (``fingerprints/content.json``): hashes of twelve-word runs from
  separate regions of a prohibited work's body, which recognise a copy of its text under any
  URL or metadata.

What the rules refuse:

1. a prohibited work, by an identifier in the URL, by the document's own identity (its title,
   its identifier, its scholarly metadata) or by reproducing its text. A document that only
   CITES a prohibited work is served, so ordinary ENSO literature stays readable;
2. the benchmark's own public pages (user supplied, see ``benchmark_self.json``), wherever
   any of their text appears;
3. anything that resolves to a private or internal address (checked in the addon);
4. anything that could carry workspace contents out: methods other than GET and HEAD, a
   request body, oversized or high-entropy URLs and headers, text shaped like a file, and
   eight-word runs of the arm's own task files;
5. with ``data_hosts``, ``data_url_substrings`` and ``data_extensions`` set (literature-only
   condition), observational data sources, judged by source and never by body;
6. anything that cannot be decoded and inspected in full: archives, opaque binaries,
   encrypted or partly unreadable PDFs.
"""
import hashlib
import json
import math
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET

try:
    from pypdf import PdfReader
    PDF_OK = True
except Exception:
    PDF_OK = False           # without a reader a PDF cannot be inspected, so it is refused

TEXT_MIME = ("html", "xml", "json", "text", "plain", "javascript", "csv", "rss", "atom",
             "yaml", "markdown", "x-www-form-urlencoded")
ARCHIVE_MAGIC = (b"PK\x03\x04", b"\x1f\x8b", b"BZh", b"\xfd7zXZ", b"Rar!", b"7z\xbc\xaf")
ARCHIVE_ANYWHERE = (b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b\x08", b"BZh9", b"7z\xbc\xaf\x27\x1c",
                    b"Rar!\x1a\x07", b"\xfd7zXZ\x00", b"ustar\x00", b"ustar  \x00",
                    b"%PDF-", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8", b"\x00asm")
MAX_PDF_PAGES = 600


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---- normalisation -----------------------------------------------------------------------

DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")
QUOTES = dict.fromkeys(map(ord, "\u2018\u2019\u201a\u201b\u2032"), "'")
DQUOTES = dict.fromkeys(map(ord, "\u201c\u201d\u201e\u2033"), '"')


def normalize_words(text):
    """NFKC, unicode punctuation folded to ASCII, lowercased, every run of characters other
    than a-z and 0-9 treated as a word break. Fingerprints are hashes of this form."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(DASHES).translate(QUOTES).translate(DQUOTES).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).split()


def phrase_fingerprint(text):
    """The stored form of a title or phrase: word count and sha256 of the normalised words,
    and length and sha256 of the same words joined without spaces."""
    words = normalize_words(text)
    squashed = "".join(words)
    return {"words": len(words), "sha256": sha256_text(" ".join(words)),
            "chars": len(squashed), "squashed_sha256": sha256_text(squashed)}


def normalize_url(url):
    """One spelling per resource: lowercase scheme and host, no fragment, no tracking
    parameters, no trailing slash, sorted query."""
    u = urllib.parse.urlsplit(url.strip())
    host = (u.hostname or "").lower().rstrip(".")
    path = re.sub(r"/+$", "", u.path or "")
    qs = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
          if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref"))]
    q = urllib.parse.urlencode(sorted(qs))
    return ("%s://%s%s%s" % ((u.scheme or "https").lower(), host, path,
                             ("?" + q) if q else "")).lower()


_ARXIV = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def ids_in(text):
    """arXiv identifiers and DOIs appearing anywhere in a string (lowercase)."""
    ax = {m.group(1) for m in _ARXIV.finditer(text)}
    doi = {m.group(0).rstrip(".,);").lower() for m in _DOI.finditer(text)}
    return ax, doi


class TextIndex:
    """Hashes of the identifiers and word runs of one text, for matching hashed fingerprints.

    A fingerprint matches when the text contains its identifier or its words as a substring
    (identifiers) or as consecutive normalised words (titles, phrases). Runs are hashed once
    per length and reused for every work.
    """

    def __init__(self, text):
        self.low = (text or "").lower()
        self.words = normalize_words(text)
        self._runs = {}
        self._squashed = None
        self.arxiv = set()
        for m in re.finditer(r"(?=(\d{4}\.\d{4}))(?=(\d{4}\.\d{5})?)", self.low):
            self.arxiv.add(sha256_text(m.group(1)))
            if m.group(2):
                self.arxiv.add(sha256_text(m.group(2)))
        self._doi_starts = [m.start() for m in re.finditer(r"10\.\d", self.low)]

    def has_run(self, n, digest):
        if n <= 0:
            return False
        if n not in self._runs:
            w = self.words
            self._runs[n] = {sha256_text(" ".join(w[i:i + n]))
                             for i in range(0, max(0, len(w) - n + 1))}
        return digest in self._runs[n]

    def has_squashed(self, chars, digest):
        if self._squashed is None:
            self._squashed = "".join(self.words)
        s = self._squashed
        return any(sha256_text(s[i:i + chars]) == digest
                   for i in range(0, max(0, len(s) - chars + 1)))

    def has_arxiv(self, digests):
        return bool(self.arxiv.intersection(digests))

    def has_doi(self, entries):
        for e in entries:
            n = int(e["chars"])
            if any(sha256_text(self.low[i:i + n]) == e["sha256"] for i in self._doi_starts):
                return True
        return False

    def has_title(self, entries, squashed=True):
        for e in entries:
            if self.has_run(int(e["words"]), e["sha256"]):
                return True
            if squashed and self.has_squashed(int(e["chars"]), e["squashed_sha256"]):
                return True
        return False

    def has_phrase(self, entries):
        return any(self.has_run(int(e["words"]), e["sha256"]) for e in entries)

    def names_work(self, w):
        """True if this text contains one of the work's identifiers."""
        return self.has_arxiv(w.get("arxiv", [])) or self.has_doi(w.get("doi", []))


# ---- the prohibited works ----------------------------------------------------------------

SELF_ID = "benchmark_self"


def self_phrases(policy):
    """The user-supplied text of the benchmark's own pages, lowercased (see benchmark_self)."""
    s = policy.get("benchmark_self") or {}
    return [p.lower() for p in (s.get("phrases") or []) if p and p.strip()]


def _self_mentioned(low, policy):
    low = " ".join((low or "").lower().split())
    return any(p in low for p in self_phrases(policy))


def prohibited_by_identifier(url, FP):
    """(work_id, evidence) when the URL names a prohibited work by arXiv id or DOI."""
    idx = TextIndex(normalize_url(url))
    for w in FP["works"]:
        if idx.has_arxiv(w.get("arxiv", [])):
            return w["id"], "the URL carries the arXiv identifier of a prohibited work"
        if idx.has_doi(w.get("doi", [])):
            return w["id"], "the URL carries the DOI of a prohibited work"
    return None, None


# ---- decoding ----------------------------------------------------------------------------

def _pdf_has_attachments(reader):
    try:
        if getattr(reader, "attachments", None):
            return True
    except Exception:
        return True
    try:
        root = reader.trailer["/Root"]
        names = root.get("/Names")
        if names and names.get_object().get("/EmbeddedFiles"):
            return True
        if root.get("/Collection"):
            return True
        for page in reader.pages:
            for annot in (page.get("/Annots") or []):
                if annot.get_object().get("/Subtype") == "/FileAttachment":
                    return True
    except Exception:
        pass
    return False


def pdf_text(body, max_pages=None):
    """The complete text of a PDF (metadata first), or None to refuse it.

    Refused: encrypted documents, documents with embedded files, more than MAX_PDF_PAGES
    pages, any page that yields no text, and fewer than 200 characters in total.
    """
    if not PDF_OK:
        return None
    import io
    cap = int(max_pages or MAX_PDF_PAGES)
    try:
        r = PdfReader(io.BytesIO(body))
        if getattr(r, "is_encrypted", False) or _pdf_has_attachments(r):
            return None
        pages = list(r.pages)
        if not pages or len(pages) > cap:
            return None
        text = []
        for page in pages:
            t = page.extract_text()
            if not t or len(" ".join(t.split())) < 8:
                return None
            text.append(t)
        if len(" ".join(" ".join(text).split())) < 200:
            return None
        try:
            meta = [" ".join(str(v) for v in (r.metadata or {}).values() if v)]
        except Exception:
            meta = []
        return "\n".join(meta + text)
    except Exception:
        return None


def sniff(body):
    """'empty', 'pdf', 'archive', 'embedded', 'opaque' or 'text', judged on the whole body.

    Text must decode as strict UTF-8, contain no NUL, be at least 99% printable and carry no
    archive, image or PDF signature anywhere.
    """
    if not body:
        return "empty"
    if body[:5] == b"%PDF-":
        return "pdf"
    if body.startswith(ARCHIVE_MAGIC) or body[257:262] == b"ustar":
        return "archive"
    if b"\x00" in body:
        return "opaque"
    try:
        t = body.decode("utf-8")
    except UnicodeDecodeError:
        return "opaque"
    if any(magic in body for magic in ARCHIVE_ANYWHERE):
        return "embedded"
    if sum(ch.isprintable() or ch in "\r\n\t" for ch in t) < len(t) * 0.99:
        return "opaque"
    return "text"


def readable_text(body, mime, url):
    """(text, kind). Only 'pdf' and 'text' with a text that is not None can be delivered."""
    if not body:
        return "", "empty"
    kind = sniff(body)
    if kind in ("archive", "embedded", "opaque"):
        return None, kind
    if kind == "pdf":
        return pdf_text(body), "pdf"
    if "pdf" in (mime or "").lower() or normalize_url(url).endswith(".pdf"):
        return None, "opaque"
    return body.decode("utf-8"), "text"


def decode_body(raw, content_encoding):
    """(bytes, None) with the content encoding removed, or (None, reason)."""
    enc = (content_encoding or "").strip().lower()
    if not enc or enc in ("identity", "none"):
        return raw, None
    try:
        if enc in ("gzip", "x-gzip"):
            import gzip
            return gzip.decompress(raw), None
        if enc == "deflate":
            import zlib
            try:
                return zlib.decompress(raw), None
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS), None
        if enc == "br":
            import brotli
            return brotli.decompress(raw), None
        if enc == "zstd":
            import zstandard
            return zstandard.ZstdDecompressor().decompressobj().decompress(raw), None
    except Exception as e:
        return None, "%s content that could not be decoded here (%s)" % (enc, type(e).__name__)
    return None, "unknown content encoding %s" % enc[:40]


# ---- document identity -------------------------------------------------------------------

META_TITLE_KEYS = ("citation_title", "dc.title", "og:title", "twitter:title", "prism.title",
                   "eprints.title", "bepress_citation_title")
META_ID_KEYS = ("citation_doi", "citation_arxiv_id", "citation_arxiv_doi", "dc.identifier",
                "dc.identifier.doi", "prism.doi", "bepress_citation_doi", "eprints.doi")
META_URL_KEYS = ("og:url", "citation_public_url", "citation_abstract_html_url",
                 "citation_pdf_url", "dc.source", "bepress_citation_pdf_url")
SELF_STAMP = re.compile(r"arxiv[:\s]*(\d{4}\.\d{4,5})(?:v\d+)?\s*\[[a-z-]+\.[a-z-]+\]", re.I)
TITLE_SIZE_RATIO = 1.25
TITLE_MIN_CHARS = 20
TITLE_MAX_CHARS = 300
TITLE_TOP_FRACTION = 0.62


def _pdf_self_stamp(page):
    """arXiv identifiers drawn ROTATED on page one: the arXiv stamp of the document itself.
    Upright text is ordinary prose wherever it sits and takes no part in identity."""
    found = set()

    def visit(text, _cm, tm, _font, _size):
        t = " ".join((text or "").split())
        if not t or "arxiv" not in t.lower():
            return
        try:
            rotated = abs(float(tm[1])) > 0.01 or abs(float(tm[2])) > 0.01
        except Exception:
            return
        if rotated:
            found.update(m.group(1) for m in SELF_STAMP.finditer(t.lower()))

    try:
        page.extract_text(visitor_text=visit)
    except Exception:
        return set()
    return found


def _layout_title(page):
    """The title as page one sets it: the largest type, clearly larger than the body, at the
    top of the page, in at most four pieces and of a title's length. Otherwise None."""
    runs = {}
    try:
        height = float(page.mediabox.height)
    except Exception:
        height = 792.0

    def visit(text, _cm, tm, _font, size):
        t = " ".join((text or "").split())
        if not t:
            return
        try:
            y = float(tm[5])
        except Exception:
            y = 0.0
        runs.setdefault(round(float(size or 0), 1), []).append((y, t))

    try:
        page.extract_text(visitor_text=visit)
    except Exception:
        return None
    sizes = [k for k in runs if k > 0]
    if len(sizes) < 2:
        return None
    largest = max(sizes)
    body_size = max((k for k in sizes if k != largest), default=0)
    if not body_size or largest < body_size * TITLE_SIZE_RATIO:
        return None
    pieces = [(y, t) for y, t in runs[largest] if t.strip()]
    if not pieces or len(pieces) > 4 or max(y for y, _t in pieces) < height * TITLE_TOP_FRACTION:
        return None
    title = " ".join(t for _y, t in pieces).strip()
    return title.lower() if TITLE_MIN_CHARS <= len(title) <= TITLE_MAX_CHARS else None


def pdf_front_matter(body):
    """A PDF's own titles and identifiers: the information dictionary, XMP, the layout title
    (only when the metadata states none) and the rotated arXiv stamp."""
    out = {"titles": [], "ids": set()}
    if not PDF_OK:
        return out
    import io
    try:
        r = PdfReader(io.BytesIO(body))
        meta = r.metadata or {}
        if meta.get("/Title"):
            out["titles"].append(" ".join(str(meta["/Title"]).lower().split()))
        for key in ("/Keywords", "/Subject", "/doi", "/DOI", "/WPS-ARTICLEDOI"):
            if meta.get(key):
                ax, doi = ids_in(str(meta[key]).lower())
                out["ids"] |= ax | doi
        try:
            x = r.xmp_metadata
            if x:
                out["titles"] += [" ".join(str(t).lower().split())
                                  for t in (getattr(x, "dc_title", None) or {}).values()]
                for got in (getattr(x, "dc_identifier", None) or []):
                    ax, doi = ids_in(str(got).lower())
                    out["ids"] |= ax | doi
        except Exception:
            pass
        if r.pages:
            if not out["titles"]:
                layout = _layout_title(r.pages[0])
                if layout:
                    out["titles"].append(layout)
            out["ids"] |= _pdf_self_stamp(r.pages[0])
    except Exception:
        return {"titles": [], "ids": set()}
    return out


def document_identity(text, mime="", url="", body=None):
    """What a document says it IS, from structured fields only: an HTML page's <title>,
    scholarly meta tags and canonical link, a PDF's front matter, and the URL it came from.
    Prose in the body is never identity."""
    low = text or ""
    ids, titles = set(), []
    is_pdf = "pdf" in (mime or "").lower() or normalize_url(url).endswith(".pdf")
    if not is_pdf:
        for m in re.finditer(r"""<meta[^>]+(?:name|property)=["']([^"']+)["'][^>]*"""
                             r"""content=["']([^"']*)["']""", low[:400000], re.I):
            key, val = m.group(1).lower(), m.group(2).strip()
            if key in META_TITLE_KEYS:
                titles.append(val)
            if key in META_ID_KEYS:
                ids.add(val.lower())
            if key in META_ID_KEYS or key in META_URL_KEYS:
                ax, doi = ids_in(val.lower())
                ids |= ax | doi
        m = re.search(r"<title[^>]*>(.{0,400}?)</title>", low, re.I | re.S)
        if m:
            titles.append(" ".join(m.group(1).split()))
        m = re.search(r"""<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)["']""",
                      low[:400000], re.I)
        if m:
            ax, doi = ids_in(m.group(1).lower())
            ids |= ax | doi
    elif body:
        front = pdf_front_matter(body)
        titles += front["titles"]
        ids |= front["ids"]
    if url:
        ax, doi = ids_in(normalize_url(url))
        ids |= ax | doi
    ax, doi = ids_in(" ".join(titles).lower())
    ids |= ax | doi
    return {"titles": [" ".join(t.lower().split()) for t in titles if t],
            "ids": {i.lower() for i in ids}}


def scan_content(text, FP, policy, mime="", url="", body=None, CFP=None):
    """Every finding in a document, as (verdict, work_id, why) with verdict 'block' or 'cite'.

    'block' when the document IS a prohibited work (its own title or identifier), reproduces
    its text (content fingerprints), shows the benchmark's own pages, or prints the grader's
    observed event vector. 'cite' when a prohibited work is only mentioned.
    """
    idx = TextIndex(text)
    ident = document_identity(text or "", mime, url, body)
    own_titles = TextIndex(" | ".join(ident["titles"]))
    own_ids = TextIndex(" ".join(sorted(ident["ids"])))
    out = []
    for w in FP["works"]:
        if w.get("title") and own_titles.has_title(w["title"]):
            out.append(("block", w["id"], "the document's own title is this work"))
        elif own_ids.names_work(w):
            out.append(("block", w["id"], "the document identifies itself by this work's identifier"))
        elif idx.names_work(w) or idx.has_title(w.get("title", []), squashed=False) \
                or idx.has_phrase(w.get("phrases", [])):
            out.append(("cite", w["id"], "mentioned, but not as this document's own identity"))
    if _self_mentioned(text, policy):
        out.append(("block", SELF_ID, "this benchmark's own material appears on the page"))
    wid, why = content_leak(text, CFP)
    if wid:
        out.append(("block", wid, "the work's own text is being served here: " + why))
    low = " ".join((text or "").lower().split())
    for rx in FP.get("scored_target_regexes", []):
        if re.search(rx, low, re.I):
            out.append(("block", "scored_targets",
                        "the grader's observed event vector appears verbatim"))
    return out


def content_verdict(text, FP, policy, mime="", url="", body=None, CFP=None):
    """The strongest finding: ('block'|'cite'|None, work_id, why)."""
    findings = scan_content(text, FP, policy, mime, url, body, CFP)
    for level in ("block", "cite"):
        for f in findings:
            if f[0] == level:
                return f
    return None, None, None


# ---- content leakage ---------------------------------------------------------------------

def content_leak(text, CFP):
    """(work_id, evidence) when a body reproduces a prohibited work's text.

    The body's twelve-word runs (normalised, at least eight distinct words) are hashed and
    compared with the fingerprint regions of each work. A copy reproduces at least
    ``min_shingles`` runs from at least ``min_regions`` separate regions; one quoted passage
    falls in a single region and is served.
    """
    if not CFP or not text:
        return None, None
    n = int(CFP.get("shingle_words", 12))
    need = CFP.get("match_threshold", {})
    min_sh, min_rg = int(need.get("min_shingles", 6)), int(need.get("min_regions", 3))
    words = normalize_words(text)
    seen = set()
    for i in range(0, max(0, len(words) - n + 1)):
        run = words[i:i + n]
        if len(set(run)) >= 8:
            seen.add(sha256_text(" ".join(run))[:20])
    for work in CFP.get("works", []):
        hits, regions = set(), 0
        for region in work.get("regions", []):
            matched = seen.intersection(region)
            if matched:
                regions += 1
                hits |= matched
        if len(hits) >= min_sh and regions >= min_rg:
            return work["work_id"], ("%d long passages from %d separate regions of the work"
                                     % (len(hits), regions))
    return None, None


# ---- search listings ---------------------------------------------------------------------

SEARCH_PARAMS = ("q", "query", "search_query", "terms-0-term", "p", "wd", "search", "k")
_XMLNS = re.compile(r'xmlns(?::([A-Za-z0-9_.-]+))?\s*=\s*"([^"]+)"')
_OWN_ID_KEYS = ("id", "doi", "arxiv", "url", "link", "href", "identifier", "pmid",
                "corpusid", "isbn", "guid")
_OWN_TITLE_KEYS = ("title", "name", "headline")
_ID_CONTAINERS = ("externalids", "ids", "identifiers", "openaccesspdf", "primarylocation",
                  "bestoalocation", "locations", "doiurl", "links")
_NEVER_KEYS = ("reference", "citation", "citedby", "cites", "citing", "related",
               "bibliograph", "similar", "abstract", "summary", "body", "fulltext",
               "snippet", "description", "note", "comment")
_RESULT_KEYS = ("data", "items", "results", "hits", "docs", "papers", "entries", "records")


def _norm_key(k):
    return re.sub(r"[^a-z0-9]", "", (k or "").lower())


def listing_kind(text, mime, url, policy):
    """'atom', 'json' or 'html' when the response is a search result list from a listing host
    (a search query or a listing path on one of ``listing_hosts``), else None."""
    n = normalize_url(url)
    u = urllib.parse.urlsplit(n)
    on_host = u.netloc in [h.lower() for h in policy.get("listing_hosts", [])]
    on_path = any(seg in n for seg in policy.get("listing_paths", []))
    has_query = any(k in dict(urllib.parse.parse_qsl(u.query)) for k in SEARCH_PARAMS)
    if not (on_host and (has_query or on_path)):
        return None
    if _atom_root(text or "") is not None:
        return "atom"
    if "json" in (mime or "").lower():
        try:
            doc = json.loads(text or "")
        except Exception:
            return None
        return "json" if _json_result_items(doc) else None
    return "html"


def _atom_root(text):
    """The parsed Atom or RSS feed, or None."""
    if not text or "<" not in text:
        return None
    try:
        for prefix, uri in _XMLNS.findall(text):
            try:
                ET.register_namespace(prefix or "", uri)
            except Exception:
                pass
        root = ET.fromstring(text)
    except Exception:
        return None
    return root if root.tag.rsplit("}", 1)[-1].lower() in ("feed", "rss") else None


def _atom_entries(root):
    out = []
    for child in list(root):
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag == "entry":
            out.append((root, child))
        elif tag == "channel":
            out += [(child, it) for it in list(child)
                    if it.tag.rsplit("}", 1)[-1].lower() == "item"]
    return out


def _atom_own_fields(entry):
    """Identifiers (id, guid, doi, link) and titles from an entry's direct children only."""
    ids, titles = [], []
    for child in list(entry):
        t = child.tag.rsplit("}", 1)[-1].lower()
        if t in ("id", "guid", "doi") and child.text:
            ids.append(child.text.strip())
        elif t == "link":
            href = child.get("href") or (child.text or "")
            if href:
                ids.append(href.strip())
        elif t == "title" and child.text:
            titles.append(" ".join(child.text.split()))
    return ids, titles


def _json_own_fields(item):
    """Identifier and title fields of a JSON result; lists of other works are never entered."""
    ids, titles = [], []
    if not isinstance(item, dict):
        return ids, titles

    def take(node, depth):
        if depth > 2 or not isinstance(node, dict):
            return
        for k, v in node.items():
            nk = _norm_key(k)
            if any(b in nk for b in _NEVER_KEYS):
                continue
            if isinstance(v, dict):
                if any(c in nk for c in _ID_CONTAINERS):
                    take(v, depth + 1)
                continue
            if isinstance(v, list):
                if any(c in nk for c in _ID_CONTAINERS):
                    for x in v:
                        if isinstance(x, dict):
                            take(x, depth + 1)
                        elif isinstance(x, str):
                            ids.append(x)
                continue
            if v is None or isinstance(v, bool):
                continue
            if any(b in nk for b in _OWN_ID_KEYS):
                ids.append(str(v))
            elif any(nk == b or nk.endswith(b) for b in _OWN_TITLE_KEYS):
                titles.append(" ".join(str(v).split()))
    take(item, 0)
    return ids, titles


def _json_result_items(doc):
    items = []

    def walk(node):
        if isinstance(node, list):
            items.extend(x for x in node if isinstance(x, dict))
        elif isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, list) and _norm_key(k) in _RESULT_KEYS:
                    items.extend(x for x in v if isinstance(x, dict))
                elif isinstance(v, dict):
                    walk(v)
    if isinstance(doc, list):
        items.extend(x for x in doc if isinstance(x, dict))
    else:
        walk(doc)
    return items


def listing_entry_identity(entry, kind, FP, policy, CFP=None):
    """(work_id, why) when one search result IS a prohibited work, judged by its own
    identifier, link and title fields. A result that only cites the work in its abstract is
    kept. A result whose own fields cannot be read is removed if it mentions a prohibited
    work, and the benchmark's own text removes a result wherever it appears."""
    if isinstance(entry, str):
        low = entry.lower()
    else:
        try:
            low = (ET.tostring(entry, encoding="unicode") if hasattr(entry, "tag")
                   else json.dumps(entry)).lower()
        except Exception:
            low = ""
    if _self_mentioned(low, policy):
        return SELF_ID, "a work that is out of scope wherever it is mentioned"
    if kind == "atom":
        try:
            if isinstance(entry, str):
                entry = ET.fromstring(entry)
            ids, titles = _atom_own_fields(entry)
        except Exception:
            ids, titles = [], []
    elif kind == "json":
        try:
            ids, titles = _json_own_fields(json.loads(entry) if isinstance(entry, str) else entry)
        except Exception:
            ids, titles = [], []
    else:
        ids, titles = [], []
    id_idx = TextIndex(" ".join(ids).lower())
    title_idx = TextIndex(" | ".join(titles).lower())
    for w in FP.get("works", []):
        if id_idx.names_work(w):
            return w["id"], "this result's own identifier is the prohibited work"
        if titles and (title_idx.has_title(w.get("title", []))
                       or title_idx.has_phrase(w.get("phrases", []))):
            return w["id"], "this result's own title is the prohibited work"
    if not ids and not titles:
        for verdict, wid, _why in scan_content(low, FP, policy, CFP=CFP):
            if verdict in ("block", "cite"):
                return wid, "this result's fields could not be read, so it is not shown to be safe"
    return None, None


def listing_entry_survivors(text, kind, FP, policy, CFP=None):
    """(work_id, why) for every prohibited result still present in a listing body."""
    out = []
    if kind == "atom":
        root = _atom_root(text)
        if root is None:
            return [(wid, "a listing body that cannot be parsed still names it")
                    for v, wid, _w in scan_content(text or "", FP, policy, CFP=CFP)
                    if v in ("block", "cite")]
        for _parent, entry in _atom_entries(root):
            wid, why = listing_entry_identity(entry, "atom", FP, policy, CFP)
            if wid:
                out.append((wid, why))
    elif kind == "json":
        try:
            doc = json.loads(text)
        except Exception:
            return out
        for item in _json_result_items(doc):
            wid, why = listing_entry_identity(item, "json", FP, policy, CFP)
            if wid:
                out.append((wid, why))
    elif kind == "html":
        out = [(wid, "an unstructured result page that names it cannot be cut")
               for v, wid, _w in scan_content(text or "", FP, policy, CFP=CFP)
               if v in ("block", "cite")]
    return out


def remove_listing_entries(text, kind, FP, policy, CFP=None):
    """(text, removed work ids, complete) with every prohibited result removed whole from an
    Atom or JSON listing. complete=False means the format has no result boundary (HTML) or
    did not parse, and the caller withholds the page."""
    removed = []
    if kind == "atom":
        root = _atom_root(text)
        if root is None:
            return text, removed, False
        for parent, entry in _atom_entries(root):
            wid, _why = listing_entry_identity(entry, "atom", FP, policy, CFP)
            if wid:
                removed.append(wid)
                parent.remove(entry)
        try:
            out = ET.tostring(root, encoding="unicode")
        except Exception:
            return text, [], False
        if text.lstrip().startswith("<?xml"):
            out = text[:text.index("?>") + 2] + "\n" + out
        return out, removed, True
    if kind == "json":
        try:
            doc = json.loads(text)
        except Exception:
            return text, removed, False

        def prune(node):
            if isinstance(node, list):
                kept = []
                for item in node:
                    wid = (listing_entry_identity(item, "json", FP, policy, CFP)[0]
                           if isinstance(item, dict) else None)
                    if wid:
                        removed.append(wid)
                    else:
                        kept.append(item)
                return kept
            if isinstance(node, dict):
                return {k: (prune(v) if (isinstance(v, list) and _norm_key(k) in _RESULT_KEYS)
                            or isinstance(v, dict) else v) for k, v in node.items()}
            return node
        return json.dumps(prune(doc)), removed, True
    return text, removed, False


# ---- sources -----------------------------------------------------------------------------

def host_decision(host, policy):
    """(allowed, reason) for a host name. Internal names and the benchmark's own hosts are
    refused; everything else is allowed (addresses are checked separately)."""
    h = (host or "").lower().rstrip(".")
    if h in [x.lower() for x in policy.get("blocked_hostnames", [])]:
        return False, "an internal hostname, not the public web"
    for d in (policy.get("benchmark_self") or {}).get("hosts") or []:
        d = d.lower()
        if h == d or h.endswith("." + d):
            return False, "this benchmark's own surfaces are out of scope"
    return True, None


def url_denied(url, policy):
    """(denied, reason) when the URL contains one of the benchmark's own URL fragments."""
    n = normalize_url(url)
    for frag in (policy.get("benchmark_self") or {}).get("url_substrings") or []:
        if frag and frag.lower() in n:
            return True, "the URL names this benchmark's own material"
    return False, None


def data_source_denied(url, policy):
    """(denied, reason) for an observational data source: a host in ``data_hosts`` (or a
    subdomain of one), a path containing one of ``data_url_substrings``, or a path ending in
    one of ``data_extensions``. Empty lists (literature and data condition) deny nothing."""
    u = urllib.parse.urlsplit(normalize_url(url))
    h = (u.hostname or "").lower().rstrip(".")
    for d in policy.get("data_hosts", []):
        d = d.lower()
        if h == d or h.endswith("." + d):
            return True, "%s serves observational data, and this arm reads mechanisms, not data" % d
    path = (u.path or "").lower()
    for frag in policy.get("data_url_substrings", []):
        if frag.lower() in path:
            return True, "the path names a data endpoint (%s), not a description of a mechanism" % frag
    for ext in policy.get("data_extensions", []):
        if path.endswith(ext.lower()):
            return True, "a %s file is a data series, and this arm reads mechanisms, not data" % ext
    return False, None


# ---- request shape -----------------------------------------------------------------------

_ENTROPY_CHARS = re.compile(r"[A-Za-z0-9+/=_-]{64,}")
_CODE_TOKENS = ("def ", "class ", "import ", "return ", "function(", "#!/", "<?xml", "```",
                "params.json", "model.py", "instruction.md", "np.", "dt_months", "sigma",
                "self.", "= {", "};", "');", '":')


def _looks_like_payload(s, min_run):
    """A run of at least ``min_run`` base64-like characters with at least 3.5 bits of
    entropy per character (an encoded or compressed blob, not words)."""
    for m in _ENTROPY_CHARS.finditer(s or ""):
        run = m.group(0)
        if len(run) < min_run:
            continue
        counts = {}
        for ch in run:
            counts[ch] = counts.get(ch, 0) + 1
        ent = -sum((c / len(run)) * math.log2(c / len(run)) for c in counts.values())
        if ent >= 3.5:
            return True, "a %d character high-entropy run (%.1f bits per character)" % (len(run), ent)
    return False, None


def _looks_like_file_content(v, dense=True):
    """Text shaped like a file rather than a search term: line breaks or tabs, two or more
    code or data tokens, or (``dense``) over 8% brackets, quotes and operators in more than
    120 characters."""
    if not v:
        return False, None
    if "\n" in v or "\r" in v or "\t" in v:
        return True, "line breaks or tabs, which no search term has"
    low = v.lower()
    hits = [t for t in _CODE_TOKENS if t in low]
    if len(hits) >= 2 and len(v) > 40:
        return True, "source or data fragments (%s)" % ", ".join(hits[:3])
    if dense and len(v) > 120 and sum(c in "{}[]()<>;=\"'" for c in v) > len(v) * 0.08:
        return True, "punctuation density of a file, not a query"
    return False, None


def _workspace_hit(v, shingles):
    """True if ``v`` contains an n-word run (n = shingles['n']) of the arm's own task files."""
    if not shingles or not v:
        return False, None
    words = re.findall(r"[a-z0-9_.]+", v.lower())
    n = int(shingles.get("n", 8))
    table = shingles.get("hashes") or set()
    for i in range(0, max(0, len(words) - n + 1)):
        if hashlib.sha256(" ".join(words[i:i + n]).encode()).hexdigest()[:16] in table:
            return True, "an %d word run that appears in this arm's own workspace" % n
    return False, None


def exfiltration_risk(method, url, headers, body, policy, shingles=None):
    """(refuse, reason) for a request that could carry workspace contents outward.

    Allowed: the methods in ``allowed_methods`` with no body, a URL, path, query and header
    set within the size limits, headers from ``request_header_allowlist`` only, and no value
    that looks like an encoded blob, like file content or like a run of the task files.
    ``header_punctuation_check`` applies the punctuation-density test to header values too.
    """
    allowed = policy.get("allowed_methods", ["GET", "HEAD"])
    if method not in allowed:
        return True, "only %s are allowed (no uploads)" % " and ".join(allowed)
    if len(body or b"") > int(policy.get("max_request_body_bytes", 0)):
        return True, "a request body cannot carry research, so it cannot carry anything"
    u = urllib.parse.urlsplit(url)
    if len(url) > int(policy.get("max_url_bytes", 4096)):
        return True, "the URL is longer than any real one"
    if len(u.query or "") > int(policy.get("max_query_bytes", 2048)):
        return True, "the query string is longer than any real search"
    if len(u.path or "") > int(policy.get("max_path_bytes", 1024)):
        return True, "the path is longer than any real one"
    if not (shingles or {}).get("hashes"):
        return True, "the workspace fingerprint set is missing, so this request cannot be checked"
    min_run = int(policy.get("max_entropy_run", 192))
    dense_headers = bool(policy.get("header_punctuation_check", False))
    fields = [("the path", urllib.parse.unquote(u.path or ""), True)]
    for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True):
        fields.append(("query key %s" % k[:32], k, True))
        fields.append(("query value %s" % k[:32], v, True))
    reject = [h.lower() for h in policy.get("reject_headers", [])]
    allow_h = [h.lower() for h in policy.get("request_header_allowlist", [])]
    max_name = int(policy.get("max_header_name_bytes", 64))
    total = 0
    for k, v in (headers or {}).items():
        kl = k.lower()
        if len(k) > max_name:
            return True, "a header name longer than any real one (%d characters)" % len(k)
        if kl in reject:
            return True, "the %s header is never needed to read the public web" % k[:40]
        if kl not in allow_h:
            return True, "the %s header is not one a research fetch sends" % k[:40]
        total += len(k) + len(v)
        if len(v) > int(policy.get("max_header_value_bytes", 2048)):
            return True, "the %s header is longer than any real one" % k[:40]
        fields.append(("the %s header name" % k[:32], k, False))
        fields.append(("the %s header" % k[:32], v, dense_headers))
    if total > int(policy.get("max_header_bytes", 8192)):
        return True, "the request headers together are larger than any real request"
    max_qv = int(policy.get("max_query_value_bytes", 1024))
    for where, v, dense in fields:
        if where.startswith("query") and len(v) > max_qv:
            return True, "%s is longer than any real search term" % where
        for bad, why in (_looks_like_payload(v, min_run), _looks_like_file_content(v, dense),
                         _workspace_hit(v, shingles)):
            if bad:
                return True, "%s carries %s" % (where, why)
    return False, None


def request_decision(method, url, headers, body, policy, FP, shingles):
    """The request-stage decision of the proxy, before any name is resolved.

    Returns (decision, status, event, reason, work_id) with decision 'allow' or 'deny'. The
    checks run in the order the addon applies them: telemetry hosts, request shape,
    prohibited identifiers, the benchmark's own URLs, data sources, host names.
    """
    host = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    if any(host == s or host.endswith("." + s) for s in
           [x.lower() for x in policy.get("silent_deny_hosts", [])]):
        return "deny", 403, "TELEMETRY_BLOCK", "CLI telemetry, refused like any other upload", None
    bad, why = exfiltration_risk(method, url, headers, body, policy, shingles)
    if bad:
        return ("deny", 405 if method not in policy.get("allowed_methods", ["GET", "HEAD"]) else 413,
                "EXFILTRATION_BLOCK", why, None)
    wid, why = prohibited_by_identifier(url, FP)
    if wid:
        return "deny", 451, "GRADER_LEAKAGE_BLOCK", why, wid
    denied, why = url_denied(url, policy)
    if denied:
        return "deny", 451, "BENCHMARK_LEAKAGE_BLOCK", why, SELF_ID
    denied, why = data_source_denied(url, policy)
    if denied:
        return "deny", 451, "DATA_SOURCE_BLOCK", why, None
    ok, why = host_decision(host, policy)
    if not ok:
        return ("deny", 403, "BENCHMARK_LEAKAGE_BLOCK" if "benchmark" in why else "HOST_BLOCK",
                why, SELF_ID if "benchmark" in why else None)
    return "allow", None, None, None, None


def response_decision(body, mime, url, policy, FP, CFP=None):
    """The content-stage decision on a decoded response body.

    Returns (decision, status, event, reason, work_id, text) with decision 'allow', 'redact'
    (a verified listing with prohibited results removed; ``text`` is the body to deliver) or
    'deny'. ``listing_redaction`` is 'any_mention' (a listing that names a prohibited work
    in any way is redacted or withheld) or 'blocked_only' (only a listing that would be
    blocked as a whole is redacted).
    """
    text, kind = readable_text(body, mime, url)
    if kind == "empty":
        return "allow", None, None, None, None, ""
    if kind == "archive":
        return ("deny", 415, "UNSUPPORTED_FORMAT_BLOCK", "an archive is not research content "
                "this proxy can vouch for; its members would have to be recursed into to be "
                "inspected", None, None)
    if kind in ("opaque", "embedded"):
        return ("deny", 415, "UNINSPECTABLE_BLOCK", "a body this proxy cannot decode cannot be "
                "inspected (%s)" % (mime or "no content type"), None, None)
    if text is None:
        return ("deny", 415, "UNINSPECTABLE_BLOCK", "the document could not be read in full, so "
                "it cannot be shown to be in scope", None, None)
    findings = scan_content(text, FP, policy, mime=mime, url=url, body=body, CFP=CFP)
    blocking = [f for f in findings if f[0] == "block"]
    any_mention = policy.get("listing_redaction", "any_mention") == "any_mention"
    trigger = [f for f in (findings if any_mention else blocking) if f[1] != "scored_targets"]
    lkind = listing_kind(text, mime, url, policy) if trigger else None
    decision = "allow"
    if trigger and kind == "text" and lkind and all(f[1] != "scored_targets" for f in blocking):
        new_text, removed, complete = remove_listing_entries(text, lkind, FP, policy, CFP)
        if not complete:
            return ("deny", 451, "GRADER_LEAKAGE_BLOCK", "a listing that names a prohibited work "
                    "cannot be cut apart safely in this format, so none of it is served",
                    trigger[0][1], None)
        if removed:
            text = new_text
            findings = scan_content(text, FP, policy, mime=mime, url=url,
                                    body=text.encode("utf-8"), CFP=CFP)
            blocking = [f for f in findings if f[0] == "block"]
            survivors = listing_entry_survivors(text, lkind, FP, policy, CFP) if any_mention else []
            if survivors:
                return ("deny", 451, "GRADER_LEAKAGE_BLOCK", "a prohibited result survived "
                        "redaction, so the listing is withheld", survivors[0][0], None)
            decision = "redact"
    if blocking:
        wid = blocking[0][1]
        return ("deny", 451, "BENCHMARK_LEAKAGE_BLOCK" if wid == SELF_ID else "GRADER_LEAKAGE_BLOCK",
                blocking[0][2], wid, None)
    return decision, None, None, None, None, text


def effective_policy(policy, benchmark_self):
    """The policy of a condition with the user's benchmark_self settings merged in."""
    out = dict(policy)
    out["benchmark_self"] = {k: list(benchmark_self.get(k) or [])
                             for k in ("hosts", "url_substrings", "phrases")}
    return out


def workspace_shingles(texts, n=8):
    """Hashes of every n-word run of the given task texts, as the proxy's exfiltration
    check reads them: {'n': n, 'count': ..., 'hashes': [...]}."""
    hashes = set()
    for text in texts:
        words = re.findall(r"[a-z0-9_.]+", text.lower())
        for i in range(0, max(0, len(words) - n + 1)):
            hashes.add(hashlib.sha256(" ".join(words[i:i + n]).encode()).hexdigest()[:16])
    return {"n": n, "count": len(hashes), "hashes": sorted(hashes)}
