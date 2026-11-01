import json, time, urllib.request, urllib.parse
BASE = "https://api.elections.kalshi.com/trade-api/v2"
SER = ["KXCBDECISIONKOREA","KXKOSPI","KXKOREAPRES"]
_OLD = ["KXSKEXPYOY","KXCBDECISIONKOREA","KXKS200D","KXKS200W","KXKS200M","KXKS200A","KXKS200H","KXKS200L","KXKR200","KXKOSPI","KXKOSPIPOS","KXTARIFFRATEKR","KXFERTILITYSK","KXCAPITALMOVESK","KXSKPRES","KXKOREAPRES"]
def get(path, **q):
    url = BASE + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "econ-dashboard-probe"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)
out = {}
for s in SER:
    try:
        d = get("/markets", series_ticker=s, status="open", limit=200)
        ms = d.get("markets", [])
        out[s] = {"n": len(ms), "markets": [{k: v for k, v in m.items() if k in ("ticker","yes_sub_title","close_time") or "bid" in k or "ask" in k or "last" in k or "volume" in k or "interest" in k or "liquidity" in k} for m in ms[:25]]}
    except Exception as ex:
        out[s] = {"error": repr(ex)}
    time.sleep(0.3)
try:
    out["_x"] = get("/series/KXSKEXPYOY")
except Exception as ex:
    out["_candles_test"] = repr(ex)
json.dump(out, open("data/kalshi-probe2.json", "w"), ensure_ascii=False, indent=1)
for s, v in out.items():
    if s.startswith("_"): continue
    print(s, v.get("n"), v.get("error"))
    for m in v.get("markets", [])[:14]: print("   ", json.dumps(m, ensure_ascii=False))
