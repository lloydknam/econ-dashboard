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
o = KEYS["OPENFISCAL_API_KEY"]
if o:
    P["openfiscal_root"] = get("https://openapi.openfiscaldata.go.kr/", 3000)
    for yy in (2026, 2025):
        P[f"openfiscal_ExpenditureBudgetInit5_{yy}"] = get(q("https://openapi.openfiscaldata.go.kr/ExpenditureBudgetInit5", Key=o, Type="json", pIndex=1, pSize=3, FSCL_YY=yy), 2500)
    for svc in ("ExpenditureBudgetInit5", "ExpenditureBudgetAdd5", "NationalDebt", "FiscalBalance", "TotalRevenueExpenditure",
                "IncomeStatus", "NationalAssets", "GovernmentLiabilities", "CommonFiscalData", "ExpenditureSettlementInit5", "RevenueBudgetInit5", "IncomeBudgetInit5", "FiscalStatus", "NationalDebtStatus", "DebtStatus"):
        P[f"openfiscal_{svc}"] = get(q(f"https://openapi.openfiscaldata.go.kr/{svc}", Key=o, Type="json", pIndex=1, pSize=3), 800)
d = KEYS["DATA_GO_KR_KEY"]
if d:
    P["datago_search"] = get(q("https://api.odcloud.kr/api/15057841/v1/uddi:dummy", serviceKey=d, page=1, perPage=3), 800)
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("probes:", len(P), {k: v["status"] for k, v in P.items()})
