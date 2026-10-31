#!/usr/bin/env python3
"""Collect official macroeconomic observations for the Econ Dashboard.

Secrets:
  FRED_API_KEY (required for FRED)
  ECOS_API_KEY (optional for ECOS)

Repository variable:
  ECOS_SERIES_JSON (optional JSON array; see README comments below)
"""
import csv
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "official-macro.json"


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "ClerkEconTerminal/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Preserve the API's diagnostic message (e.g. invalid API key/parameter)
        # while never logging the request URL, which contains the API key.
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from None


def collect_fred():
    key = os.environ.get("FRED_API_KEY", "").strip()
    # Retain a compact history as well as the latest observation for trend charts.
    # Daily yields use 90 points; lower-frequency series use up to 24 observations.
    # The public FRED CSV fallback remains available even without an API key.
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
        api_error = "FRED_API_KEY missing or invalid format"
        if len(key) == 32 and key.isalnum() and key.islower():
            params = urllib.parse.urlencode({
                "series_id": series_id, "api_key": key, "file_type": "json",
                "sort_order": "desc", "limit": 90 if series_id in ("DGS10", "DGS2") else 24,
            })
            try:
                payload = get_json("https://api.stlouisfed.org/fred/series/observations?" + params)
                valid = [x for x in payload.get("observations", []) if x.get("value") not in (None, ".", "")]
                obs = valid[0] if valid else None
                if obs:
                    history = [{"date": x["date"], "value": float(x["value"])} for x in reversed(valid)]
                    rows.append({"name": label, "series": series_id, "date": obs["date"],
                                 "value": float(obs["value"]), "unit": unit, "source": "FRED",
                                 "history": history})
                    continue
                api_error = "FRED API returned no usable observations"
            except Exception as exc:
                api_error = str(exc)
        # FRED's public graph CSV endpoint does not require an API key.
        # This fallback keeps the dashboard operational when a Secret is missing/malformed.
        try:
            csv_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urllib.parse.urlencode({"id": series_id})
            req = urllib.request.Request(csv_url, headers={"User-Agent": "ClerkEconTerminal/1.0"})
            with urllib.request.urlopen(req, timeout=12) as response:
                text = response.read().decode("utf-8-sig")
            records = list(csv.DictReader(io.StringIO(text)))
            valid = [x for x in records if x.get(series_id) not in (None, ".", "")]
            obs = valid[-1] if valid else None
            if not obs:
                raise RuntimeError("public CSV returned no usable observations")
            count = 90 if series_id in ("DGS10", "DGS2") else 24
            history = [{"date": x["observation_date"], "value": float(x[series_id])} for x in valid[-count:]]
            rows.append({"name": label, "series": series_id, "date": obs["observation_date"],
                         "value": float(obs[series_id]), "unit": unit, "source": "FRED",
                         "history": history})
        except Exception as csv_exc:
            errors.append(series_id + ": " + api_error + " | CSV " + str(csv_exc))
    return rows, ("; ".join(errors) if errors else "OK")


def collect_ecos():
    key = os.environ.get("ECOS_API_KEY", "").strip()
    raw = os.environ.get("ECOS_SERIES_JSON", "").strip()
    if not raw:
        config_path = ROOT / "config" / "ecos-series.json"
        if config_path.exists():
            raw = config_path.read_text(encoding="utf-8").strip()
    if not key:
        return [], "ECOS_API_KEY not configured"
    if not raw:
        return [], "No ECOS series configured in config/ecos-series.json or ECOS_SERIES_JSON"
    try:
        specs = json.loads(raw)
        if not isinstance(specs, list):
            raise ValueError("ECOS_SERIES_JSON must be a JSON array")
    except Exception as exc:
        return [], "Invalid ECOS_SERIES_JSON: " + str(exc)
    if not specs:
        return [], "ECOS_SERIES_JSON is empty; no ECOS series selected"

    rows, errors = [], []
    today = date.today()
    for spec in specs:
        try:
            stat = str(spec["stat_code"])
            cycle = str(spec.get("cycle", "M")).upper()
            # Keep daily requests below ECOS's 100-row page limit so the
            # returned observations reach the latest date rather than stopping
            # at the first 100 historical records.
            lookback_days = {"D": 90, "M": 365 * 3, "Q": 365 * 5, "A": 365 * 15}.get(cycle, 365 * 3)
            window_start = today - timedelta(days=lookback_days)
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
            start = str(spec.get("start_dt") or period(window_start))
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
            valid = [x for x in records if x.get("DATA_VALUE") not in (None, "")]
            obs = valid[-1] if valid else None
            if obs:
                history = [{"date": x.get("TIME", ""),
                            "value": float(str(x["DATA_VALUE"]).replace(",", ""))}
                           for x in valid[-90:]]
                rows.append({
                    "name": str(spec.get("name", stat)), "series": stat,
                    "date": obs.get("TIME", ""), "value": float(str(obs["DATA_VALUE"]).replace(",", "")),
                    "unit": str(spec.get("unit", "")), "source": "ECOS",
                    "history": history,
                })
        except Exception as exc:
            errors.append(str(spec.get("name", spec.get("stat_code", "ECOS"))) + ": " + str(exc))
    return rows, ("; ".join(errors) if errors else "OK")


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fred, fred_status = collect_fred()
    ecos, ecos_status = collect_ecos()
    payload = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fred_status": fred_status,
        "ecos_status": ecos_status,
        "fred": fred,
        "ecos": ecos,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}: FRED={len(fred)}, ECOS={len(ecos)}")


# Trigger a fresh data collection after repository secret updates.
if __name__ == "__main__":
    main()
