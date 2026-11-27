"""NSE's public archive files: announcements, financial-results and insider RSS feeds, bulk and block deals.

These are plain static files on nsearchives.nseindia.com (no login, no
cookies). Fetched with a short timeout and cached under nse/cache/ for a few
minutes so repeated runs don't hammer the exchange. Every tool also takes
--file to read a saved copy instead.
"""

import csv
import io
import os
import re
import time
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
