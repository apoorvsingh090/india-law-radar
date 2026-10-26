"""One-off pilot probe (not part of the app): list legislative.gov.in hrefs.

Usage: python scripts/probe_legislative.py
Respects robots.txt (Allow: /) and fetches one page with a clear UA.
"""
import re
import urllib.request

UA = "IndiaLawRadar/0.8.0 pilot-check (single page, respects robots.txt)"

req = urllib.request.Request(
    "https://www.legislative.gov.in/", headers={"User-Agent": UA}
)
body = urllib.request.urlopen(req, timeout=30).read(400000).decode(
    "utf-8", "replace"
)
hrefs = sorted(set(re.findall(r'href="([^"]+)"', body)))
print(len(hrefs), "unique hrefs")
interesting = [
    h for h in hrefs
    if any(k in h.lower() for k in (
        "act", "rule", "gazette", "bill", "document", "sitemap", "pdf",
        "api", "_next/data",
    ))
]
for href in interesting[:60]:
    print(href)

