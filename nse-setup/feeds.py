"""Exchange data the research skills read: NSE's archive files, NSE's website data and BSE's website data.

1. NSE archive files on nsearchives.nseindia.com: plain static files, no
   login, no cookies (announcements RSS, bulk.csv, block.csv).
2. NSE website data (www.nseindia.in/api/...): the JSON NSE's own pages
   load. Not an official API: it needs the cookies a browser gets from the
   home page first, and NSE can change it without notice.
3. BSE website data (api.bseindia.com/BseIndiaAPI/api/...): the JSON
   bseindia.com loads. Not an official API either: it wants a bseindia.com
   Referer.

Everything is fetched with a short timeout and cached under nse/cache/ for a
few minutes so repeated runs don't hammer the exchanges. Every tool also
takes --file to read a saved copy instead.
"""

import csv
import hashlib
import http.cookiejar
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import nselib

BASE = "https://nsearchives.nseindia.com/"
URLS = {
    "announcements": BASE + "content/RSS/Online_announcements.xml",
    "results": BASE + "content/RSS/Financial_Results.xml",
    "insider": BASE + "content/RSS/Insider_Trading.xml",
    "bulk": BASE + "content/equities/bulk.csv",
    "block": BASE + "content/equities/block.csv",
}
CACHE_MIN = 5
UA = "Mozilla/5.0 (compatible; nse-skills/0.1; personal research)"
# the website APIs turn away anything that doesn't look like a browser
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
NSE_WWW = "https://www.nseindia.in"
NSE_API = {
    # insider (SEBI PIT) filings since NSE moved them to XBRL on 4 May 2026
    "pit": ("/api/corporates-pit-gg", "/companies-listing/corporate-filings-insider-trading"),
    # the older insider list, with who traded and how much, for filings before May 2026
    "pit_old": ("/api/corporates-pit", "/companies-listing/corporate-filings-insider-trading"),
}
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/"
BSE_WWW = "https://www.bseindia.com/"
BSE_ATTACH = BSE_WWW + "xml-data/corpfiling/AttachLive/"


def fetch(kind, file=None, cache_min=CACHE_MIN):
    """Text of one feed: from --file if given, else a fresh cache, else NSE."""
    if file:
        with open(file, encoding="utf-8-sig") as fh:
            return fh.read()
    url = URLS[kind]
    cache = nselib.path("cache", os.path.basename(url))
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < cache_min * 60:
        with open(cache, encoding="utf-8") as fh:
            return fh.read()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        text = r.read().decode("utf-8-sig", errors="replace")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def _cached(key, cache_min):
    cache = nselib.path("cache", key)
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < cache_min * 60:
        with open(cache, encoding="utf-8") as fh:
            return cache, fh.read()
    return cache, None


def _save(cache, text):
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        fh.write(text)


def _key(prefix, url):
    return "%s-%s.json" % (prefix, hashlib.sha1(url.encode()).hexdigest()[:12])


def nse_json(kind, params, file=None, cache_min=CACHE_MIN):
    """JSON from NSE's website data: visit the home page and the listing page for cookies, then ask."""
    if file:
        with open(file, encoding="utf-8-sig") as fh:
            return json.load(fh)
    api, page = NSE_API[kind]
    url = NSE_WWW + api + "?" + urllib.parse.urlencode(params)
    cache, text = _cached(_key("nse", url), cache_min)
    if text is None:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        page_h = {"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                  "Accept-Language": "en-US,en;q=0.9"}
        for warm in (NSE_WWW + "/", NSE_WWW + page):
            try:
                opener.open(urllib.request.Request(warm, headers=page_h), timeout=15).read()
            except OSError:
                pass  # the API call below says whether we got enough cookies
        api_h = {"User-Agent": BROWSER_UA, "Accept": "application/json, text/javascript, */*; q=0.01",
                 "Accept-Language": "en-US,en;q=0.9", "Referer": NSE_WWW + page,
                 "X-Requested-With": "XMLHttpRequest"}
        with opener.open(urllib.request.Request(url, headers=api_h), timeout=20) as r:
            text = r.read().decode("utf-8-sig", errors="replace")
        _check_json(text, "NSE")
        _save(cache, text)
    return json.loads(text)


def bse_json(endpoint, params, file=None, cache_min=CACHE_MIN):
    """JSON from BSE's website data (api.bseindia.com), asked for the way bseindia.com asks."""
    if file:
        with open(file, encoding="utf-8-sig") as fh:
            return json.load(fh)
    url = BSE_API + endpoint + "?" + urllib.parse.urlencode(params)
    cache, text = _cached(_key("bse", url), cache_min)
    if text is None:
        h = {"User-Agent": BROWSER_UA, "Accept": "application/json, text/plain, */*",
             "Accept-Language": "en-US,en;q=0.5", "Origin": BSE_WWW.rstrip("/"), "Referer": BSE_WWW}
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
            text = r.read().decode("utf-8-sig", errors="replace")
        _check_json(text, "BSE")
        _save(cache, text)
    return json.loads(text)


def _check_json(text, who):
    t = text.lstrip()
    if not t or t[0] not in "[{":
        raise OSError("%s sent a web page instead of data (it may be blocking scripts right now)" % who)


def rss_items(text):
    """[{title, link, description, pub}] from an NSE RSS feed."""
    root = ET.fromstring(text.strip().encode("utf-8"))
    out = []
    for it in root.iter("item"):
        g = lambda tag: re.sub(r"\s+", " ", (it.findtext(tag) or "")).strip()  # noqa: E731
        out.append({"title": g("title"), "link": g("link"), "description": g("description"), "pub": g("pubDate")})
    return out


def csv_rows(text):
    """Rows of an NSE CSV as dicts, header names stripped."""
    rdr = csv.reader(io.StringIO(text.strip()))
    rows = list(rdr)
    if not rows:
        return []
    head = [h.strip() for h in rows[0]]
    return [dict(zip(head, [c.strip() for c in r])) for r in rows[1:] if any(c.strip() for c in r)]


def num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


_SUFFIX = re.compile(r"\b(limited|ltd\.?|the|india|co\.?|company|corporation|corp\.?|inc\.?)\b", re.I)


def norm_name(s):
    return re.sub(r"[^a-z0-9]+", " ", _SUFFIX.sub(" ", s.lower())).strip()


def name_matches(title, names):
    """Does an RSS title (a company name) match any of the watchlist names or symbols?"""
    t = norm_name(title)
    for n in names:
        k = norm_name(n)
        if k and t == k:   # exact, so "Infosys" does not pick up "Infosys BPM Services"
            return True
    return False


def groww_pick(data, section, symbol, name=None):
    """One company's `section` (financialStatement, shareholding_pattern) out of a saved Groww answer.

    A Groww search can return several companies (Infosys also brings HCL
    Infosystems); pick the one whose slug matches the name or symbol, else the first.
    """
    if section in data:
        return data[section], symbol
    content = data.get("result", data).get("content", data.get("result", data))
    keys = [k for k, v in content.items() if isinstance(v, dict) and section in v]
    if not keys:
        raise ValueError("no %s found in the saved file" % section)
    want = [norm_name(x) for x in (name, symbol) if x]
    for k in keys:
        if norm_name(k.replace("-", " ").replace(" ltd", "")) in want:
            return content[k][section], k
    return content[keys[0]][section], keys[0]
