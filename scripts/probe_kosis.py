import json, os, urllib.parse, urllib.request
KEY = os.environ.get("KOSIS_API_KEY", "").strip()
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read().decode("utf-8-sig"))
TABLES = ["DT_1DA7E06S_NEW", "DT_2KAA352", "DT_1DA7024S", "DT_1DA7010S", "DT_1DA7028S", "DT_1DA7E26S_NEW", "DT_1DA7031S", "DT_1DA7050S", "DT_1DA7E33S_NEW"]
for t in TABLES:
    d = None
    for objs in ({"objL1": "ALL", "objL2": "ALL"}, {"objL1": "ALL"}):
        q = urllib.parse.urlencode({"method": "getData", "apiKey": KEY, "format": "json", "jsonVD": "Y", "orgId": "101", "tblId": t,
            "itmId": "ALL", "prdSe": "M", "newEstPrdCnt": "1", **objs})
        try:
            r = get("https://kosis.kr/openapi/Param/statisticsParameterData.do?" + q)
            if isinstance(r, list):
                d = (objs, r); break
        except Exception as ex:
            pass
    if not d:
        print("## FAIL", t); continue
    objs, rows = d
    c1 = {}; c2 = {}; itm = {}
    for x in rows:
        c1.setdefault((x.get("C1"), x.get("C1_NM")), 1)
        if x.get("C2"): c2.setdefault((x.get("C2"), x.get("C2_NM")), 1)
        itm.setdefault((x.get("ITM_ID"), x.get("ITM_NM"), x.get("UNIT_NM")), 1)
    print("## T", t, "objs", list(objs), "rows", len(rows), "prd", rows[0].get("PRD_DE") if rows else "")
    print("## C1", json.dumps(list(c1), ensure_ascii=False))
    print("## C2", json.dumps(list(c2), ensure_ascii=False)[:1500])
    print("## ITM", json.dumps(list(itm), ensure_ascii=False)[:900])
