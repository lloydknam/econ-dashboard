import json, re, time, urllib.request, urllib.parse
BASE = "https://api.elections.kalshi.com/trade-api/v2"
KW = re.compile(r"korea|kospi|kosdaq|\bwon\b|krw|seoul|samsung|hyundai|bank of korea|\bBOK\b|한국", re.I)
def get(path, **q):
    url = BASE + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "econ-dashboard-probe"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)
out = {"events": [], "series_hits": [], "errors": []}
try:
    cur = None
    for page in range(60):
        q = dict(status="open", limit=200, with_nested_markets="true")
        if cur: q["cursor"] = cur
        d = get("/events", **q)
        for e in d.get("events", []):
            blob = " ".join(str(e.get(k, "")) for k in ("title", "sub_title", "series_ticker", "event_ticker", "category"))
            mk = e.get("markets", []) or []
            blob += " " + " ".join(str(m.get("title", "")) + " " + str(m.get("yes_sub_title", "")) for m in mk)
            if KW.search(blob):
                out["events"].append({"event_ticker": e.get("event_ticker"), "series_ticker": e.get("series_ticker"), "title": e.get("title"), "category": e.get("category"),
                    "markets": [{"ticker": m.get("ticker"), "title": m.get("title"), "yes_sub_title": m.get("yes_sub_title"), "yes_bid": m.get("yes_bid"), "yes_ask": m.get("yes_ask"), "last_price": m.get("last_price"), "volume": m.get("volume"), "close_time": m.get("close_time")} for m in mk[:12]]})
        cur = d.get("cursor")
        if not cur: break
        time.sleep(0.3)
    out["pages"] = page + 1
except Exception as ex:
    out["errors"].append("events: %r" % ex)
try:
    s = get("/series")
    out["series_total"] = len(s.get("series", []))
    out["series_hits"] = [{"ticker": x.get("ticker"), "title": x.get("title"), "category": x.get("category"), "frequency": x.get("frequency")} for x in s.get("series", []) if KW.search(" ".join(str(x.get(k, "")) for k in ("title", "ticker", "tags")))]
except Exception as ex:
    out["errors"].append("series: %r" % ex)
json.dump(out, open("data/kalshi-probe.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in out.items()}, ensure_ascii=False))
for e in out["events"][:40]: print(e["event_ticker"], "|", e["title"])
