import json, os, urllib.parse, urllib.request
KEY = os.environ.get("KOSIS_API_KEY", "").strip()
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode("utf-8-sig"))
for kw in ["경제활동인구조사 고용률", "경제활동인구조사 실업률", "경제활동인구 취업자"]:
    q = urllib.parse.urlencode({"method": "getList", "apiKey": KEY, "vwCd": "MT_ZTITLE", "searchNm": kw, "format": "json", "jsonVD": "Y"})
    try:
        d = get("https://kosis.kr/openapi/statisticsSearch.do?" + q)
        rows = d if isinstance(d, list) else d.get("result", d)
        print("##", kw, type(rows).__name__, (len(rows) if hasattr(rows, "__len__") else ""))
        for x in (rows or [])[:12]:
            if isinstance(x, dict):
                print(json.dumps({k: x.get(k) for k in ("ORG_ID", "TBL_ID", "TBL_NM", "ORG_NM", "PRD_SE", "STRT_PRD_DE", "END_PRD_DE")}, ensure_ascii=False))
            else:
                print(str(x)[:300])
    except Exception as ex:
        print("ERR", kw, repr(ex)[:300])
