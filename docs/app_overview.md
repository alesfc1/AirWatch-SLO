# AirWatch GeoSlovenija — App Overview

A high-level walkthrough of what the project does, where the data comes
from, how it flows through the system, and what the user actually sees
on screen. For pipeline-specific reference material see
[`pipeline.md`](pipeline.md), [`pipeline_data.md`](pipeline_data.md), and
[`event_pipeline.md`](event_pipeline.md).

---

## 1. What the app is

**AirWatch GeoSlovenija** visualises atmospheric pollution over Slovenia
using **Sentinel-5P** satellite data, aggregated per **NUTS3 region**
(12 statistical regions of Slovenia). Instead of showing a generic
monthly time-series, the dashboard frames the data around a small set
of named **events** (industrial fires, wildfires, industrial cases) and
lets the user scrub through the days of the event's month to see how
the pollutant signature evolved across the country.

There are two front-ends in the repo:

| Dashboard | Stack | Status | Purpose |
| --- | --- | --- | --- |
| [`dashboard_shiny/`](../dashboard_shiny/) | Python Shiny + Plotly | **Primary** | Event-driven "mission control" UI (light theme), reads CSVs directly from `outputs/`. |
| [`dashboard/`](../dashboard/) | Python Dash + dash-bootstrap-components | Secondary / legacy | Monthly NO₂ choropleth, reads CSVs (and optionally PostGIS) — wired up for Docker. |

Most active development is in the Shiny app — that's the UI described
below.

---

## 2. Where the data comes from

### 2.1 Satellite source

- **Sentinel-5P TROPOMI** (ESA Copernicus). Tropospheric column
  densities for: **NO₂, CO, HCHO, SO₂, AAI** (UV aerosol index).
- Pulled through the **Sentinel Hub Statistical API**, not via raw
  `.nc` downloads. Sentinel Hub computes the spatial aggregation per
  polygon, so we only handle small JSON responses.

### 2.2 Credentials

Read from environment variables (`.env`, never committed):

```
SH_CLIENT_ID
SH_CLIENT_SECRET
```

See [`.env.example`](../.env.example). Optionally points at Copernicus
Data Space Ecosystem (CDSE) instead of Sinergise.

### 2.3 Geographic reference

Slovenian NUTS3 polygons from Eurostat (raw input):

```
reference_data/regions/raw/NUTS_RG_20M_2024_4326_LEVL_3.geojson
```

Filtered to `CNTR_CODE = SI`, `LEVL_CODE = 3` → 12 regions, written to:

```
reference_data/regions/processed/slovenia_nuts3_regions_2024_4326.geojson   # EPSG:4326 (web/API)
reference_data/regions/processed/slovenia_nuts3_regions_2024_3794.gpkg      # EPSG:3794 (SI analysis)
```

CRS rule: **4326** for Sentinel Hub requests and the dashboard map;
**3794 / D96-TM** for Slovenian spatial analysis.

### 2.4 Event definitions

The three events the dashboard currently knows about:

| `event_id` | Event | Type | Analysis month | Event window |
| --- | --- | --- | --- | --- |
| `spar_fire_2025` | SPAR/BTC warehouse fire (Ljubljana) | industrial_fire | Dec 2025 | 2025-12-14 (single day) |
| `kras_fire_2022` | Goriški Kras wildfire | wildfire | Jul 2022 | 2022-07-15 → 2022-07-31 |
| `cinkarna_celje_2019` | Cinkarna Celje industrial case | industrial_case | Dec 2019 | 2019-12-01 → 2019-12-31 |

Each event carries: analysis range, event window, lat/lon, location
name, Slovene description / interpretation note / confidence note, and
the list of relevant pollutants. The dashboard reads these from the
metadata JSON (see §3.3).

---

## 3. Data pipeline (overview)

The detailed step-by-step lives in [`pipeline.md`](pipeline.md) and
[`event_pipeline.md`](event_pipeline.md). High-level flow:

```
Eurostat NUTS GeoJSON ─┐
                       ▼
              01_prepare_regions       ──►  reference_data/regions/processed/
                       │
events.json ──────────►│
                       ▼
              02_build_statistical_requests
                       │
                       ▼  one request per (event × region × pollutant)
              outputs/sentinel_hub_stats/event_request_manifest.json
                       │
                       ▼
              03_run_statistical_api   ──►  Sentinel Hub Statistical API
                       │                    (aggregationInterval = P1D)
                       ▼
              outputs/sentinel_hub_stats/raw_events/             (NO₂ only)
              outputs/sentinel_hub_stats/raw_events_multipollutant/
                       │
                       ▼
              04_parse_statistical_results --events
                       │
                       ▼
              outputs/timeseries/event_no2_nuts3_daily.csv             + _metadata.json
              outputs/timeseries/event_pollutants_nuts3_daily.csv      + _metadata.json
              outputs/timeseries/no2_nuts3_timeseries.csv              (legacy monthly)
                       │
                       ▼
                  Shiny dashboard reads these CSVs directly
                  (no PostGIS dependency for the event UI)
```

The Sentinel-5P NO₂ band is returned in `mol/m²`; the parser multiplies
by 10⁶ so the CSV is already in **µmol/m²**. Other pollutants use
their own display units (see §3.3).

### 3.1 CSV schema — `event_no2_nuts3_daily.csv` (single-pollutant)

| column | meaning |
| --- | --- |
| `event_id`, `event_name`, `event_type` | from `events.json` |
| `date_from`, `date_to` | ISO interval boundaries returned by Sentinel Hub |
| `day_index` | 1-based day within the event's analysis month |
| `region_code`, `region_name` | NUTS3 (e.g. `SI041` / *Osrednjeslovenska*) |
| `pollutant` | `NO2` |
| `value_mean`, `value_min`, `value_max`, `value_stdev` | µmol/m² |
| `sample_count`, `no_data_count`, `data_mask_valid_count` | pixel counts |
| `unit`, `source`, `aggregation_interval` | `µmol/m²`, Sentinel Hub source string, `P1D` |
| `quality_status` | `good` / `partial` / `missing` (see §3.4) |

### 3.2 CSV schema — `event_pollutants_nuts3_daily.csv` (long-format multi-pollutant)

Same columns plus `pollutant` (NO₂ / CO / HCHO / SO₂ / AAI) and
`display_unit` (µmol/m², mmol/m², index). One row per
`(event × pollutant × region × day)`.

The Shiny app prefers this file and falls back to the NO₂-only CSV.

### 3.3 Metadata JSON

`outputs/timeseries/event_pollutants_nuts3_daily_metadata.json` carries:

- `dataset_status` — `live` (from Sentinel Hub) or `sample` (from
  `generate_sample_event_data.py`). Drives the badge in the top-right.
- `pollutants_available`, `pollutants_spec` — display name, short label,
  unit, decimals, Slovene relevance description per pollutant.
- `events[]` — full event records (the same as `events.json`) plus the
  list of pollutants relevant for that event and a `default_pollutant`.

### 3.4 Quality status

Computed per `(region × day)` from pixel counts:

- `good` — valid / sample ≥ 0.5 and a mean exists.
- `partial` — some valid pixels, but valid / sample < 0.5.
- `missing` — no valid pixels and/or no mean value.

The dashboard preserves these states instead of imputing values, and
shows them in the region intel panel (pill) and the bottom-right
legend.

---

## 4. What the Shiny dashboard displays

[`dashboard_shiny/app.py`](../dashboard_shiny/app.py) is a single-page
"satellite mission control" layout. It reads three files at startup:

```
outputs/timeseries/event_no2_nuts3_daily.csv        (or _pollutants_)
outputs/timeseries/event_no2_nuts3_daily_metadata.json
reference_data/regions/processed/slovenia_nuts3_regions_2024_4326.geojson
```

If any are missing the app degrades gracefully and shows a banner — it
does not crash.

### Layout, top to bottom

1. **Mission header** — brand mark, event chip rail (one chip per
   event), pollutant chip rail (NO₂ / CO / HCHO / SO₂ / AAI), and
   status badges (`Live` / `Sample` dataset, Sentinel-5P / ESA tag).

2. **Map stage** — full-bleed Plotly Mapbox choropleth on a
   `carto-positron` base. The fill colour encodes the day's value for
   the chosen pollutant. Four floating glass overlays sit on top:
   - **TL** — mission heading and the *Dejanske / Odstopanje*
     (absolute / anomaly) mode toggle. In anomaly mode each region's
     mean is compared to the event-month average; a diverging cyan ↔
     red scale shows cleaner vs. elevated.
   - **TR** — telemetry strip: Slovenia average, highest region,
     lowest region, source, dataset status for the selected day.
   - **BL** — region intel panel: NUTS3 dropdown, the selected
     region's daily value, quality pill, min/max/stdev mini-stats, and
     rank for the day.
   - **BR** — colour-ramp legend, quality-pip legend (good / partial /
     missing), and a coords/scale strip.

   The map also draws:
   - A pulsing red halo + label at the event's lat/lon
     (`event_lat`, `event_lon`).
   - A cyan highlight ring at the selected region's centroid.

3. **Timeline dock** — play/pause button + day slider (one step per
   day in the event's analysis month). The slider's track shows a
   shaded **event-window band** so the analysis month is visually
   separated from the actual event days. Stepping the day fires a
   custom `map_restyle` message so only the day's z/customdata ship
   over the websocket — the mapbox tiles and geojson stay mounted.

4. **Trend chart** — Plotly line chart for the selected region (or
   Slovenia composite if none is selected). Min–max band, cyan mean
   line, single-day vertical marker for one-day events or shaded
   `vrect` for multi-day events. A dotted day-marker line tracks the
   slider in real time, driven from [`www/app.js`](../dashboard_shiny/www/app.js).

5. **Methodology panel** — restates CRS, units, aggregation interval,
   and the main interpretive limitations (column density vs.
   concentration, S5P resolution, daily coverage gaps).

6. **Status footer** — dataset status string and version line.

### Theming

- Light theme, defined entirely in [`www/styles.css`](../dashboard_shiny/www/styles.css)
  via CSS variables (`--bg-*`, `--t1..t5`, `--cyan`, `--hot`, etc.).
  Plotly figures and the mapbox tile style (`carto-positron`) match
  the same palette in [`app.py`](../dashboard_shiny/app.py).
- Fonts: Manrope (display), DM Sans (body), JetBrains Mono (numeric /
  labels), loaded from Google Fonts.

---

## 5. The secondary Dash app (`dashboard/`)

[`dashboard/app.py`](../dashboard/app.py) is a simpler Plotly Dash UI
focused on **monthly NO₂** (not events):

- Reads `outputs/timeseries/no2_nuts3_timeseries.csv` and the same
  processed GeoJSON.
- Period dropdown (YYYY-MM), NUTS3 choropleth (`carto-positron`),
  per-region trend chart, and a stats panel for the clicked region.
- Optional PostGIS path via [`postgresdb.py`](../dashboard/postgresdb.py)
  (config in [`config.py`](../dashboard/config.py), env-driven —
  `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`,
  `DATABASE_USER`, `DATABASE_PASSWORD`).
- Containerised via [`Dockerfile`](../dashboard/Dockerfile) — runs
  `scripts/import_to_db.py` before starting the server.

This app is useful for a quick monthly view; the event-driven story
lives in the Shiny app.

---

## 6. Repository layout

```
airwatch-geoslovenija/
├── dashboard_shiny/        Primary Shiny dashboard (event-driven)
│   ├── app.py              Single-file app, Plotly + custom HTML
│   ├── www/                styles.css (light theme), app.js (custom JS bridges)
│   └── tests/
├── dashboard/              Secondary Dash dashboard (monthly NO₂)
│   ├── app.py, config.py, postgresdb.py, assets/style.css
│   └── Dockerfile          Containerised version, also imports to PostGIS
├── data_pipeline 2/        Legacy .nc-based pipeline (kept for reference)
│   └── scripts/            Older S5P download / crop / aggregate scripts
├── reference_data/
│   └── regions/
│       ├── raw/            Eurostat NUTS3 GeoJSON input
│       └── processed/      Slovenia-only NUTS3 in 4326 + 3794
├── outputs/
│   ├── sentinel_hub_stats/
│   │   ├── request_manifest.json, event_request_manifest.json
│   │   ├── raw/, raw_events/, raw_events_multipollutant/
│   │   └── …               One JSON per (event × region × pollutant) S-Hub response
│   ├── timeseries/         Final CSVs the dashboards read
│   ├── no2_by_region/      Legacy per-region results
│   └── final_v2.csv        Wide table used by the Dash app + import_to_db
├── shapefiles/             NUTS_SL_01m_2024 .shp + sidecars (legacy)
├── data/                   Misc tabular inputs (PM2.5 monthly CSVs, GDP, etc.)
├── database/               Placeholder for PostGIS artefacts (.gitkeep only)
├── scripts/                import_to_db.py, shape_to_postgres.py, notebooks
├── docs/                   pipeline.md, pipeline_data.md, event_pipeline.md, this file
└── .env / .env.example     Sentinel Hub credentials (.env is git-ignored)
```

---

## 7. How to run

### Fastest path — sample data + Shiny dashboard

```bash
python data_pipeline/sentinel_hub_stats/generate_sample_event_data.py
python dashboard_shiny/app.py
```

The generator writes both the CSV and the metadata JSON. The dashboard
shows the data with a *Sample data* badge.

### Live Sentinel Hub pipeline

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

Useful flags for the manifest builder: `--event-id`, `--region-code`,
`--max-requests`, `--aggregation-interval P1D`.

### Dash app (monthly NO₂)

```bash
python dashboard/app.py
# or via Docker
docker build -f dashboard/Dockerfile -t airwatch-dash .
docker run --env-file .env -p 8050:8050 airwatch-dash
```

---

## 8. Limitations

- **Column density, not concentration.** Sentinel-5P NO₂ is a
  *tropospheric column density* (mol/m² → µmol/m²), not a direct
  ground-level concentration. Spatial and temporal patterns are
  meaningful; absolute health-relevant numbers require ARSO ground
  measurements.
- **Coarse spatial resolution.** TROPOMI's nadir pixel is ~5.5 × 3.5 km;
  small NUTS3 polygons are covered by only a few pixels per day. This
  is why `quality_status = partial` shows up frequently for the smaller
  regions.
- **Daily coverage gaps.** A single S5P orbit can miss areas, and cloud
  cover further reduces valid pixels. Days flagged `missing` are not
  imputed — they appear as un-coloured polygons in the map.
- **Correlation, not causation.** The event markers and shaded windows
  describe *temporal/spatial association* with the named incident; they
  do not, by themselves, prove that a given NO₂ anomaly was caused by
  the event.

---

## 9. At a glance

- **Three named events** × **12 NUTS3 regions** × **up to 5 pollutants**
  × **~30 days/month** ≈ a few thousand rows in
  `event_pollutants_nuts3_daily.csv`.
- **One full month per event** keeps the slider readable (~30 steps)
  and the Sentinel Hub bill small (one P1D request per region × event
  × pollutant).
- **No PostGIS dependency for the Shiny app** — the file-based CSV
  output is the contract between pipeline and UI. PostGIS is only used
  by the legacy Dash app.
