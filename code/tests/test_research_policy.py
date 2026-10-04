"""Decisions of the web research proxy for the two web conditions, offline.

The requests and bodies are representative of what the agents sent and received. The
prohibited identifiers used here are the ones the task's blacklist.txt names.
"""
import base64
import io
import json
import re
import zipfile

import pytest

from sciexam.agent import research as RS
from sciexam.agent.research import policy as R

BROWSER = {"Host": "arxiv.org", "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
           "Accept": "text/html", "Accept-Encoding": "gzip"}
# pip's User-Agent carries a JSON blob of its build metadata
PIP_UA = ('pip/24.0 {"ci":null,"cpu":"x86_64","distro":{"name":"Ubuntu","version":"24.04"},'
          '"implementation":{"name":"CPython","version":"3.12.3"},"installer":{"name":"pip",'
          '"version":"24.0"},"openssl_version":"OpenSSL 3.0.13","python":"3.12.3",'
          '"setuptools_version":"68.1.2","system":{"name":"Linux","release":"6.8.0"}}')
TASK_TEXT = ("For every index, remove the monthly-mean climatology over the fixed base period "
             "for each calendar month, subtract that month's average. Same base period for all "
             "five indices, remove the monthly climatology only, no additional detrending.")
SELF = {"hosts": ["benchmark-results.example.org"], "url_substrings": ["/our-benchmark/"],
        "phrases": ["our benchmark leaderboard"]}


@pytest.fixture(scope="module", params=RS.POLICIES)
def cond(request, tmp_path_factory):
    path = tmp_path_factory.mktemp("self") / "benchmark_self.json"
    path.write_text(json.dumps(SELF))
    pol, works, content = RS.load(request.param, path)
    return request.param, pol, works, content, R.workspace_shingles([TASK_TEXT])


def req(cond, url, method="GET", headers=None, body=b""):
    _name, pol, works, _content, sh = cond
    sh = dict(sh, hashes=set(sh["hashes"]))
    return R.request_decision(method, url, headers or BROWSER, body, pol, works, sh)


def resp(cond, body, mime="text/html", url="https://example.org/page"):
    _name, pol, works, content, _sh = cond
    return R.response_decision(body, mime, url, pol, works, content)


# ---- request stage -------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["https://arxiv.org/abs/2306.04074",
                                 "https://journals.ametsoc.org/view/journals/atsc/54/7/x.xml",
                                 "https://api.semanticscholar.org/graph/v1/paper/search?"
                                 "query=recharge+oscillator+ENSO&limit=20",
                                 "https://www.climate.gov/news-features/blogs/enso/flavor"])
def test_literature_is_allowed(cond, url):
    assert req(cond, url)[0] == "allow"


@pytest.mark.parametrize("url", ["https://arxiv.org/abs/2402.04585",
                                 "https://arxiv.org/pdf/2402.04585v2.pdf",
                                 "https://export.arxiv.org/abs/2402.04585?context=physics",
                                 "https://doi.org/10.1029/2024RG000843",
                                 "https://agupubs.onlinelibrary.wiley.com/doi/full/"
                                 "10.1029/2024rg000843/abstract"])
def test_prohibited_work_is_refused_by_identifier(cond, url):
    d = req(cond, url)
    assert d[:3] == ("deny", 451, "GRADER_LEAKAGE_BLOCK") and d[4].startswith("blacklist_")


@pytest.mark.parametrize("url,headers,method,why", [
    ("https://example.org/", None, "POST", "only GET and HEAD"),
    ("https://example.org/search?q=" + base64.urlsafe_b64encode(bytes(range(200))).decode(),
     None, "GET", "high-entropy"),
    ("https://example.org/search?q=" + TASK_TEXT.replace(" ", "+"), None, "GET",
     "own workspace"),
    ("https://example.org/", dict(BROWSER, Cookie="a=b"), "GET", "Cookie header"),
    ("https://example.org/", dict(BROWSER, **{"X-Upload": "1"}), "GET", "not one a research"),
    ("https://example.org/?q=def+f():%0Areturn+1", None, "GET", "line breaks"),
])
def test_uploads_and_exfiltration_are_refused(cond, url, headers, method, why):
    d = req(cond, url, method=method, headers=headers)
    assert d[0] == "deny" and d[2] == "EXFILTRATION_BLOCK" and why in d[3]


@pytest.mark.parametrize("url,event", [
    ("https://benchmark-results.example.org/models", "BENCHMARK_LEAKAGE_BLOCK"),
    ("https://github.com/someone/our-benchmark/tree/main", "BENCHMARK_LEAKAGE_BLOCK"),
    ("https://http-intake.logs.us5.datadoghq.com/api/v2/logs", "TELEMETRY_BLOCK"),
    ("https://host.docker.internal/", "HOST_BLOCK"),
    ("https://localhost/", "HOST_BLOCK")])
def test_own_pages_telemetry_and_internal_hosts_are_refused(cond, url, event):
    assert req(cond, url)[0] == "deny" and req(cond, url)[2] == event


@pytest.mark.parametrize("url", [
    "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php",
    "https://www.ncei.noaa.gov/access/monitoring/enso/sst",
    "https://psl.noaa.gov/data/gridded/data.noaa.ersst.v5.html",
    "https://example.org/files/nino34.csv",
    "https://example.edu/thredds/catalog.html"])
def test_data_sources_follow_the_condition(cond, url):
    name = cond[0]
    d = req(cond, url)
    if name == "literature_only":
        assert d[:3] == ("deny", 451, "DATA_SOURCE_BLOCK")
    else:
        assert d[0] == "allow"


def test_pip_user_agent_follows_the_condition(cond):
    """The header punctuation test of literature_and_data refuses pip's JSON User-Agent."""
    h = {"Host": "pypi.org", "User-Agent": PIP_UA, "Accept": "application/vnd.pypi.simple.v1+json"}
    d = req(cond, "https://pypi.org/simple/pypdf/", headers=h)
    if cond[0] == "literature_and_data":
        assert d[:3] == ("deny", 413, "EXFILTRATION_BLOCK") and "punctuation" in d[3]
    else:
        assert d[0] == "allow"


def test_missing_workspace_fingerprints_refuse_everything(cond):
    _name, pol, works, _c, _sh = cond
    d = R.request_decision("GET", "https://example.org/", BROWSER, b"", pol, works, {"hashes": set()})
    assert d[0] == "deny" and "fingerprint set is missing" in d[3]


# ---- content stage -------------------------------------------------------------------------

def test_ordinary_page_and_citation_are_served(cond):
    page = (b"<html><head><title>ENSO dynamics</title></head><body>"
            + b"The recharge oscillator links thermocline depth and SST. " * 20
            + b"See also arXiv:2402.04585 and doi 10.1029/2024RG000843.</body></html>")
    d = resp(cond, page)
    assert d[0] == "allow" and d[5].startswith("<html>")


def test_document_that_is_the_prohibited_work_is_refused(cond):
    page = (b'<html><head><meta name="citation_doi" content="10.1029/2024RG000843">'
            b"<title>A review</title></head><body>" + b"text " * 100 + b"</body></html>")
    assert resp(cond, page)[:3] == ("deny", 451, "GRADER_LEAKAGE_BLOCK")


def test_scored_targets_and_own_pages_are_refused(cond):
    vector = b"<p>EN 24, EP 14, CP 10, EX 4, MYEN 5, LN 24, MYLN 8</p>" + b"x " * 50
    assert resp(cond, vector)[:3] == ("deny", 451, "GRADER_LEAKAGE_BLOCK")
    own = b"<p>Results of Our Benchmark Leaderboard</p>" + b"x " * 50
    assert resp(cond, own)[:3] == ("deny", 451, "BENCHMARK_LEAKAGE_BLOCK")


def test_archives_and_opaque_bodies_are_refused(cond):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pypdf/__init__.py", "x = 1\n")
    wheel = "https://files.pythonhosted.org/packages/aa/pypdf-6.19.0-py3-none-any.whl"
    assert resp(cond, buf.getvalue(), "application/octet-stream", wheel)[:3] == (
        "deny", 415, "UNSUPPORTED_FORMAT_BLOCK")
    assert resp(cond, b"\x00\x01\x02binary", "application/octet-stream")[2] == "UNINSPECTABLE_BLOCK"
    assert resp(cond, b"not a pdf at all", "application/pdf", "https://x.org/a.pdf")[2] == \
        "UNINSPECTABLE_BLOCK"


def test_search_listing_follows_the_condition(cond):
    """A result list with the prohibited work as one result and a citing paper as another."""
    listing = {"data": [
        {"paperId": "a", "title": "A stochastic ENSO model", "externalIds": {"DOI": "10.1175/x.1"},
         "abstract": "We extend 10.1029/2024RG000843 with noise."},
        {"paperId": "b", "title": "A review", "externalIds": {"DOI": "10.1029/2024RG000843"}}]}
    url = "https://api.semanticscholar.org/graph/v1/paper/search?query=recharge+oscillator"
    d = resp(cond, json.dumps(listing).encode(), "application/json", url)
    if cond[0] == "literature_only":
        assert d[0] == "redact"
        kept = json.loads(d[5])["data"]
        assert [p["paperId"] for p in kept] == ["a"]
    else:
        assert d[0] == "allow" and json.loads(d[5]) == listing


# ---- fingerprints --------------------------------------------------------------------------

def test_fingerprints_are_hashes_only():
    works = R.load_json(RS.HERE / "fingerprints" / "works.json")
    content = R.load_json(RS.HERE / "fingerprints" / "content.json")
    hex64 = re.compile(r"[0-9a-f]{64}")
    for w in works["works"]:
        assert set(w) == {"id", "arxiv", "doi", "title", "phrases"}
        assert all(hex64.fullmatch(h) for h in w["arxiv"])
        for e in w["doi"] + w["title"] + w["phrases"]:
            assert all(isinstance(v, int) or hex64.fullmatch(v) for v in e.values())
    for w in content["works"]:
        assert set(w) == {"work_id", "regions"}
        assert all(re.fullmatch(r"[0-9a-f]{20}", h) for r in w["regions"] for h in r)
    assert RS.load("literature_only")[0]["benchmark_self"] == {
        "hosts": [], "url_substrings": [], "phrases": []}


def test_phrase_fingerprints_match_normalised_text():
    fp = R.phrase_fingerprint("A Stochastic Model: of ENSO")
    idx = R.TextIndex("... see a stochastic-model of  ENSO, and more")
    assert idx.has_title([fp], squashed=False)
    assert R.TextIndex("astochasticmodelofenso").has_title([fp])
    assert not R.TextIndex("a stochastic model of the ENSO").has_title([fp], squashed=False)
