# Cached Sentinel Hub Statistical API responses (multi-pollutant)

This directory holds the **raw JSON responses** returned by the
Copernicus Data Space Ecosystem (CDSE) Sentinel Hub Statistical API for
every (event × pollutant × NUTS3 region) request made by
`data_pipeline/sentinel_hub_stats/run_event_multipollutant.py`.

## Why this exists

Sentinel Hub API has monthly usage limits and processing-unit quotas. To
avoid re-spending quota on data we already have, the pipeline is
idempotent: if the raw response file for a request is already on disk,
the API is NOT called again.

These files are intentionally **committed to the repo** (they are not in
`.gitignore`). They are the on-disk cache that backs the
`event_pollutants_nuts3_daily.csv` produced for the dashboard.

## File naming convention

```
<event_id>_<region_code>_<POLLUTANT>_<analysis_start>_<analysis_end>.json
```

Example:

```
spar_fire_2025_SI044_HCHO_2025-12-01_2026-01-01.json
```

## How to rebuild the parsed CSV without calling the API

If `event_pollutants_nuts3_daily.csv` is missing but these raw files are
intact, run:

```bash
python data_pipeline/sentinel_hub_stats/run_event_multipollutant.py --parse-only
```

This will read the cached JSON, re-apply unit conversions, and rewrite
the CSV + metadata file. **It will NOT contact the API**, so it consumes
no quota and works offline.

## How to refresh a specific event/pollutant

If you want to refetch one combination (e.g. you suspect a stale response):

```bash
python data_pipeline/sentinel_hub_stats/run_event_multipollutant.py \\
    --event-id spar_fire_2025 --pollutant CO --overwrite
```

`--overwrite` forces an API call for the requested set; everything else
remains cached.

## What is the total volume

84 JSON files, ~1.5 MB total, covering:

- 3 events: SPAR/BTC fire, Goriški Kras wildfire, Cinkarna Celje
- 4 pollutants from this directory (CO, HCHO, AAI, SO₂)
- NO₂ is in the legacy directory `outputs/sentinel_hub_stats/raw_events/`
- 12 Slovenian NUTS3 regions × 31 days per event

## Source

- Provider: Copernicus Data Space Ecosystem (CDSE)
- Endpoint: `https://sh.dataspace.copernicus.eu/api/v1/statistics`
- Satellite: Sentinel-5P (TROPOMI), Level-2 products
- Aggregation: daily (P1D)
- Resolution: 0.05° (~5.5 × 3.5 km native pixel)
