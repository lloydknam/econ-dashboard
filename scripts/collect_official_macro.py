#!/usr/bin/env python3
"""Collect official macroeconomic observations for the Econ Dashboard.

Sources
  ECOS (Bank of Korea)  — config/ecos-series.json, needs ECOS_API_KEY
  FRED (St. Louis Fed)  — config/fred-series.json, FRED_API_KEY optional
                          (public CSV endpoint is used as a fallback)

A temporary failure of a provider or a single series never erases the last
usable observations: previous rows are retained and merged.
"""
import csv
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "official-macro.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
# How many observations to keep per frequency (enough for 1y charts and YoY maths).
CAP = {"D": 270, "W": 60, "M": 40, "Q": 24, "A": 15}
WORKERS = 6


def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"HTTP {exc.code}: {detail[:200] or exc.reason}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 0:
                time.sleep(2)
                continue
            raise RuntimeError(f"connection failed: {exc}") from None


def get_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8-sig")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 0:
                time.sleep(2)
                continue
            raise RuntimeError(f"connection failed: {exc}") from None


# ----------------------------------------------------------------- FRED ----
def fetch_fred(spec, key):
    series_id = spec["id"]
    cap = CAP.get(spec.get("freq", "M"), 40)
    label, unit = spec.get("name", series_id), spec.get("unit", "")
    api_error = "FRED_API_KEY missing or invalid format"
    if len(key) == 32 and key.isalnum() and key.islower():
        params = urllib.parse.urlencode({
            "series_id": series_id, "api_key": key, "file_type": "json",
            "sort_order": "desc", "limit": cap + 10,
        })
        try:
            payload = get_json("https://api.stlouisfed.org/fred/series/observations?" + params)
            valid = [x for x in payload.get("observations", []) if x.get("value") not in (None, ".", "")]
            if valid:
                history = [{"date": x["date"], "value": float(x["value"])} for x in reversed(valid)][-cap:]
                last = history[-1]
                return {"name": label, "series": series_id, "date": last["date"], "value": last["value"],
                        "unit": unit, "source": "FRED", "history": history}
            api_error = "API returned no usable observations"
        except Exception as exc:  # fall back to the public CSV endpoint
            api_error = str(exc)
    csv_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urllib.parse.urlencode({"id": series_id})
    text = get_text(csv_url)
    records = list(csv.DictReader(io.StringIO(text)))
    valid = [x for x in records if x.get(series_id) not in (None, ".", "")]
    if not valid:
        raise RuntimeError(f"{api_error} | CSV returned no usable observations")
    date_key = "observation_date" if "observation_date" in valid[0] else "DATE"
    history = [{"date": x[date_key], "value": float(x[series_id])} for x in valid[-cap:]]
    last = history[-1]
    return {"name": label, "series": series_id, "date": last["date"], "value": last["value"],
            "unit": unit, "source": "FRED", "history": history}


def collect_fred():
    cfg = ROOT / "config" / "fred-series.json"
    specs = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else []
    key = os.environ.get("FRED_API_KEY", "").strip()

    def work(spec):
        try:
            return fetch_fred(spec, key), None
        except Exception as exc:
            return None, f'{spec.get("id")}: {exc}'

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(work, specs))
    rows = [r for r, _ in results if r]
    errors = [e for _, e in results if e]
    return rows, ("; ".join(errors) if errors else "OK")


# ----------------------------------------------------------------- ECOS ----
def period(cycle, d):
    if cycle == "D":
        return d.strftime("%Y%m%d")
    if cycle == "Q":
        return f"{d.year}Q{((d.month - 1) // 3) + 1}"
    if cycle == "A":
        return d.strftime("%Y")
    return d.strftime("%Y%m")


def fetch_ecos(spec, key):
    stat = str(spec["stat_code"])
    cycle = str(spec.get("cycle", "M")).upper()
    today = date.today()
    lookback = {"D": 365, "M": 365 * 3, "Q": 365 * 6, "A": 365 * 16}.get(cycle, 365 * 3)
    window_start = today - timedelta(days=lookback)
    item_codes = [str(spec.get("item_code" + str(i), "")) for i in range(1, 5)]
    last_item = max((i for i, v in enumerate(item_codes) if v), default=-1)
    if cycle == "D":
        # ECOS returns at most 100 rows per request: split into 90-day windows.
        segments, cursor = [], window_start
        while cursor <= today:
            seg_end = min(cursor + timedelta(days=89), today)
            segments.append((period(cycle, cursor), period(cycle, seg_end)))
            cursor = seg_end + timedelta(days=1)
    else:
        segments = [(str(spec.get("start_dt") or period(cycle, window_start)),
                     str(spec.get("end_dt") or period(cycle, today)))]
    valid = []
    for seg_start, seg_end in segments:
        parts = ["StatisticSearch", key, "json", "kr", "1", "100", stat, cycle, seg_start, seg_end] + item_codes[:last_item + 1]
        url = "https://ecos.bok.or.kr/api/" + "/".join(urllib.parse.quote(p, safe="") for p in parts)
        payload = get_json(url)
        block = payload.get("StatisticSearch", {})
        if isinstance(block, list):
            block = block[0] if block else {}
        records = block.get("row", []) if isinstance(block, dict) else []
        valid.extend(x for x in records if x.get("DATA_VALUE") not in (None, ""))
    valid.sort(key=lambda x: x.get("TIME", ""))
    if not valid:
        raise RuntimeError("no observations returned")
    cap = CAP.get(cycle, 40)
    history = [{"date": x.get("TIME", ""), "value": float(str(x["DATA_VALUE"]).replace(",", ""))} for x in valid[-cap:]]
    last = history[-1]
    return {"name": str(spec.get("name", stat)), "series": str(spec.get("series_id", stat)),
            "date": last["date"], "value": last["value"], "unit": str(spec.get("unit", "")),
            "source": "ECOS", "history": history}


def collect_ecos():
    key = os.environ.get("ECOS_API_KEY", "").strip()
    raw = os.environ.get("ECOS_SERIES_JSON", "").strip()
    if not raw:
        cfg = ROOT / "config" / "ecos-series.json"
        if cfg.exists():
            raw = cfg.read_text(encoding="utf-8").strip()
    if not key:
        return [], "ECOS_API_KEY not configured"
    try:
        specs = json.loads(raw) if raw else []
        if not isinstance(specs, list):
            raise ValueError("series config must be a JSON array")
    except Exception as exc:
        return [], "Invalid ECOS series config: " + str(exc)
    if not specs:
        return [], "No ECOS series configured"

    def work(spec):
        try:
            return fetch_ecos(spec, key), None
        except Exception as exc:
            return None, f'{spec.get("series_id", spec.get("stat_code"))}: {exc}'

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(work, specs))
    rows = [r for r, _ in results if r]
    errors = [e for _, e in results if e]
    return rows, ("; ".join(errors) if errors else "OK")


# --------------------------------------------------------------- MARKET ----
import re


def fetch_yahoo(spec):
    sym = urllib.parse.quote(spec["symbol"], safe="")
    payload, err = None, None
    for attempt, host in enumerate(("query1", "query2", "query1")):
        try:
            payload = get_json(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d")
            break
        except Exception as exc:  # rate limited: back off, try sibling host
            err = exc
            time.sleep(2 * (attempt + 1))
    if payload is None:
        raise err
    res = (payload.get("chart", {}).get("result") or [None])[0]
    if not res:
        raise RuntimeError("no result")
    off = int(res.get("meta", {}).get("gmtoffset", 0))
    closes = res["indicators"]["quote"][0]["close"]
    hist = {}
    for ts, c in zip(res.get("timestamp", []), closes):
        if c is None:
            continue
        hist[datetime.fromtimestamp(ts + off, tz=timezone.utc).strftime("%Y-%m-%d")] = float(c)
    return finish_market(spec, hist, "Yahoo")


def fetch_naver(spec):
    end = date.today()
    start = end - timedelta(days=400)
    url = ("https://api.finance.naver.com/siseJson.naver?" + urllib.parse.urlencode({
        "symbol": spec["symbol"], "requestType": "1", "timeframe": "day",
        "startTime": start.strftime("%Y%m%d"), "endTime": end.strftime("%Y%m%d")}))
    text = get_text(url)
    hist = {}
    for m in re.finditer(r'\[\s*["\'](\d{8})["\']\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)', text):
        d = m.group(1)
        hist[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = float(m.group(5))
    return finish_market(spec, hist, "Naver")


def finish_market(spec, hist, source):
    if not hist:
        raise RuntimeError("no observations returned")
    cap = CAP["D"]
    history = [{"date": k, "value": hist[k]} for k in sorted(hist)][-cap:]
    last = history[-1]
    return {"name": spec.get("name", spec["id"]), "series": spec["id"], "date": last["date"],
            "value": last["value"], "unit": "", "source": source, "history": history}


def _num(v):
    return float(str(v).replace(",", ""))


def fetch_naver_world(spec):
    """Naver world indices / FX / commodities (JSON). Tries two known endpoint families."""
    kind, code = spec["naver"]
    end = date.today()
    start = end - timedelta(days=400)
    hist, errs = {}, []
    if kind in ("index", "stock"):
        try:
            url = (f"https://api.stock.naver.com/chart/foreign/{kind}/{urllib.parse.quote(code, safe='')}/day?"
                   f"startDateTime={start:%Y%m%d}0000&endDateTime={end:%Y%m%d}0000")
            for r in json.loads(get_text(url)):
                hist[f"{r['localDate'][:4]}-{r['localDate'][4:6]}-{r['localDate'][6:8]}"] = _num(r["closePrice"])
        except Exception as exc:
            errs.append(f"chart-api {exc}")
    if not hist:
        try:
            size = None
            for page in range(1, 40):
                payload = None
                for sz in ((size,) if size else (60, 30, 20, 10)):
                    for base in ("https://m.stock.naver.com/front-api/marketIndex/prices?" + urllib.parse.urlencode({
                            "category": kind, "reutersCode": code, "page": page, "pageSize": sz}),
                            f"https://api.stock.naver.com/marketindex/{kind}/{urllib.parse.quote(code, safe='')}/prices?"
                            + urllib.parse.urlencode({"page": page, "pageSize": sz})):
                        try:
                            payload = json.loads(get_text(base))
                            size = sz
                            break
                        except Exception as exc:
                            errs.append(f"{exc}")
                    if payload is not None:
                        break
                if payload is None:
                    break
                rows = payload if isinstance(payload, list) else (payload.get("result") or [])
                if isinstance(rows, dict):
                    rows = rows.get("prices") or rows.get("list") or []
                if not rows:
                    break
                for r in rows:
                    d = str(r.get("localTradedAt") or r.get("localDate") or "")[:10].replace("/", "-")
                    if len(d) == 8:
                        d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                    hist[d] = _num(r["closePrice"])
                if min(hist) <= start.isoformat():
                    break
        except Exception as exc:
            errs.append(f"front-api {exc}")
    if not hist:
        raise RuntimeError("naver-world: " + ("; ".join(sorted(set(errs)))[:80] if errs else "empty"))
    return finish_market(spec, hist, "Naver")


def fetch_coingecko(spec):
    url = (f"https://api.coingecko.com/api/v3/coins/{spec['coingecko']}/market_chart?"
           "vs_currency=usd&days=365&interval=daily")
    payload = get_json(url)
    hist = {}
    for ms, price in payload.get("prices", []):
        hist[datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")] = float(price)
    return finish_market(spec, hist, "CoinGecko")


def fetch_stooq(spec):
    end = date.today()
    start = end - timedelta(days=400)
    url = "https://stooq.com/q/d/l/?" + urllib.parse.urlencode({
        "s": spec["stooq"], "i": "d", "d1": start.strftime("%Y%m%d"), "d2": end.strftime("%Y%m%d")})
    text = get_text(url)
    if not text.lstrip().lower().startswith("date,"):
        raise RuntimeError("stooq: " + text.strip()[:80])
    hist = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            hist[row["Date"]] = float(row["Close"])
        except (KeyError, ValueError, TypeError):
            continue
    return finish_market(spec, hist, "Stooq")


_yahoo_fail = {"n": 0}


def fetch_market(spec):
    if spec.get("src") == "naver":
        return fetch_naver(spec)
    errors = []
    if spec.get("coingecko"):
        try:
            row = fetch_coingecko(spec)
            time.sleep(2)
            return row
        except Exception as exc:
            errors.append(f"coingecko {exc}")
    if spec.get("naver"):
        try:
            return fetch_naver_world(spec)
        except Exception as exc:
            errors.append(str(exc)[:120])
    if _yahoo_fail["n"] < 3:  # after 3 straight failures Yahoo is treated as blocked
        try:
            row = fetch_yahoo(spec)
            _yahoo_fail["n"] = 0
            time.sleep(0.7)
            return row
        except Exception as exc:
            _yahoo_fail["n"] += 1
            errors.append(f"yahoo {exc}")
    if spec.get("stooq"):
        try:
            return fetch_stooq(spec)
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError(" / ".join(errors) or "no source")


def collect_market():
    cfg = ROOT / "config" / "market-series.json"
    specs = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else []

    def work(spec):
        try:
            return fetch_market(spec), None
        except Exception as exc:
            return None, f'{spec.get("id")}: {exc}'

    # sequential on purpose: Yahoo rate-limits aggressive clients
    results = [work(spec) for spec in specs]
    rows = [r for r, _ in results if r]
    errors = [e for _, e in results if e]
    return rows, ("; ".join(errors) if errors else "OK")


# ---------------------------------------------------------------- KOSIS ----
def fetch_kosis(spec, key):
    params = {"method": "getList", "apiKey": key, "itmId": spec.get("itmId", "ALL"), "objL1": spec.get("objL1", "ALL"),
              "objL2": spec.get("objL2", ""), "format": "json", "jsonVD": "Y", "prdSe": spec.get("prdSe", "Y"),
              "newEstPrdCnt": spec.get("count", 12), "orgId": spec["orgId"], "tblId": spec["tblId"]}
    payload = get_json("https://kosis.kr/openapi/Param/statisticsParameterData.do?" + urllib.parse.urlencode(params))
    if isinstance(payload, dict):
        raise RuntimeError(f"{payload.get('err', '')} {payload.get('errMsg', '')}".strip() or "unexpected response")
    hist = {}
    for r in payload:
        try:
            hist[str(r["PRD_DE"])] = _num(r["DT"])
        except (KeyError, ValueError, TypeError):
            continue
    if not hist:
        raise RuntimeError("no observations returned")
    history = [{"date": k, "value": hist[k]} for k in sorted(hist)]
    last = history[-1]
    return {"name": spec.get("name", spec["id"]), "series": spec["id"], "date": last["date"], "value": last["value"],
            "unit": "", "source": "KOSIS", "history": history}


def collect_kosis():
    key = os.environ.get("KOSIS_API_KEY", "").strip()
    cfg = ROOT / "config" / "kosis-series.json"
    specs = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else []
    if not key:
        return [], "SKIPPED (KOSIS_API_KEY not set)"
    out, errors = [], []
    for spec in specs:
        try:
            out.append(fetch_kosis(spec, key))
        except Exception as exc:
            errors.append(f'{spec["id"]}: {exc}')
    return out, ("; ".join(errors) if errors else "OK")


# ------------------------------------------------------- OpenFiscal (열린재정) ----
def fetch_openfiscal_year(key, year):
    """Sum 세출예산(확정) by 분야 and 소관(부처) for one fiscal year; amounts converted from 천원 to 조원."""
    by_fld, by_off, by_ep, total, page, got = {}, {}, {}, 0.0, 1, 0
    while True:
        url = "https://openapi.openfiscaldata.go.kr/ExpenditureBudgetInit5?" + urllib.parse.urlencode({
            "Key": key, "Type": "json", "pIndex": page, "pSize": 1000, "FSCL_YY": year})
        payload = get_json(url)
        if isinstance(payload, str):  # the API double-encodes some error payloads
            payload = json.loads(payload)
        block = payload.get("ExpenditureBudgetInit5")
        if not block:
            raise RuntimeError(str((payload.get("RESULT") or payload))[:120])
        head = block[0]["head"]
        count = int(head[0]["list_total_count"])
        code = (head[1].get("RESULT") or {}).get("CODE", "")
        if code != "INFO-000":
            raise RuntimeError(code)
        rows = block[1].get("row", [])
        for r in rows:
            if (r.get("FIN_DE_EP_NM") or "") != "일반지출":
                continue  # exclude 내부거래·보전지출 (double counting)
            amt = r.get("Y_YY_DFN_MEDI_KCUR_AMT")
            if amt is None:
                amt = r.get("Y_YY_MEDI_KCUR_AMT")
            if amt is None:
                continue
            v = float(amt) / 1e9
            total += v
            by_fld[r.get("FLD_NM") or "기타"] = by_fld.get(r.get("FLD_NM") or "기타", 0.0) + v
            by_off[r.get("OFFC_NM") or "기타"] = by_off.get(r.get("OFFC_NM") or "기타", 0.0) + v
        got += len(rows)
        if not rows or got >= count:
            break
        page += 1
    return total, by_fld, by_off, by_ep


def collect_fiscal(previous_rows):
    key = os.environ.get("OPENFISCAL_API_KEY", "").strip()
    if not key:
        return [], "SKIPPED (OPENFISCAL_API_KEY not set)"
    this_year = date.today().year
    table = {}  # series id -> {year: value}
    names = {}
    for r in previous_rows:
        names[r["series"]] = r.get("name", r["series"])
        table[r["series"]] = {h["date"]: h["value"] for h in r.get("history", [])}
    if "OF:META:v2" not in table:  # older, unfiltered aggregates are discarded
        table, names = {}, {}
    cached = set(table.get("OF:META:v2", {}))
    errors = []
    for year in range(this_year - 6, this_year + 1):
        if str(year) in cached and year < this_year - 1:
            continue  # settled years are not refetched
        try:
            total, fld, off, ep = fetch_openfiscal_year(key, year)
        except Exception as exc:
            errors.append(f"{year}: {exc}")
            continue
        table.setdefault("OF:TOTAL", {})[str(year)] = total
        names["OF:TOTAL"] = "세출예산 총계"
        for nm, v in fld.items():
            table.setdefault("OF:FLD:" + nm, {})[str(year)] = v
            names["OF:FLD:" + nm] = nm
        table.setdefault("OF:META:v2", {})[str(year)] = 1.0
        names["OF:META:v2"] = "meta"
        for nm, v in off.items():
            table.setdefault("OF:OFFC:" + nm, {})[str(year)] = v
            names["OF:OFFC:" + nm] = nm
    rows = []
    for sid, hist in table.items():
        history = [{"date": y, "value": round(hist[y], 3)} for y in sorted(hist)][-10:]
        if history:
            rows.append({"name": names.get(sid, sid), "series": sid, "date": history[-1]["date"],
                         "value": history[-1]["value"], "unit": "조원", "source": "열린재정", "history": history})
    return rows, ("; ".join(errors) if errors else "OK")


# ---------------------------------------------------------------- kalshi ----
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _kdollar(v):
    try:
        return float(v) * 100.0
    except (TypeError, ValueError):
        return None


def fetch_kalshi_group(spec, previous_rows, today):
    import re as _re
    data = get_json(f"{KALSHI_BASE}/markets?series_ticker={spec['series']}&status=open&limit=200")
    mk = data.get("markets", [])
    if spec.get("earliest_event") and mk:
        first = min(mk, key=lambda m: m.get("close_time") or "9")
        mk = [m for m in mk if m.get("event_ticker") == first.get("event_ticker")]
    prev = {str(r.get("series")): r for r in previous_rows}
    cand = []
    for m in mk:
        last = _kdollar(m.get("last_price_dollars"))
        bid, ask = _kdollar(m.get("yes_bid_dollars")), _kdollar(m.get("yes_ask_dollars"))
        mid = (bid + ask) / 2 if bid is not None and ask is not None and ask > 0 else None
        prob = last if last else mid
        if prob is None:
            continue
        cand.append((m, prob, bid, ask))
    if spec.get("near50"):
        cand = [c for c in cand if 0 < c[1] < 100]
        cand = sorted(cand, key=lambda c: abs(c[1] - 50))[: int(spec["near50"])]
    elif spec.get("top"):
        cand = sorted(cand, key=lambda c: -c[1])[: int(spec["top"])]
    names = spec.get("names", {})
    rows = []
    for m, prob, bid, ask in cand:
        ticker = m.get("ticker", "")
        sub = m.get("yes_sub_title") or ""
        suffix = ticker.rsplit("-", 1)[-1]
        label = spec.get("labels", {}).get(suffix) or names.get(sub) or sub or suffix
        rank = list(names).index(sub) if sub in names else None
        mm = _re.search(r"(?:At least|Above)\s*[^\d-]*(-?[\d,\.]+\s*[%a-zA-Z]*)", label)
        if mm and label not in names.values():
            label = mm.group(1).strip() + (" 이상" if label.startswith("At least") else " 초과")
        if rank is None:
            nm = _re.search(r"-?[\d,]*\.?\d+", sub.replace(",", ""))
            rank = float(nm.group(0)) if nm else None
        sid = "KX:" + ticker
        hist = [h for h in (prev.get(sid, {}).get("history") or []) if h.get("date") != today]
        hist.append({"date": today, "value": round(prob, 1)})
        rows.append({
            "name": label, "series": sid, "group": spec["series"], "date": today, "value": round(prob, 1),
            "unit": "%", "bid": bid, "ask": ask, "volume": _num(m.get("volume_fp")), "rank": rank,
            "close_time": m.get("close_time", ""), "source": "Kalshi", "history": hist[-400:],
        })
    return rows


def collect_kalshi(previous_rows):
    path = ROOT / "config" / "kalshi-series.json"
    if not path.exists():
        return previous_rows, "SKIPPED (no config)"
    specs = json.loads(path.read_text(encoding="utf-8"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out, errors, ok = [], [], 0
    for spec in specs:
        group_prev = [r for r in previous_rows if r.get("group") == spec["series"]]
        try:
            rows = fetch_kalshi_group(spec, group_prev, today)
            ok += 1
            out.extend(rows)
        except Exception as exc:  # keep the previous snapshot for that group
            errors.append(f"{spec['series']}: {exc}")
            out.extend(group_prev)
        time.sleep(0.3)
    if not ok:
        return previous_rows, "REFRESH FAILED; retained previous data — " + "; ".join(errors)
    return out, "OK" if not errors else "PARTIAL REFRESH; " + "; ".join(errors)


def settle(prev_rows, prev_at, fresh, status, now, key):
    """Return (rows, updated_at, status) applying the retain-on-failure policy."""
    if status.startswith("SKIPPED"):
        return prev_rows, prev_at, status
    if fresh:
        rows = merge(prev_rows, fresh)
        return rows, now, status if status == "OK" else "PARTIAL REFRESH; missing series retained — " + status
    return prev_rows, prev_at, "REFRESH FAILED; retained previous data — " + status


# ----------------------------------------------------------------- main ----
def merge(previous_rows, fresh_rows):
    merged = {str(r.get("series")): r for r in previous_rows}
    merged.update({str(r.get("series")): r for r in fresh_rows})
    return list(merged.values())


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    previous["fiscal"] = [r for r in previous.get("fiscal", []) if not str(r.get("series", "")).startswith("OF:EP:")]

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fred, fred_status = collect_fred()
    ecos, ecos_status = collect_ecos()
    market, market_status = collect_market()
    kosis, kosis_status = collect_kosis()
    fiscal, fiscal_status = collect_fiscal(previous.get("fiscal", []))
    kalshi_rows, kalshi_status = collect_kalshi(previous.get("kalshi", []))
    kalshi_at = now if not kalshi_status.startswith(("SKIPPED", "REFRESH FAILED")) else previous.get("kalshi_updated_at_utc", "")

    # A temporary provider failure must never erase the last usable observations.
    if fred:
        fred_rows, fred_at = merge(previous.get("fred", []), fred), now
        if fred_status != "OK":
            fred_status = "PARTIAL REFRESH; missing series retained — " + fred_status
    else:
        fred_rows, fred_at = previous.get("fred", []), previous.get("fred_updated_at_utc", "")
        fred_status = "REFRESH FAILED; retained previous data — " + fred_status

    if ecos:
        ecos_rows, ecos_at = merge(previous.get("ecos", []), ecos), now
        if ecos_status != "OK":
            ecos_status = "PARTIAL REFRESH; missing series retained — " + ecos_status
    else:
        ecos_rows, ecos_at = previous.get("ecos", []), previous.get("ecos_updated_at_utc", "")
        ecos_status = "REFRESH FAILED; retained previous data — " + ecos_status

    if market:
        market_rows, market_at = merge(previous.get("market", []), market), now
        if market_status != "OK":
            market_status = "PARTIAL REFRESH; missing series retained — " + market_status
    else:
        market_rows, market_at = previous.get("market", []), previous.get("market_updated_at_utc", "")
        market_status = "REFRESH FAILED; retained previous data — " + market_status

    kosis_rows, kosis_at, kosis_status = settle(previous.get("kosis", []), previous.get("kosis_updated_at_utc", ""), kosis, kosis_status, now, "kosis")
    fiscal_rows, fiscal_at, fiscal_status = settle(previous.get("fiscal", []), previous.get("fiscal_updated_at_utc", ""), fiscal, fiscal_status, now, "fiscal")

    payload = {
        "updated_at_utc": now,
        "fred_updated_at_utc": fred_at,
        "ecos_updated_at_utc": ecos_at,
        "fred_status": fred_status,
        "ecos_status": ecos_status,
        "fred": fred_rows,
        "ecos": ecos_rows,
        "market_updated_at_utc": market_at,
        "market_status": market_status,
        "market": market_rows,
        "kosis_updated_at_utc": kosis_at,
        "kosis_status": kosis_status,
        "kosis": kosis_rows,
        "fiscal_updated_at_utc": fiscal_at,
        "fiscal_status": fiscal_status,
        "fiscal": fiscal_rows,
        "kalshi_updated_at_utc": kalshi_at,
        "kalshi_status": kalshi_status,
        "kalshi": kalshi_rows,
    }
    # Compact JSON keeps the file small for mobile downloads.
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}: FRED={len(fred_rows)} (fresh {len(fred)}), ECOS={len(ecos_rows)} (fresh {len(ecos)}), MARKET={len(market_rows)} (fresh {len(market)}), KOSIS={len(kosis_rows)}, FISCAL={len(fiscal_rows)}")


if __name__ == "__main__":
    main()
