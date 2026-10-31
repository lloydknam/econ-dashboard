# Econ Dashboard

Kalshi-inspired global macro and market monitoring dashboard.

## Data sources

- **TradingView widgets**: global equity indices, FX, yields, commodities and economic calendar. Market data may be delayed according to provider/exchange rules.
- **World Bank WDI API**: annual GDP growth, CPI inflation and unemployment for selected economies.
- **FRED**: US 10Y/2Y Treasury yields, federal funds rate, CPI, unemployment and GDP. The collector first uses the FRED API when a correctly formatted key is available, then falls back to FRED's public graph CSV endpoint.
- **Bank of Korea ECOS**: policy rate, USD/KRW reference exchange rate and 3-year Treasury yield using the series in `config/ecos-series.json`.

## Automated refresh

GitHub Actions runs every six hours and whenever the collector or workflow is changed. It writes the latest observations to `data/official-macro.json` and commits the updated file.

### Repository configuration

- `FRED_API_KEY` (optional): valid 32-character FRED API key. The public CSV fallback is used when absent or malformed.
- `ECOS_API_KEY` (required for ECOS): Open API key issued by the Bank of Korea.
- `ECOS_SERIES_JSON` (optional override): JSON array with ECOS series definitions. When omitted, the checked-in `config/ecos-series.json` is used.

Do not commit API keys or place them in browser JavaScript. GitHub Actions secrets are used only by the collector.

## Local test

```bash
python -m py_compile scripts/collect_official_macro.py
python scripts/collect_official_macro.py
python -m json.tool data/official-macro.json
```

## Publish

The dashboard is a static site. If GitHub Pages is enabled for this repository, select **Deploy from a branch**, branch `main`, folder `/ (root)`. The entry page is `index.html`.

## Important notes

- Annual World Bank observations and daily/monthly official market indicators have different reference periods. Each observation carries its own date.
- FRED and ECOS data are fetched server-side by GitHub Actions; API keys are never exposed to the public page.
- This dashboard is for information and visualization, not investment advice or an official statistical publication.
