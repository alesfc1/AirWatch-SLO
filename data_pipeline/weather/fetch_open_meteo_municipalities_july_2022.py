#!/usr/bin/env python3
"""Fetch Open-Meteo Historical Weather context for Slovenian municipalities.

For every municipality polygon in
``reference_data/context_layers/eprostor_municipalities.geojson`` we compute a
centroid in EPSG:4326 and call the Open-Meteo Historical Weather API for the
month of July 2022. Daily values are then aggregated into a single monthly
summary row per municipality and written to:

    outputs/weather/open_meteo_municipality_july_2022.csv

Any municipalities that fail every retry land in:

    outputs/weather/open_meteo_municipality_july_2022_errors.csv

The script is read-only with respect to the Sentinel Hub pollutant pipeline —
it does not touch any of its inputs or outputs. The output here is intended as
*weather context* for wildfire interpretation only, not as ground-truth
station measurement.

Run:
    python data_pipeline/weather/fetch_open_meteo_municipalities_july_2022.py
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

OUTPUT_DIR = PROJECT_ROOT / "outputs" / "weather"
OUTPUT_CSV = OUTPUT_DIR / "open_meteo_municipality_july_2022.csv"
ERROR_CSV = OUTPUT_DIR / "open_meteo_municipality_july_2022_errors.csv"
METADATA_JSON = OUTPUT_DIR / "open_meteo_municipality_july_2022_metadata.json"

API_URL = "https://archive-api.open-meteo.com/v1/archive"
SOURCE_NAME = "Open-Meteo Historical Weather API"
DATE_FROM = "2022-07-01"
DATE_TO = "2022-07-31"
TIMEZONE = "Europe/Ljubljana"
MONTH_LABEL = "2022-07"

# Open-Meteo daily endpoint supports these variables directly.
DAILY_VARIABLES = [
    "temperature_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
]

# Open-Meteo's daily endpoint does NOT expose mean wind speed, mean relative
# humidity or mean cloud cover. We therefore request the hourly equivalents
# and average them ourselves to obtain the requested daily means:
#   * wind_speed_10m_mean        <- hourly wind_speed_10m, daily mean
#   * relative_humidity_2m_mean  <- hourly relative_humidity_2m, daily mean
#   * cloud_cover_mean           <- hourly cloud_cover, daily mean
HOURLY_VARIABLES = [
    "wind_speed_10m",
    "relative_humidity_2m",
    "cloud_cover",
]

REQUEST_TIMEOUT_S = 30
MAX_RETRIES = 5
RETRY_BACKOFF_S = 2.0
INTER_REQUEST_DELAY_S = 0.1  # gentle pacing


# ---------------------------------------------------------------------------
# Geometry helpers — polygon centroid in EPSG:4326 (no shapely dep required).
# ---------------------------------------------------------------------------


def _ring_signed_area(ring: list[tuple[float, float]]) -> float:
    """Signed area of a closed lon/lat ring via the shoelace formula."""
    n = len(ring)
    s = 0.0
    for i in range(n - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _ring_centroid(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Centroid (cx, cy) and signed area for a closed lon/lat ring."""
    n = len(ring)
    area = _ring_signed_area(ring)
    if area == 0.0:
        xs = [p[0] for p in ring[:-1]] or [p[0] for p in ring]
        ys = [p[1] for p in ring[:-1]] or [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys), 0.0)
    cx = 0.0
    cy = 0.0
    for i in range(n - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    cx /= 6.0 * area
    cy /= 6.0 * area
    return (cx, cy, area)


def _close_ring(coords: list[list[float]]) -> list[tuple[float, float]]:
    if not coords:
        return []
    ring = [(float(p[0]), float(p[1])) for p in coords if len(p) >= 2]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def geometry_centroid_lonlat(geom: dict) -> tuple[float, float] | None:
    """Return (lon, lat) centroid for Polygon / MultiPolygon geometry.

    For MultiPolygon, areas are signed-weighted using each outer ring so the
    centroid lands in the dominant polygon (handles split coastal municipalities).
    """
    if not geom:
        return None
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    rings: list[list[tuple[float, float]]] = []
    if gtype == "Polygon" and coords:
        rings.append(_close_ring(coords[0]))
    elif gtype == "MultiPolygon":
        for poly in coords:
            if poly:
                rings.append(_close_ring(poly[0]))
    if not rings:
        return None
    total_area = 0.0
    weighted_x = 0.0
    weighted_y = 0.0
    for ring in rings:
        if len(ring) < 3:
            continue
        cx, cy, area = _ring_centroid(ring)
        weight = abs(area) or 1.0
        weighted_x += cx * weight
        weighted_y += cy * weight
        total_area += weight
    if total_area == 0.0:
        return None
    return (weighted_x / total_area, weighted_y / total_area)


# ---------------------------------------------------------------------------
# Open-Meteo HTTP client with retries
# ---------------------------------------------------------------------------


def fetch_open_meteo(lat: float, lon: float) -> dict:
    """Call Open-Meteo Historical Weather and return the parsed JSON.

    Raises ``requests.HTTPError`` (after exhausting retries) so callers can
    record the failure without crashing the run.
    """
    params = {
        "latitude": f"{lat:.5f}",
        "longitude": f"{lon:.5f}",
        "start_date": DATE_FROM,
        "end_date": DATE_TO,
        "timezone": TIMEZONE,
        "daily": ",".join(DAILY_VARIABLES),
        "hourly": ",".join(HOURLY_VARIABLES),
    }

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT_S)
            if resp.status_code == 429:
                # Rate limited — back off harder.
                wait = RETRY_BACKOFF_S * (2 ** (attempt - 1)) * 2
                time.sleep(wait)
                last_err = requests.HTTPError(f"429 rate-limited (attempt {attempt})")
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as err:
            last_err = err
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_S * (2 ** (attempt - 1)))
    if last_err:
        raise last_err
    raise RuntimeError("Open-Meteo request failed with no captured exception")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _circular_mean_deg(angles_deg: list[float]) -> float | None:
    """Yamartino-style circular mean for directional data (degrees)."""
    vals = [a for a in angles_deg if a is not None and not (isinstance(a, float) and math.isnan(a))]
    if not vals:
        return None
    sin_sum = sum(math.sin(math.radians(a)) for a in vals)
    cos_sum = sum(math.cos(math.radians(a)) for a in vals)
    if sin_sum == 0.0 and cos_sum == 0.0:
        return None
    mean = math.degrees(math.atan2(sin_sum / len(vals), cos_sum / len(vals)))
    return (mean + 360.0) % 360.0


def _safe_mean(values: list) -> float | None:
    nums = [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _safe_sum(values: list) -> float | None:
    nums = [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not nums:
        return None
    return sum(nums)


def _safe_max(values: list) -> float | None:
    nums = [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not nums:
        return None
    return max(nums)


def _hourly_to_daily_mean(times: list[str], values: list) -> dict[str, float]:
    """Group hourly values by ISO date prefix and return per-day means."""
    bucket: dict[str, list[float]] = {}
    for t, v in zip(times, values):
        if v is None:
            continue
        if isinstance(v, float) and math.isnan(v):
            continue
        day = str(t)[:10]
        bucket.setdefault(day, []).append(float(v))
    return {day: sum(vs) / len(vs) for day, vs in bucket.items() if vs}


def summarize_response(payload: dict) -> dict:
    """Collapse one Open-Meteo response into the monthly-summary row schema."""
    daily = payload.get("daily") or {}
    hourly = payload.get("hourly") or {}

    temp_mean_avg = _safe_mean(daily.get("temperature_2m_mean") or [])
    precip_total = _safe_sum(daily.get("precipitation_sum") or [])
    wind_max = _safe_max(daily.get("wind_speed_10m_max") or [])
    gust_max = _safe_max(daily.get("wind_gusts_10m_max") or [])
    wdir_dom = _circular_mean_deg(daily.get("wind_direction_10m_dominant") or [])

    hourly_times = hourly.get("time") or []
    ws_daily = _hourly_to_daily_mean(hourly_times, hourly.get("wind_speed_10m") or [])
    rh_daily = _hourly_to_daily_mean(hourly_times, hourly.get("relative_humidity_2m") or [])
    cc_daily = _hourly_to_daily_mean(hourly_times, hourly.get("cloud_cover") or [])

    wind_mean_avg = _safe_mean(list(ws_daily.values()))
    rh_mean_avg = _safe_mean(list(rh_daily.values()))
    cc_mean_avg = _safe_mean(list(cc_daily.values()))

    return {
        "temperature_2m_mean_avg": temp_mean_avg,
        "precipitation_sum_total": precip_total,
        "wind_speed_10m_mean_avg": wind_mean_avg,
        "wind_speed_10m_max": wind_max,
        "wind_gusts_10m_max": gust_max,
        "wind_direction_10m_dominant": wdir_dom,
        "relative_humidity_2m_mean_avg": rh_mean_avg,
        "cloud_cover_mean_avg": cc_mean_avg,
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


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
        raise FileNotFoundError(f"Municipality GeoJSON not found: {INPUT_GEOJSON}")
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
    print(f"[open_meteo] loaded {total} municipalities from {INPUT_GEOJSON.name}")
    print(f"[open_meteo] window: {DATE_FROM} → {DATE_TO} ({TIMEZONE})")

    rows: list[dict] = []
    errors: list[dict] = []

    started = time.time()
    for idx, m in enumerate(municipalities, start=1):
        muni_id = m["municipality_id"]
        muni_name = m["municipality_name"]
        lat = float(m["lat"])
        lon = float(m["lon"])

        try:
            payload = fetch_open_meteo(lat, lon)
            summary = summarize_response(payload)
        except Exception as err:  # noqa: BLE001 — record any error and continue
            errors.append({
                "municipality_id": muni_id,
                "municipality_name": muni_name,
                "lat": lat,
                "lon": lon,
                "error": f"{type(err).__name__}: {err}",
            })
            print(
                f"[open_meteo] [{idx}/{total}] FAIL {muni_name!r}: "
                f"{type(err).__name__}: {err}",
                file=sys.stderr,
            )
            time.sleep(INTER_REQUEST_DELAY_S)
            continue

        rows.append({
            "municipality_id": muni_id,
            "municipality_name": muni_name,
            "lat": lat,
            "lon": lon,
            "month": MONTH_LABEL,
            **summary,
            "source": SOURCE_NAME,
        })

        if idx % 20 == 0 or idx == total:
            elapsed = time.time() - started
            print(
                f"[open_meteo] [{idx}/{total}] ok — {muni_name} "
                f"(elapsed {elapsed:.1f}s, errors {len(errors)})"
            )
        time.sleep(INTER_REQUEST_DELAY_S)

    csv_columns = [
        "municipality_id",
        "municipality_name",
        "lat",
        "lon",
        "month",
        "temperature_2m_mean_avg",
        "precipitation_sum_total",
        "wind_speed_10m_mean_avg",
        "wind_speed_10m_max",
        "wind_gusts_10m_max",
        "wind_direction_10m_dominant",
        "relative_humidity_2m_mean_avg",
        "cloud_cover_mean_avg",
        "source",
    ]
    df = pd.DataFrame(rows, columns=csv_columns)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"[open_meteo] wrote {len(df)} rows → {OUTPUT_CSV}")

    if errors:
        err_df = pd.DataFrame(errors)
        err_df.to_csv(ERROR_CSV, index=False, encoding="utf-8")
        print(f"[open_meteo] wrote {len(errors)} error rows → {ERROR_CSV}")
    else:
        # Make sure stale error files from a previous run don't linger.
        if ERROR_CSV.exists():
            ERROR_CSV.unlink()

    metadata = {
        "source": SOURCE_NAME,
        "api_name": "Open-Meteo Historical Weather (archive-api.open-meteo.com)",
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "timezone": TIMEZONE,
        "municipality_count": int(len(df)),
        "municipality_failures": int(len(errors)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "variables": {
            "daily": DAILY_VARIABLES,
            "hourly_for_daily_mean": HOURLY_VARIABLES,
            "derived_from_hourly": [
                "wind_speed_10m_mean (mean of hourly wind_speed_10m)",
                "relative_humidity_2m_mean (mean of hourly relative_humidity_2m)",
                "cloud_cover_mean (mean of hourly cloud_cover)",
            ],
        },
        "input_geojson": str(INPUT_GEOJSON.relative_to(PROJECT_ROOT)),
        "output_csv": str(OUTPUT_CSV.relative_to(PROJECT_ROOT)),
        "errors_csv": (
            str(ERROR_CSV.relative_to(PROJECT_ROOT)) if errors else None
        ),
        "note": (
            "Weather values are retrieved for municipality centroids and "
            "represent reanalysis/modelled weather context, not official "
            "municipal station measurements."
        ),
    }
    with METADATA_JSON.open("w", encoding="utf-8") as fh:
        json.dump(metadata, fh, ensure_ascii=False, indent=2)
    print(f"[open_meteo] wrote metadata → {METADATA_JSON}")


if __name__ == "__main__":
    run()
