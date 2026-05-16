#!/usr/bin/env python3
"""Fetch Open-Meteo Air Quality reanalysis per Slovenian municipality.

For every municipality polygon in
``reference_data/context_layers/eprostor_municipalities.geojson`` we compute a
centroid (EPSG:4326) and call the Open-Meteo Air Quality API on the
``cams_europe`` reanalysis domain for the month of July 2022. Hourly values
for the six common air pollutants are then averaged into a single monthly
summary row per municipality and written to:

    outputs/air_quality/open_meteo_municipality_air_quality_july_2022.csv

Failed municipalities (after retry) are recorded separately in:

    outputs/air_quality/open_meteo_municipality_air_quality_july_2022_errors.csv

This pipeline is independent of the Sentinel Hub Statistical API pipeline; it
adds *municipality-level air quality context* for the Goriški Kras wildfire
(July 2022) when the dashboard's "Občine" scope is active.

Run:
    python data_pipeline/air_quality/fetch_open_meteo_air_quality_municipalities_july_2022.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# Reuse the centroid helper from the sibling weather pipeline so both
# pipelines pin to the exact same lon/lat per municipality.
sys_path_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(sys_path_root))
from weather.fetch_open_meteo_municipalities_july_2022 import (  # noqa: E402
    geometry_centroid_lonlat,
)

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_GEOJSON = (
    PROJECT_ROOT
    / "reference_data"
    / "context_layers"
    / "eprostor_municipalities.geojson"
)

OUTPUT_DIR = PROJECT_ROOT / "outputs" / "air_quality"
OUTPUT_CSV = OUTPUT_DIR / "open_meteo_municipality_air_quality_july_2022.csv"
ERROR_CSV = OUTPUT_DIR / "open_meteo_municipality_air_quality_july_2022_errors.csv"
METADATA_JSON = (
    OUTPUT_DIR / "open_meteo_municipality_air_quality_july_2022_metadata.json"
)

API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
SOURCE_NAME = "Open-Meteo Air Quality API (CAMS Europe reanalysis)"
DATE_FROM = "2022-07-01"
DATE_TO = "2022-07-31"
TIMEZONE = "Europe/Ljubljana"
MONTH_LABEL = "2022-07"

# CAMS Europe reanalysis is the only domain that goes back to July 2022 for
# the full pollutant set we care about.
DOMAIN = "cams_europe"

# Hourly variables fetched per municipality. Open-Meteo returns values in
# µg/m³ for PM10/PM2.5/NO2/SO2/O3 and µg/m³ for CO (note: not mg/m³).
HOURLY_VARIABLES = [
    "pm10",
    "pm2_5",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "carbon_monoxide",
]

REQUEST_TIMEOUT_S = 30
MAX_RETRIES = 5
RETRY_BACKOFF_S = 2.0
INTER_REQUEST_DELAY_S = 0.1


def _safe_mean(values: list) -> float | None:
    nums = [float(v) for v in values
            if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _safe_max(values: list) -> float | None:
    nums = [float(v) for v in values
            if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not nums:
        return None
    return max(nums)


def fetch_open_meteo_aq(lat: float, lon: float) -> dict:
    """Call Open-Meteo Air Quality and return parsed JSON."""
    params = {
        "latitude": f"{lat:.5f}",
        "longitude": f"{lon:.5f}",
        "start_date": DATE_FROM,
        "end_date": DATE_TO,
        "timezone": TIMEZONE,
        "hourly": ",".join(HOURLY_VARIABLES),
        "domains": DOMAIN,
    }

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT_S)
            if resp.status_code == 429:
                time.sleep(RETRY_BACKOFF_S * (2 ** (attempt - 1)) * 2)
                last_err = requests.HTTPError(
                    f"429 rate-limited (attempt {attempt})"
                )
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as err:
            last_err = err
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_S * (2 ** (attempt - 1)))
    if last_err:
        raise last_err
    raise RuntimeError("Open-Meteo Air Quality request failed")


def summarize_response(payload: dict) -> dict:
    """Collapse the hourly response into monthly summary stats."""
    h = payload.get("hourly") or {}
    return {
        "pm10_avg":  _safe_mean(h.get("pm10") or []),
        "pm10_max":  _safe_max(h.get("pm10") or []),
        "pm25_avg":  _safe_mean(h.get("pm2_5") or []),
        "pm25_max":  _safe_max(h.get("pm2_5") or []),
        "no2_avg":   _safe_mean(h.get("nitrogen_dioxide") or []),
        "no2_max":   _safe_max(h.get("nitrogen_dioxide") or []),
        "so2_avg":   _safe_mean(h.get("sulphur_dioxide") or []),
        "so2_max":   _safe_max(h.get("sulphur_dioxide") or []),
        "o3_avg":    _safe_mean(h.get("ozone") or []),
        "o3_max":    _safe_max(h.get("ozone") or []),
        "co_avg":    _safe_mean(h.get("carbon_monoxide") or []),
        "co_max":    _safe_max(h.get("carbon_monoxide") or []),
    }


def _municipality_id(props: dict) -> str:
    return str(
        props.get("EID_OBCINA")
        or props.get("FEATUREID")
        or props.get("SIFRA")
        or ""
    )


def _municipality_name(props: dict) -> str:
    return str(props.get("NAZIV") or "").strip()


def load_municipalities() -> list[dict]:
    if not INPUT_GEOJSON.exists():
        raise FileNotFoundError(
            f"Municipality GeoJSON not found: {INPUT_GEOJSON}"
        )
    with INPUT_GEOJSON.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    out: list[dict] = []
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        centroid = geometry_centroid_lonlat(feat.get("geometry") or {})
        if not centroid:
            continue
        lon, lat = centroid
        out.append({
            "municipality_id": _municipality_id(props),
            "municipality_name": _municipality_name(props),
            "lat": lat,
            "lon": lon,
        })
    return out


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    municipalities = load_municipalities()
    total = len(municipalities)
    print(f"[open_meteo_aq] loaded {total} municipalities from "
          f"{INPUT_GEOJSON.name}")
    print(f"[open_meteo_aq] window: {DATE_FROM} → {DATE_TO} ({TIMEZONE}) "
          f"domain={DOMAIN}")

    rows: list[dict] = []
    errors: list[dict] = []
    started = time.time()

    for idx, m in enumerate(municipalities, start=1):
        muni_id = m["municipality_id"]
        muni_name = m["municipality_name"]
        lat = float(m["lat"]); lon = float(m["lon"])
        try:
            payload = fetch_open_meteo_aq(lat, lon)
            summary = summarize_response(payload)
        except Exception as err:  # noqa: BLE001
            errors.append({
                "municipality_id": muni_id,
                "municipality_name": muni_name,
                "lat": lat, "lon": lon,
                "error": f"{type(err).__name__}: {err}",
            })
            print(f"[open_meteo_aq] [{idx}/{total}] FAIL {muni_name!r}: "
                  f"{type(err).__name__}: {err}", file=sys.stderr)
            time.sleep(INTER_REQUEST_DELAY_S)
            continue

        rows.append({
            "municipality_id": muni_id,
            "municipality_name": muni_name,
            "lat": lat, "lon": lon,
            "month": MONTH_LABEL,
            **summary,
            "source": SOURCE_NAME,
        })

        if idx % 20 == 0 or idx == total:
            elapsed = time.time() - started
            print(f"[open_meteo_aq] [{idx}/{total}] ok — {muni_name} "
                  f"(elapsed {elapsed:.1f}s, errors {len(errors)})")
        time.sleep(INTER_REQUEST_DELAY_S)

    csv_columns = [
        "municipality_id", "municipality_name", "lat", "lon", "month",
        "pm10_avg", "pm10_max",
        "pm25_avg", "pm25_max",
        "no2_avg", "no2_max",
        "so2_avg", "so2_max",
        "o3_avg", "o3_max",
        "co_avg", "co_max",
        "source",
    ]
    df = pd.DataFrame(rows, columns=csv_columns)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"[open_meteo_aq] wrote {len(df)} rows → {OUTPUT_CSV}")

    if errors:
        err_df = pd.DataFrame(errors)
        err_df.to_csv(ERROR_CSV, index=False, encoding="utf-8")
        print(f"[open_meteo_aq] wrote {len(errors)} error rows → {ERROR_CSV}")
    elif ERROR_CSV.exists():
        ERROR_CSV.unlink()

    metadata = {
        "source": SOURCE_NAME,
        "api_name": "Open-Meteo Air Quality (air-quality-api.open-meteo.com)",
        "domain": DOMAIN,
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "timezone": TIMEZONE,
        "municipality_count": int(len(df)),
        "municipality_failures": int(len(errors)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "variables": HOURLY_VARIABLES,
        "input_geojson": str(INPUT_GEOJSON.relative_to(PROJECT_ROOT)),
        "output_csv": str(OUTPUT_CSV.relative_to(PROJECT_ROOT)),
        "errors_csv": (
            str(ERROR_CSV.relative_to(PROJECT_ROOT)) if errors else None
        ),
        "units": {
            "pm10": "µg/m³", "pm2_5": "µg/m³",
            "nitrogen_dioxide": "µg/m³", "sulphur_dioxide": "µg/m³",
            "ozone": "µg/m³", "carbon_monoxide": "µg/m³",
        },
        "note": (
            "Air quality values are retrieved for municipality centroids from "
            "the CAMS Europe reanalysis served via Open-Meteo. They represent "
            "modelled monthly averages, not official station measurements."
        ),
    }
    with METADATA_JSON.open("w", encoding="utf-8") as fh:
        json.dump(metadata, fh, ensure_ascii=False, indent=2)
    print(f"[open_meteo_aq] wrote metadata → {METADATA_JSON}")


if __name__ == "__main__":
    run()
