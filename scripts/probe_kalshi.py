import json, re, time, urllib.request, urllib.parse
BASE = "https://api.elections.kalshi.com/trade-api/v2"
def get(path, **q):
    url = BASE + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "econ-dashboard-probe"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)
out = {"series": [], "markets": {}}
s = get("/series")["series"]
eco = [x for x in s if x.get("category") in ("Economics", "Financials")]
out["n_all"] = len(s); out["n_eco"] = len(eco)
for x in eco:
    out["series"].append({"t": x.get("ticker"), "title": x.get("title"), "cat": x.get("category"), "freq": x.get("frequency")})
# open markets per Economics series (count + sample)
for x in eco:
    if x.get("category") != "Economics": continue
    try:
        d = get("/markets", series_ticker=x["ticker"], status="open", limit=100)
        ms = d.get("markets", [])
        if ms:
            def p(m):
                v = m.get("last_price_dollars")
                return round(float(v) * 100) if v not in (None, "") else None
            out["markets"][x["ticker"]] = {"title": x.get("title"), "n": len(ms), "vol": sum(float(m.get("volume_fp") or 0) for m in ms),
                "close": min((m.get("close_time") or "")[:10] for m in ms),
                "sample": [[m.get("yes_sub_title"), p(m), m.get("volume_fp")] for m in ms[:6]]}
    except Exception as ex:
        out["markets"][x["ticker"]] = {"error": repr(ex)}
    time.sleep(0.15)
json.dump(out, open("data/kalshi-probe2.json", "w"), ensure_ascii=False, indent=1)
print("eco series", len(eco), "with open markets", len(out["markets"]))
for t, v in sorted(out["markets"].items(), key=lambda kv: -(kv[1].get("vol") or 0)):
    if "error" in v: print(t, v["error"]); continue
    print(f'{t} | {v["title"]} | n={v["n"]} vol={v["vol"]:.0f} close={v["close"]} | {v["sample"][:3]}')
