import json, os, urllib.parse, urllib.request
KEY = os.environ.get("KOSIS_API_KEY", "").strip()
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read().decode("utf-8-sig"))
tables = {}
for kw in ["산업별 취업자", "연령별 취업자", "종사상지위별 취업자", "고용형태별 근로자", "산업 연령 취업자 경제활동인구", "임금근로자 고용형태"]:
    q = urllib.parse.urlencode({"method": "getList", "apiKey": KEY, "vwCd": "MT_ZTITLE", "searchNm": kw, "format": "json", "jsonVD": "Y"})
    try:
        d = get("https://kosis.kr/openapi/statisticsSearch.do?" + q)
        for x in d if isinstance(d, list) else []:
            if x.get("ORG_ID") == "101" and x.get("END_PRD_DE", "") >= "2025":
                tables.setdefault(x["TBL_ID"], x["TBL_NM"])
    except Exception as ex:
        print("## SEARCH ERR", kw, repr(ex)[:200])
print("## TABLES", len(tables))
for t, n in tables.items(): print("## T", t, n)
for t, n in list(tables.items())[:14]:
    q = urllib.parse.urlencode({"method": "getData", "apiKey": KEY, "format": "json", "jsonVD": "Y", "orgId": "101", "tblId": t,
        "itmId": "ALL", "objL1": "ALL", "objL2": "ALL", "objL3": "ALL", "prdSe": "M", "newEstPrdCnt": "1"})
    try:
        d = get("https://kosis.kr/openapi/Param/statisticsParameterData.do?" + q)
        if isinstance(d, dict):
            print("## CODES", t, "ERR", str(d)[:160]); continue
        seen = {}
        for x in d:
            k = (x.get("C1"), x.get("C1_NM"), x.get("C2"), x.get("C2_NM"), x.get("ITM_ID"), x.get("ITM_NM"), x.get("UNIT_NM"))
            seen.setdefault(k, 1)
        print("## CODES", t, n, "rows", len(d), "combos", len(seen))
        for k in list(seen)[:400]:
            print("## K", t, json.dumps(k, ensure_ascii=False))
    except Exception as ex:
        print("## CODES ERR", t, repr(ex)[:200])
