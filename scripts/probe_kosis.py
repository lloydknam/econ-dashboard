import json, os, urllib.parse, urllib.request
KEY = os.environ.get("KOSIS_API_KEY", "").strip()
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read().decode("utf-8-sig"))
base = {"apiKey": KEY, "format": "json", "jsonVD": "Y", "orgId": "101", "tblId": "DT_1DA7002S"}
for typ in ("ITM", "OBJ"):
    try:
        q = urllib.parse.urlencode({**base, "method": "getMeta", "type": typ})
        d = get("https://kosis.kr/openapi/statisticsParameterData.do?" + q)
        print("## META", typ, json.dumps(d, ensure_ascii=False)[:1500])
    except Exception as ex:
        print("## META ERR", typ, repr(ex)[:200])
try:
    q = urllib.parse.urlencode({**base, "method": "getData", "itmId": "ALL", "objL1": "ALL", "objL2": "", "prdSe": "M", "newEstPrdCnt": "2"})
    d = get("https://kosis.kr/openapi/Param/statisticsParameterData.do?" + q)
    rows = d if isinstance(d, list) else []
    print("## DATA rows", len(rows), "err" if isinstance(d, dict) else "")
    if isinstance(d, dict): print(json.dumps(d, ensure_ascii=False)[:500])
    seen = set()
    for x in rows[:400]:
        key = (x.get("ITM_NM"), x.get("C1_NM"), x.get("PRD_DE"))
        if key in seen: continue
        seen.add(key)
        print(json.dumps({"itm": x.get("ITM_ID"), "itmNm": x.get("ITM_NM"), "c1": x.get("C1"), "c1Nm": x.get("C1_NM"), "prd": x.get("PRD_DE"), "dt": x.get("DT"), "unit": x.get("UNIT_NM")}, ensure_ascii=False))
except Exception as ex:
    print("## DATA ERR", repr(ex)[:300])
