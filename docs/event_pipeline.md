# AirWatch GeoSlovenija — Event-based NO2 Pipeline

This document describes the event-based daily NO2 pipeline and the Shiny
Python dashboard that visualizes its output.

## Main idea

The project shifts the user-facing focus from generic monthly NO2 time
series to a small number of named **events** in Slovenia. For each event
we retrieve **daily** Sentinel-5P NO2 statistics through the Sentinel Hub
**Statistical API**, aggregate them at the **NUTS3 region** level, and
expose them as a Shiny dashboard with:

- an event selector,
- a day slider that animates the month, and
- a NUTS3 choropleth map plus a regional trend chart.

## The three events

| event_id              | event_name                     | event_type        | analysis month  | event window         | location (lat, lon)     |
| --------------------- | ------------------------------ | ----------------- | --------------- | -------------------- | ----------------------- |
| `spar_fire_2025`      | SPAR/BTC fire                  | industrial_fire   | December 2025   | 2025-12-14           | 46.064, 14.549 (Ljubljana, Letališka c.) |
| `kras_fire_2022`      | Goriški Kras wildfire          | wildfire          | July 2022       | 2022-07-15 → 2022-07-31 | 45.85, 13.62 (Goriški Kras) |
| `cinkarna_celje_2019` | Cinkarna Celje industrial case | industrial_case   | December 2019   | 2019-12-01 → 2019-12-31 (case-study period) | 46.236, 15.267 (Cinkarna Celje, Kidričeva 26) |

The events are defined in `data_pipeline/events/events.json`. Each event
defines:

- `analysis_start` / `analysis_end` — the **Sentinel Hub Statistical API
  time range** for daily NO2 aggregation. Always covers a full calendar
  month.
- `event_start` / `event_end` — the **actual event window** used only by
  the dashboard for interpretation markers (vertical line for a one-day
  event, shaded vrect for a multi-day event). These do **not** affect
  the API request.
- `event_lat` / `event_lon` and `event_location_name` — used to draw an
  event marker on the choropleth map.
- `description`, `interpretation_note`, `confidence_note` — visible in
  the dashboard event info panel.
- `aggregation_interval` (`P1D`), `month_label`.

`start_date` / `end_date` are kept as backward-compatible aliases for
`analysis_start` / `analysis_end`. New consumers should use the
`analysis_*` names.

## Why daily aggregation (P1D)?

Each event needs to be inspected day by day during the month it
occurred — a single monthly average would hide the actual peak. By
requesting `aggregationInterval = P1D` we ask Sentinel Hub to return
**one statistic record per day** inside the requested time range.

## Why one full month per event?

A single month gives a meaningful before/after context window around
the event peak while still keeping the dataset small and a slider with
~31 steps usable in the UI. With 3 events × 12 NUTS3 regions this is
**36 Statistical API requests** instead of 36 × 31 = 1 116 daily
requests.

## Why Sentinel Hub Statistical API and not `.nc` downloads?

- Sentinel Hub does the spatial aggregation per polygon for us — we get
  per-NUTS3 stats directly, with no need to download large `.nc`
  granules or do gridded raster math locally.
- A single request covers an entire month per region with daily
  aggregation, so the I/O is minimal and the pipeline can run from a
  laptop or CI without a NAS.
- The project rules explicitly forbid downloading `.nc` files and using
  PostGIS; the Statistical API output (JSON) and a CSV file are the
  only local artifacts we need.


## CRS conventions

| Use case                              | CRS         |
| ------------------------------------- | ----------- |
| Sentinel Hub Statistical API geometry | EPSG:4326   |
| Web / Leaflet / dashboard map         | EPSG:4326   |
| Slovenian spatial analysis/validation | EPSG:3794   |

The processed regions live in both formats:

- `reference_data/regions/processed/slovenia_nuts3_regions_2024_4326.geojson`
- `reference_data/regions/processed/slovenia_nuts3_regions_2024_3794.gpkg`

## Output CSV schema

`outputs/timeseries/event_no2_nuts3_daily.csv`

| column                  | meaning                                        |
| ----------------------- | ---------------------------------------------- |
| `event_id`              | matches `events.json`                          |
| `event_name`            | human-readable event name                      |
| `event_type`            | e.g. `industrial_fire`, `wildfire`             |
| `date_from`             | ISO interval start (Sentinel Hub-provided)     |
| `date_to`               | ISO interval end                               |
| `day_index`             | 1-based day within the selected event month    |
| `region_code`           | NUTS3 code, e.g. `SI041`                       |
| `region_name`           | NUTS3 name                                     |
| `pollutant`             | `NO2`                                          |
| `value_mean`            | daily mean NO2 in µmol/m²                      |
| `value_min`             | daily min NO2 in µmol/m²                       |
| `value_max`             | daily max NO2 in µmol/m²                       |
| `value_stdev`           | daily standard deviation in µmol/m²            |
| `sample_count`          | total pixels considered                        |
| `no_data_count`         | pixels without valid data                      |
| `data_mask_valid_count` | `sample_count - no_data_count`                 |
| `unit`                  | `µmol/m²` (after conversion)                   |
| `source`                | `Sentinel Hub Statistical API / Sentinel-5P`   |
| `aggregation_interval`  | `P1D`                                          |
| `quality_status`        | `good` / `partial` / `missing`                 |

The Sentinel-5P NO2 band returns values in **mol/m²**. The parser
multiplies by 1 000 000 so the CSV is already in **µmol/m²**:

```
µmol/m² = mol/m² × 1,000,000
```

`quality_status` thresholds (in `04_parse_statistical_results.py`):

- `missing` — no valid pixel and/or no mean value.
- `partial` — some valid pixels, but `valid / sample < 0.5`.
- `good` — `valid / sample >= 0.5` and a mean exists.

## Metadata JSON schema

`outputs/timeseries/event_no2_nuts3_daily_metadata.json`

```json
{
  "dataset_status": "sample | live",
  "source": "Sentinel Hub Statistical API / Sentinel-5P",
  "pollutant": "NO2",
  "unit": "µmol/m²",
  "aggregation_interval": "P1D",
  "generated_at": "...",
  "row_count": 1116,
  "region_count": 12,
  "event_count": 3,
  "events": [
    {
      "event_id": "...",
      "event_name": "...",
      "event_type": "...",
      "start_date": "...",
      "end_date": "...",
      "month_label": "...",
      "day_count": 31
    }
  ]
}
```

`dataset_status`:

- `sample` — produced by `generate_sample_event_data.py`.
- `live` — produced by the live Sentinel Hub pipeline after
  `04_parse_statistical_results.py --events`.

## Shiny dashboard

`dashboard_shiny/app.py` reads:

- `outputs/timeseries/event_no2_nuts3_daily.csv`
- `outputs/timeseries/event_no2_nuts3_daily_metadata.json`
- `reference_data/regions/processed/slovenia_nuts3_regions_2024_4326.geojson`

If the CSV is missing, the dashboard shows:

```
event_no2_nuts3_daily.csv not found. Run the Sentinel Hub event pipeline
first or generate sample data.
```

If the metadata file is missing:

```
Metadata file not found.
```

It does not crash on missing files.

UI controls:

- **Event** selector (e.g. *SPAR/BTC fire — December 2025*).
- **Region** selector (NUTS3 region or *All regions*).
- **Day slider** (one step per day, dynamic per event).
- Fixed pollutant pill: `NO2`.
- Dataset-status badge: `Sample data` or `Live Sentinel Hub data`.

UI outputs:

- **Event info panel** showing the event name, analysis month, event
  window, location, description, `interpretation_note` and
  `confidence_note` for the selected event.
- NUTS3 choropleth (color = `value_mean`), with an **event marker**
  drawn at `event_lat` / `event_lon`.
- Selected-date label (`YYYY-MM-DD` from `date_from`).
- Summary cards: Slovenia average, highest region, lowest region,
  selected region, source, dataset status.
- Region trend chart with optional min–max band and a shaded **event
  window** (or vertical line for single-day events) so the analysis
  month is visually separated from the actual event interpretation
  window.
- Methodology panel at the bottom restating CRS, unit, aggregation, and
  the main interpretive limitations.

## Running the sample data generator

This is the fastest way to see the dashboard working end-to-end:

```bash
python data_pipeline/sentinel_hub_stats/generate_sample_event_data.py
python dashboard_shiny/app.py
```

The generator writes both the CSV and the metadata JSON. The dashboard
shows the data with a *Sample data* badge.

## Running the live Sentinel Hub pipeline

```bash
export SH_CLIENT_ID="..."
export SH_CLIENT_SECRET="..."

python data_pipeline/sentinel_hub_stats/01_prepare_regions.py
python data_pipeline/sentinel_hub_stats/02_build_statistical_requests.py --events
python data_pipeline/sentinel_hub_stats/03_run_statistical_api.py \
    --manifest outputs/sentinel_hub_stats/event_request_manifest.json
python data_pipeline/sentinel_hub_stats/04_parse_statistical_results.py --events
python dashboard_shiny/app.py
```

Useful flags for the manifest builder:

- `--event-id`, `--region-code` — restrict to a single combination.
- `--max-requests` — useful for smoke tests (e.g. 2 items).
- `--aggregation-interval P1D` — override the per-event value.

## Limitations

- **Column density, not concentration.** Sentinel-5P NO2 is a
  tropospheric column density (mol/m² → µmol/m²), not a direct
  ground-level concentration.
- **Validation.** Local ARSO ground measurements are required to validate
  pollution claims; the pipeline alone is not sufficient.
- **Spatial resolution.** Sentinel-5P TROPOMI has a coarse pixel
  size (~5.5 × 3.5 km nadir). Small NUTS3 polygons are covered by very
  few pixels per day.
- **Daily coverage gaps.** A single S5P orbit can miss some areas, and
  cloud cover further reduces coverage. Daily values therefore may
  legitimately be `partial` or `missing`. The dashboard preserves these
  states instead of imputing values.
