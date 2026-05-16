# Open-Meteo Weather Context — July 2022

This document describes the Open-Meteo weather-context dataset added for the
**Goriški Kras wildfire (July 2022)** event in the AirWatch GeoSlovenija
dashboard. The dataset adds *weather context* to the Sentinel-5P pollutant
intelligence; it does **not** replace it and does **not** modify the existing
Sentinel Hub pollutant pipeline.

---

## Why weather context matters

Sentinel-5P measures column concentrations of pollutants (NO₂, CO, HCHO,
SO₂, AAI) over Slovenia. Without weather context the signal is hard to
interpret — the same fire can read very differently depending on:

- **Wind speed and direction** — disperse smoke and shift the pollutant
  plume to neighbouring NUTS3 regions, or pin it locally.
- **Precipitation** — wet deposition lowers measured column densities.
- **Relative humidity & cloud cover** — drive missing-data rates in
  Sentinel-5P (cloudy days yield fewer reliable retrievals) and affect
  aerosol optical signatures.
- **Temperature** — a strong proxy for fire-weather severity in the Kras.

Adding a single monthly summary of these variables per Slovene municipality
gives the analyst the minimum context needed to read the Sentinel-5P maps
without claiming any causal link.

---

## Source

- **API**: [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- **Endpoint**: `https://archive-api.open-meteo.com/v1/archive`
- **Time range**: `2022-07-01` → `2022-07-31` (inclusive)
- **Timezone**: `Europe/Ljubljana`
- **Spatial sampling**: one centroid per Slovene municipality
  (`reference_data/context_layers/eprostor_municipalities.geojson`, 212
  features from eProstor RPE OGC API Features).

Open-Meteo Historical is built on ERA5 / ECMWF reanalysis. The values are
therefore **modelled/reanalysis weather**, not official municipal
station measurements.

---

## Municipality-centroid approach

For every municipality polygon (Polygon or MultiPolygon) we compute the
**area-weighted centroid** in EPSG:4326 via the shoelace formula
(`geometry_centroid_lonlat` in the fetch script). For MultiPolygons the
larger sub-polygon dominates, which keeps coastal / split municipalities
sensible (e.g. Koper).

The centroid is then passed to Open-Meteo and the entire month of July 2022
is fetched in one call per municipality.

---

## Variables

The script requests the variables listed in the requirements. Open-Meteo's
**daily** endpoint exposes some directly; the rest are computed from
**hourly** data and averaged per day.

| Requested variable                 | How it is obtained                                                                 |
|------------------------------------|-------------------------------------------------------------------------------------|
| `temperature_2m_mean`              | Open-Meteo daily endpoint (`temperature_2m_mean`)                                  |
| `precipitation_sum`                | Open-Meteo daily endpoint (`precipitation_sum`)                                    |
| `wind_speed_10m_mean`              | **Derived**: mean of hourly `wind_speed_10m` per day, then per month               |
| `wind_speed_10m_max`               | Open-Meteo daily endpoint (`wind_speed_10m_max`)                                   |
| `wind_gusts_10m_max`               | Open-Meteo daily endpoint (`wind_gusts_10m_max`)                                   |
| `wind_direction_10m_dominant`      | Open-Meteo daily endpoint (`wind_direction_10m_dominant`), circular-mean over month|
| `relative_humidity_2m_mean`        | **Derived**: mean of hourly `relative_humidity_2m` per day, then per month         |
| `cloud_cover_mean`                 | **Derived**: mean of hourly `cloud_cover` per day, then per month                  |

The Open-Meteo daily endpoint does not expose mean wind speed, mean relative
humidity or mean cloud cover. The fetch script therefore also requests the
matching hourly series and averages them itself. This is documented in code
comments alongside the `HOURLY_VARIABLES` constant.

---

## Monthly summary (output CSV)

The fetch script collapses the 31 daily values into a single monthly summary
row per municipality and writes:

```
outputs/weather/open_meteo_municipality_july_2022.csv
```

Columns:

| Column                            | Meaning                                                        |
|-----------------------------------|----------------------------------------------------------------|
| `municipality_id`                 | `EID_OBCINA` from eProstor                                     |
| `municipality_name`               | `NAZIV` from eProstor                                          |
| `lat`, `lon`                      | EPSG:4326 centroid                                             |
| `month`                           | `2022-07`                                                      |
| `temperature_2m_mean_avg`         | Mean of daily `temperature_2m_mean` over July 2022 (°C)        |
| `precipitation_sum_total`         | Sum of daily `precipitation_sum` over July 2022 (mm)           |
| `wind_speed_10m_mean_avg`         | Mean of daily mean wind speed (km/h)                           |
| `wind_speed_10m_max`              | Maximum of daily `wind_speed_10m_max` (km/h)                   |
| `wind_gusts_10m_max`              | Maximum of daily `wind_gusts_10m_max` (km/h)                   |
| `wind_direction_10m_dominant`     | Circular mean of daily dominant directions (°)                 |
| `relative_humidity_2m_mean_avg`   | Mean of daily mean relative humidity (%)                       |
| `cloud_cover_mean_avg`            | Mean of daily mean cloud cover (%)                             |
| `source`                          | `Open-Meteo Historical Weather API`                            |

Failed municipalities (after retry) are recorded separately in:

```
outputs/weather/open_meteo_municipality_july_2022_errors.csv
```

Run metadata lives in:

```
outputs/weather/open_meteo_municipality_july_2022_metadata.json
```

---

## Limitations

- **Reanalysis, not station data** — values are modelled at the municipality
  centroid. They should not be reported as official municipal measurements.
- **Centroid bias** — large municipalities with strong altitude gradients
  (e.g. Bohinj, Kobarid) collapse to a single point. The CSV cannot resolve
  intra-municipal variation.
- **Monthly aggregation** — the dashboard only ships the monthly summary;
  intra-month dynamics (e.g. the storm front of mid-July 2022) are smoothed.
- **No causal claim** — coloured municipalities show *associated* weather
  during the wildfire window, not weather *caused* by, or *causing*, the
  event.
- **API limits** — the public Open-Meteo endpoint has rate limits. The
  fetch script paces requests (`INTER_REQUEST_DELAY_S`) and retries on
  HTTP 429 with exponential backoff.

---

## How to run the fetch script

From the project root, with the repo's `.venv` active:

```bash
.venv/bin/python data_pipeline/weather/fetch_open_meteo_municipalities_july_2022.py
```

The script reads only `reference_data/context_layers/eprostor_municipalities.geojson`
and writes only into `outputs/weather/`. It does not touch any Sentinel Hub
files. A full run for 212 municipalities takes roughly one minute on a good
connection.

Output:

- `outputs/weather/open_meteo_municipality_july_2022.csv`
- `outputs/weather/open_meteo_municipality_july_2022_metadata.json`
- `outputs/weather/open_meteo_municipality_july_2022_errors.csv` *(only if
  some municipalities failed)*

---

## How the dashboard uses the CSV

The dashboard (`dashboard_shiny/app.py`) reads the CSV at module import via
`load_weather_df()`. If the file is missing, every weather feature
degrades gracefully:

- **Side-rail card "Vremenski kontekst — julij 2022"**
  - Rendered only when the Kras 2022 event is selected.
  - When the CSV is present: shows monthly averages for temperature,
    precipitation, wind speed, max wind gust, dominant wind direction and
    humidity.
  - When a NUTS3 region is selected, the panel automatically narrows to the
    municipalities whose centroids fall inside that region (`_MUNI_REGION_MAP`
    is precomputed once at module import via a centroid point-in-polygon
    test against the NUTS3 GeoJSON).
  - When no region is selected, the panel shows the all-Slovenia average
    across the 212 municipalities.
  - When the CSV is missing on disk: shows only "Vremenski podatki niso
    naloženi.".
- **Optional map layer "Vreme po občinah"**
  - Toggle in the GeoSlovenija context panel.
  - When on, small semi-transparent markers are added at each municipality
    centroid, coloured by the selected metric (temperature, precipitation,
    wind speed or humidity).
  - The Sentinel-5P NUTS3 choropleth stays the primary reading; the weather
    overlay is intentionally subtle and is drawn *on top of* the choropleth
    so the user can still see the pollutant signal.
  - Toggle is disabled when the CSV is missing.

The dashboard UI remains Slovenian throughout. No other event uses these
weather files.
