#!/usr/bin/env python3
"""Collect official macroeconomic observations for the Econ Dashboard.

Secrets:
  FRED_API_KEY (required for FRED)
  ECOS_API_KEY (optional for ECOS)

Repository variable:
  ECOS_SERIES_JSON (optional JSON array; see README comments below)
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "official-macro.json"


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "ClerkEconTerminal/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def collect_fred():
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        return [], "FRED_API_KEY not configured"
    # Daily/weekly/monthly indicators. Latest non-missing observation is retained.
    series = [
        ("US 10Y Treasury", "DGS10", "%"),
        ("US 2Y Treasury", "DGS2", "%"),
        ("Federal Funds Rate", "FEDFUNDS", "%"),
        ("US CPI", "CPIAUCSL", "index"),
        ("US Unemployment", "UNRATE", "%"),
        ("US GDP", "GDP", "USD bn, SAAR"),
    ]
    rows = []
    errors = []
    for label, series_id, unit in series:
        params = urllib.parse.urlencode({
            "series_id": series_id, "api_key": key, "file_type": "json",
            "sort_order": "desc", "limit": 12,
        })
        try:
            payload = get_json("https://api.stlouisfed.org/fred/series/observations?" + params)
            obs = next((x for x in payload.get("observations", []) if x.get("value") not in (None, ".", "")), None)
            if obs:
                rows.append({"name": label, "series": series_id, "date": obs["date"],
                             "value": float(obs["value"]), "unit": unit, "source": "FRED"})
        except Exception as exc:
            errors.append(series_id + ": " + str(exc))
    return rows, ("; ".join(errors) if errors else "OK")


def collect_ecos():
    key = os.environ.get("ECOS_API_KEY", "").strip()
    raw = os.environ.get("ECOS_SERIES_JSON", "[]").strip()
    if not key:
        return [], "ECOS_API_KEY not configured"
    try:
        specs = json.loads(raw)
        if not isinstance(specs, list):
            raise ValueError("ECOS_SERIES_JSON must be a JSON array")
    except Exception as exc:
        return [], "Invalid ECOS_SERIES_JSON: " + str(exc)

    rows, errors = [], []
    today = date.today()
    for spec in specs:
        try:
            stat = str(spec["stat_code"])
            cycle = str(spec.get("cycle", "M")).upper()
            three_years_ago = today - timedelta(days=365 * 3)
            def period(d):
                if cycle == "D":
                    return d.strftime("%Y%m%d")
                if cycle == "M":
                    return d.strftime("%Y%m")
                if cycle == "Q":
                    return f"{d.year}Q{((d.month - 1) // 3) + 1}"
                if cycle == "A":
                    return d.strftime("%Y")
                return d.strftime("%Y%m")
            start = str(spec.get("start_dt") or period(three_years_ago))
            end = str(spec.get("end_dt") or period(today))
            item_codes = [str(spec.get("item_code" + str(i), "")) for i in range(1, 5)]
            last_item = max((i for i, value in enumerate(item_codes) if value), default=-1)
            parts = ["StatisticSearch", key, "json", "kr", "1", "100", stat, cycle, start, end] + item_codes[:last_item + 1]
            url = "https://ecos.bok.or.kr/api/" + "/".join(urllib.parse.quote(p, safe="") for p in parts)
            payload = get_json(url)
            block = payload.get("StatisticSearch", {})
            if isinstance(block, list):
                block = block[0] if block else {}
            records = block.get("row", []) if isinstance(block, dict) else []
            obs = next((x for x in reversed(records) if x.get("DATA_VALUE") not in (None, "")), None)
            if obs:
                rows.append({
                    "name": str(spec.get("name", stat)), "series": stat,
                    "date": obs.get("TIME", ""), "value": float(str(obs["DATA_VALUE"]).replace(",", "")),
                    "unit": str(spec.get("unit", "")), "source": "ECOS",
                })
        except Exception as exc:
            errors.append(str(spec.get("name", spec.get("stat_code", "ECOS"))) + ": " + str(exc))
    return rows, ("; ".join(errors) if errors else "OK")


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fred, fred_status = collect_fred()
    ecos, ecos_status = collect_ecos()
    payload = {
        "updated_at_utc": date.today().isoformat(),
        "fred_status": fred_status,
        "ecos_status": ecos_status,
        "fred": fred,
        "ecos": ecos,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}: FRED={len(fred)}, ECOS={len(ecos)}")


if __name__ == "__main__":
    main()
