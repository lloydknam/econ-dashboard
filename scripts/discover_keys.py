#!/usr/bin/env python3
"""One-off probe: checks that KOSIS / 열린재정 / data.go.kr keys work and records
raw responses (truncated, keys redacted) to data/discovery.json so endpoints can be wired up."""
import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "discovery.json"
UA = {"User-Agent": "Mozilla/5.0 ClerkEconTerminal/2.0"}
KEYS = {n: os.environ.get(n, "").strip() for n in ("KOSIS_API_KEY", "OPENFISCAL_API_KEY", "DATA_GO_KR_KEY")}


def get(url, limit=1500):
    for k, v in KEYS.items():
        if v:
            url_show = url.replace(v, f"<{k}>").replace(urllib.parse.quote(v, safe=""), f"<{k}>")
            break
    else:
        url_show = url
    for k, v in KEYS.items():
        if v:
            url_show = url_show.replace(v, f"<{k}>").replace(urllib.parse.quote(v, safe=""), f"<{k}>")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            body = r.read().decode("utf-8", errors="replace")
            status = r.status
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        status, body = None, f"ERR {e}"
    for v in KEYS.values():
        if v:
            body = body.replace(v, "<KEY>")
    return {"url": url_show, "status": status, "body": body[:limit]}


def q(base, **p):
    return base + "?" + urllib.parse.urlencode(p, safe="+")


res = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
       "keys_present": {k: bool(v) for k, v in KEYS.items()}, "probes": {}}
P = res["probes"]
k = KEYS["KOSIS_API_KEY"]
if k:
    for term in ("국가채무", "관리재정수지", "국세", "재정수지", "총지출", "일반정부"):
        P[f"kosis_search_{term}"] = get(q("https://kosis.kr/openapi/statisticsSearch.do", method="getList", apiKey=k,
                                          searchNm=term, format="json", jsonVD="Y", startCount=1, resultCount=15, sort="RANK"), 6000)
def kosis_table(org, tbl, prd, n=3, itm="ALL", l1="ALL", l2="", extra=None):
    prm = dict(method="getList", apiKey=k, itmId=itm, objL1=l1, objL2=l2, format="json", jsonVD="Y",
               prdSe=prd, newEstPrdCnt=n, orgId=org, tblId=tbl)
    r = get(q("https://kosis.kr/openapi/Param/statisticsParameterData.do", **prm), 400000)
    try:
        rows = json.loads(r["body"])
        if isinstance(rows, dict):
            return {"error": rows}
        seen, out = set(), []
        for x in rows:
            key = (x.get("C1_NM"), x.get("C2_NM"), x.get("ITM_NM"), x.get("UNIT_NM"), x.get("ITM_ID"), x.get("C1"), x.get("C2"))
            if key not in seen and len(out) < 70:
                seen.add(key)
                out.append({"C1_NM": key[0], "C2_NM": key[1], "ITM_NM": key[2], "UNIT": key[3], "ITM_ID": key[4], "C1": key[5], "C2": key[6],
                            "PRD": x.get("PRD_DE"), "DT": x.get("DT")})
        return {"rows": len(rows), "distinct": out}
    except Exception as e:
        return {"parse_error": str(e), "raw": r["body"][:600], "status": r["status"]}


if k:
    P["kosis_DT_102006_001_Y"] = kosis_table("184", "DT_102006_001", "Y", 3)
    P["kosis_DT_102N_A001_Y"] = kosis_table("184", "DT_102N_A001", "Y", 2)
    P["kosis_DT_102N_AD01_M"] = kosis_table("184", "DT_102N_AD01", "M", 2)
    P["kosis_DT_102N_AD01_Y"] = kosis_table("184", "DT_102N_AD01", "Y", 2)
o = KEYS["OPENFISCAL_API_KEY"]
if o:
    P["openfiscal_root"] = get("https://openapi.openfiscaldata.go.kr/", 3000)
    for yy in (2026, 2025):
        P[f"openfiscal_ExpenditureBudgetInit5_{yy}"] = get(q("https://openapi.openfiscaldata.go.kr/ExpenditureBudgetInit5", Key=o, Type="json", pIndex=1, pSize=3, FSCL_YY=yy), 2500)
d = KEYS["DATA_GO_KR_KEY"]
if d:
    P["datago_search"] = get(q("https://api.odcloud.kr/api/15057841/v1/uddi:dummy", serviceKey=d, page=1, perPage=3), 800)
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("probes:", len(P), {k: v["status"] for k, v in P.items()})
