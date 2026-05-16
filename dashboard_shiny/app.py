#!/usr/bin/env python3
"""AirWatch GeoSlovenija — cinematic "satellite command center" Shiny app.

Event-based Sentinel-5P NO2 intelligence for Slovenian NUTS3 regions.

Inputs (read-only, local files):
  - outputs/timeseries/event_no2_nuts3_daily.csv
  - outputs/timeseries/event_no2_nuts3_daily_metadata.json
  - reference_data/regions/processed/slovenia_nuts3_regions_2024_4326.geojson
  - data_pipeline/events/events.json     (optional fallback)

This module deliberately preserves the existing data pipeline. The redesign is
purely UI: dark mission-control framing, event mission cards, cinematic
timeline, dark choropleth, telemetry strip, region intel panel, dark trend
chart with anomaly toggle, analyst note, data-quality legend, mission log.

Run:
    python dashboard_shiny/app.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_widget


# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# NO2-only legacy CSV (always present, used as the safe fallback).
EVENT_CSV = PROJECT_ROOT / "outputs" / "timeseries" / "event_no2_nuts3_daily.csv"
EVENT_METADATA = PROJECT_ROOT / "outputs" / "timeseries" / "event_no2_nuts3_daily_metadata.json"

# Multi-pollutant CSV produced by data_pipeline/sentinel_hub_stats/
# run_event_multipollutant.py. If present, supersedes the NO2-only CSV.
MULTIPOLLUTANT_CSV = (
    PROJECT_ROOT / "outputs" / "timeseries" / "event_pollutants_nuts3_daily.csv"
)
MULTIPOLLUTANT_METADATA = (
    PROJECT_ROOT
    / "outputs"
    / "timeseries"
    / "event_pollutants_nuts3_daily_metadata.json"
)

REGIONS_GEOJSON = (
    PROJECT_ROOT
    / "reference_data"
    / "regions"
    / "processed"
    / "slovenia_nuts3_regions_2024_4326.geojson"
)
EVENTS_JSON_FALLBACK = PROJECT_ROOT / "data_pipeline" / "events" / "events.json"

# GeoSlovenija / eProstor context layers — local EPSG:4326 GeoJSON files.
# All optional. The dashboard does NOT crash if a file is missing; instead
# the matching layer toggle in the UI is rendered as disabled with the label
# "Sloj ni naložen". See docs/geoslovenija_context_layers.md for details.
CONTEXT_LAYERS_DIR = PROJECT_ROOT / "reference_data" / "context_layers"
CONTEXT_LAYER_FILES: dict[str, Path] = {
    "municipalities": CONTEXT_LAYERS_DIR / "eprostor_municipalities.geojson",
    "transport":      CONTEXT_LAYERS_DIR / "eprostor_transport_infrastructure.geojson",
    "industrial":     CONTEXT_LAYERS_DIR / "geopeskovnik_industrial_business_areas.geojson",
}

# Slovene labels and provenance shown in the floating context panel.
CONTEXT_LAYER_META: dict[str, dict[str, str]] = {
    "municipalities": {
        "label": "Občine",
        "source": "eProstor",
    },
    "transport": {
        "label": "Prometna infrastruktura",
        "source": "eProstor",
    },
    "industrial": {
        "label": "Industrijska in poslovna območja",
        "source": "geo-peskovnik",
    },
}

NO2_UNIT = "µmol/m²"

# Per-pollutant display spec used by the dashboard. Must stay in sync with
# data_pipeline/sentinel_hub_stats/pollutants.py.
POLLUTANT_SPEC: dict[str, dict] = {
    "NO2":  {"short": "NO₂",  "display_unit": "µmol/m²",
             "name_slo": "Dušikov dioksid",     "decimals": 1,
             "relevance_slo": "Promet, izgorevanje, industrija."},
    "CO":   {"short": "CO",   "display_unit": "mmol/m²",
             "name_slo": "Ogljikov monoksid",   "decimals": 2,
             "relevance_slo": "Močan kazalec nepopolnega izgorevanja — značilen za požare."},
    "HCHO": {"short": "HCHO", "display_unit": "µmol/m²",
             "name_slo": "Formaldehid",         "decimals": 1,
             "relevance_slo": "Indikator biomasnih požarov in hlapnih organskih spojin."},
    "SO2":  {"short": "SO₂",  "display_unit": "µmol/m²",
             "name_slo": "Žveplov dioksid",     "decimals": 1,
             "relevance_slo": "Tipičen za kemijsko in metalurško industrijo."},
    "AAI":  {"short": "AAI",  "display_unit": "indeks",
             "name_slo": "Aerosolni indeks (UV)", "decimals": 2,
             "relevance_slo": "Zaznavanje UV-absorbirajočih aerosolov: dim, prah, pepel."},
}

# Per-event default pollutant list. First entry is the preferred default.
# Must stay in sync with pollutants.EVENT_POLLUTANTS.
EVENT_POLLUTANTS_DEFAULT: dict[str, list[str]] = {
    "spar_fire_2025":     ["CO",  "HCHO", "AAI", "NO2"],
    "kras_fire_2022":     ["AAI", "CO",   "HCHO", "NO2"],
    "cinkarna_celje_2019": ["SO2", "NO2"],
}

# Sequential intuitive scale for absolute values — green/teal (low) → amber → red (high).
NO2_COLORSCALE = [
    [0.00, "#0fb98c"],   # clean — green/teal
    [0.30, "#5ec48f"],   # low–moderate — green
    [0.55, "#f0b441"],   # moderate — amber
    [0.80, "#ee7a3a"],   # high — orange
    [1.00, "#dc4a4a"],   # critical — red
]

# Diverging cyan ↔ red scale for anomaly mode (cleaner than usual ↔ elevated).
ANOMALY_COLORSCALE = [
    [0.00, "#3ddcc7"],   # much cleaner than usual (cyan)
    [0.35, "#2e8aa6"],   # mildly cleaner
    [0.50, "#e3e8f2"],   # neutral (matches light UI)
    [0.65, "#ee7a3a"],   # mildly elevated
    [1.00, "#dc4a4a"],   # much elevated than usual (red)
]


# ---------------------------------------------------------------------------
# Data loading (unchanged semantics — gracefully degrade if files missing)
# ---------------------------------------------------------------------------


def load_event_csv(path: Path = EVENT_CSV) -> pd.DataFrame:
    """Return the legacy NO2-only events CSV. Empty if missing."""
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["date_from"] = pd.to_datetime(df["date_from"], utc=True, errors="coerce")
    df["date"] = df["date_from"].dt.strftime("%Y-%m-%d")
    if "pollutant" not in df.columns:
        df["pollutant"] = "NO2"
    if "display_unit" not in df.columns:
        df["display_unit"] = NO2_UNIT
    return df


def load_multipollutant_csv(path: Path = MULTIPOLLUTANT_CSV) -> pd.DataFrame:
    """Return the long-format multi-pollutant CSV. Empty if missing.

    Schema includes a `pollutant` column and `display_unit` column, plus the
    same per-region / per-day columns as the legacy file. Returns an empty
    DataFrame if the file isn't present so the dashboard can gracefully fall
    back to the NO2-only CSV.
    """
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["date_from"] = pd.to_datetime(df["date_from"], utc=True, errors="coerce")
    df["date"] = df["date_from"].dt.strftime("%Y-%m-%d")
    if "pollutant" not in df.columns:
        df["pollutant"] = "NO2"
    if "display_unit" not in df.columns:
        df["display_unit"] = df["pollutant"].map(
            {p: spec["display_unit"] for p, spec in POLLUTANT_SPEC.items()}
        ).fillna(NO2_UNIT)
    return df


def load_combined_pollutant_frame() -> pd.DataFrame:
    """Return a single long-format DataFrame covering all available pollutants.

    Prefers the multi-pollutant CSV. If absent, falls back to the legacy
    NO2-only CSV so the dashboard still works.
    """
    multi = load_multipollutant_csv()
    if not multi.empty:
        return multi
    return load_event_csv()


def load_metadata(path: Path = EVENT_METADATA) -> dict:
    """Return the metadata dict. Empty dict if missing."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_events_fallback(path: Path = EVENTS_JSON_FALLBACK) -> list[dict]:
    """Return the raw events list from data_pipeline/events/events.json."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_regions_geojson(path: Path = REGIONS_GEOJSON) -> dict:
    """Return raw GeoJSON dict for the choropleth map."""
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for feature in data.get("features", []):
        properties = feature.get("properties") or {}
        code = properties.get("region_code") or properties.get("NUTS_ID")
        feature["id"] = code
    return data


def load_context_layer(path: Path) -> dict:
    """Return raw GeoJSON dict for a context layer.

    Gracefully returns an empty FeatureCollection if the file is missing or
    cannot be parsed. The dashboard checks `len(features)` to decide whether
    the matching toggle should be enabled or disabled.
    """
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"type": "FeatureCollection", "features": []}
    if not isinstance(data, dict) or "features" not in data:
        return {"type": "FeatureCollection", "features": []}
    return data


def load_context_layers() -> dict[str, dict]:
    """Eager-load all expected context-layer GeoJSON files (or empty stubs)."""
    return {key: load_context_layer(path) for key, path in CONTEXT_LAYER_FILES.items()}


def _flatten_polygon_rings(geom: dict) -> list[list[tuple[float, float]]]:
    """Return a list of (lon, lat) ring sequences for a Polygon/MultiPolygon."""
    rings: list[list[tuple[float, float]]] = []
    gtype = (geom or {}).get("type")
    coords = (geom or {}).get("coordinates") or []
    if gtype == "Polygon":
        for ring in coords:
            rings.append([(pt[0], pt[1]) for pt in ring if len(pt) >= 2])
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                rings.append([(pt[0], pt[1]) for pt in ring if len(pt) >= 2])
    return rings


def _flatten_line_paths(geom: dict) -> list[list[tuple[float, float]]]:
    """Return a list of (lon, lat) sequences for LineString / MultiLineString."""
    paths: list[list[tuple[float, float]]] = []
    gtype = (geom or {}).get("type")
    coords = (geom or {}).get("coordinates") or []
    if gtype == "LineString":
        paths.append([(pt[0], pt[1]) for pt in coords if len(pt) >= 2])
    elif gtype == "MultiLineString":
        for line in coords:
            paths.append([(pt[0], pt[1]) for pt in line if len(pt) >= 2])
    return paths


def _geom_centroid(geom: dict) -> tuple[float, float] | None:
    """Cheap centroid (mean of outer-ring vertices) for Point/Polygon/MultiPolygon."""
    gtype = (geom or {}).get("type")
    coords = (geom or {}).get("coordinates") or []
    if gtype == "Point" and len(coords) >= 2:
        return (float(coords[1]), float(coords[0]))  # (lat, lon)
    rings = _flatten_polygon_rings(geom)
    xs: list[float] = []
    ys: list[float] = []
    for ring in rings:
        for x, y in ring:
            xs.append(x); ys.append(y)
    if not xs or not ys:
        return None
    return (sum(ys) / len(ys), sum(xs) / len(xs))


# ---------------------------------------------------------------------------
# Plotly trace builders for GeoSlovenija / eProstor context layers
#
# These draw on top of the NUTS3 choropleth as subtle context (thin outlines /
# thin lines / semi-transparent fills). They never replace the choropleth and
# never add fake pollution data — they are purely spatial reference.
# ---------------------------------------------------------------------------


def _add_polygon_outline_layer(
    fig, geojson: dict, *, line_color: str, line_width: float, name: str,
) -> None:
    """Draw polygon/multipolygon outlines as a single Scattermapbox trace.

    Used for municipalities (eProstor) — thin outlines only.
    """
    lats: list[float | None] = []
    lons: list[float | None] = []
    for feat in (geojson or {}).get("features", []):
        for ring in _flatten_polygon_rings(feat.get("geometry") or {}):
            for x, y in ring:
                lons.append(x); lats.append(y)
            # None separator splits sub-paths into discrete polylines.
            lons.append(None); lats.append(None)
    if not lats:
        return
    fig.add_trace(go.Scattermapbox(
        lat=lats, lon=lons,
        mode="lines",
        line=dict(width=line_width, color=line_color),
        name=name,
        hoverinfo="skip",
        showlegend=False,
    ))


def _add_line_layer(
    fig, geojson: dict, *, line_color: str, line_width: float, name: str,
) -> None:
    """Draw LineString/MultiLineString features as a single Scattermapbox trace.

    Used for transport infrastructure (eProstor) — thin lines for major
    roads / railways.
    """
    lats: list[float | None] = []
    lons: list[float | None] = []
    for feat in (geojson or {}).get("features", []):
        for path in _flatten_line_paths(feat.get("geometry") or {}):
            for x, y in path:
                lons.append(x); lats.append(y)
            lons.append(None); lats.append(None)
    if not lats:
        return
    fig.add_trace(go.Scattermapbox(
        lat=lats, lon=lons,
        mode="lines",
        line=dict(width=line_width, color=line_color),
        name=name,
        hoverinfo="skip",
        showlegend=False,
    ))


def _add_industrial_layer(
    fig, geojson: dict, *, fill_color: str, line_color: str,
    point_color: str, name: str,
) -> None:
    """Draw industrial / business areas (geo-peskovnik).

    Polygons render as semi-transparent fills (outline only via Scattermapbox)
    plus a centroid point so the area is also recognisable at low zoom.
    Point features render as a single colored dot.
    """
    poly_lats: list[float | None] = []
    poly_lons: list[float | None] = []
    point_lats: list[float] = []
    point_lons: list[float] = []
    point_texts: list[str] = []
    for feat in (geojson or {}).get("features", []):
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        title = (
            props.get("ime")
            or props.get("name")
            or props.get("naziv")
            or "Industrijska / poslovna cona"
        )
        gtype = geom.get("type")
        if gtype in ("Polygon", "MultiPolygon"):
            for ring in _flatten_polygon_rings(geom):
                for x, y in ring:
                    poly_lons.append(x); poly_lats.append(y)
                poly_lons.append(None); poly_lats.append(None)
            c = _geom_centroid(geom)
            if c:
                point_lats.append(c[0]); point_lons.append(c[1])
                point_texts.append(str(title))
        elif gtype == "Point":
            c = _geom_centroid(geom)
            if c:
                point_lats.append(c[0]); point_lons.append(c[1])
                point_texts.append(str(title))

    if poly_lats:
        fig.add_trace(go.Scattermapbox(
            lat=poly_lats, lon=poly_lons,
            mode="lines",
            line=dict(width=1.2, color=line_color),
            fill="toself",
            fillcolor=fill_color,
            name=name,
            hoverinfo="skip",
            showlegend=False,
        ))

    if point_lats:
        fig.add_trace(go.Scattermapbox(
            lat=point_lats, lon=point_lons,
            mode="markers",
            marker=dict(size=8, color=point_color),
            text=point_texts,
            name=name,
            hovertemplate="<b>%{text}</b><br>Vir: geo-peskovnik<extra></extra>",
            showlegend=False,
        ))


def build_event_choices(metadata: dict, df: pd.DataFrame) -> dict[str, str]:
    """Return {event_id: plain-text label} — back-compat helper for tests.

    Prefers metadata; falls back to the CSV's distinct events when metadata is
    missing. The UI itself does not use this function (it builds mission-card
    HTML labels via :func:`_build_event_choices`), but tests rely on it.
    """
    choices: dict[str, str] = {}
    events = metadata.get("events") if isinstance(metadata, dict) else None
    if events:
        for event in events:
            label_parts = [event.get("event_name") or event["event_id"]]
            if event.get("month_label"):
                label_parts.append(event["month_label"])
            choices[event["event_id"]] = " — ".join(label_parts)
        return choices
    if df is None or df.empty:
        return choices
    for event_id, group in df.groupby("event_id"):
        name = group["event_name"].iloc[0]
        choices[str(event_id)] = str(name)
    return choices


def compute_region_centroids(geojson: dict) -> dict[str, tuple[float, float]]:
    """Approximate centroid (mean of outer-ring vertices) for each region.

    Lightweight; precomputed once at import so map redraws stay cheap.
    """
    centroids: dict[str, tuple[float, float]] = {}
    for feature in geojson.get("features", []):
        code = (feature.get("properties") or {}).get("region_code")
        if not code:
            continue
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        gtype = geom.get("type")
        xs: list[float] = []
        ys: list[float] = []
        if gtype == "Polygon":
            for ring in coords:
                for x, y in ring:
                    xs.append(x); ys.append(y)
        elif gtype == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    for x, y in ring:
                        xs.append(x); ys.append(y)
        if xs and ys:
            centroids[code] = (sum(ys) / len(ys), sum(xs) / len(xs))
    return centroids


# ---------------------------------------------------------------------------
# Eager load + per-event cache at module import.
#
# The dashboard does not call the Sentinel Hub API directly — it reads the
# already-cached pipeline output. But the React renderers (event_df,
# month_means, anomaly column, day slice) were recomputing on every event
# change / slider tick. We collapse all of that work into a single dict built
# once at import:
#
#     _EVENT_CACHE[event_id] = {
#         "event":         <metadata block>,
#         "df":            full per-event DataFrame (with value_anomaly column),
#         "month_means":   pd.Series indexed by region_code,
#         "region_choices":{region_code: "code — name", "": "All regions ..."}
#         "max_day":       int,
#         "days":          {day_index: per-day DataFrame slice (12 rows)},
#         "event_window":  {"start_pct", "width_pct", "label"} | None,
#     }
#
# Every reactive lookup is then a dict access in O(1).
# ---------------------------------------------------------------------------

_INITIAL_DF = load_event_csv()
_INITIAL_METADATA = load_metadata()
_EVENTS_FALLBACK = load_events_fallback()
_REGIONS_GEOJSON = load_regions_geojson()
_REGION_CENTROIDS = compute_region_centroids(_REGIONS_GEOJSON)

# region_code -> region_name, used for in-map text labels at centroids.
_REGION_NAMES: dict[str, str] = {
    str((feat.get("properties") or {}).get("region_code") or ""):
    str((feat.get("properties") or {}).get("region_name") or "")
    for feat in (_REGIONS_GEOJSON.get("features") or [])
    if (feat.get("properties") or {}).get("region_code")
}

# Capital / main town of each NUTS3 region. Coordinates are approximate
# (city centre, EPSG:4326). Used purely for in-map orientation labels —
# they are not measurement points.
_REGION_CAPITALS: dict[str, dict] = {
    "SI031": {"name": "Murska Sobota", "lat": 46.660, "lon": 16.166},
    "SI032": {"name": "Maribor",        "lat": 46.554, "lon": 15.645},
    "SI033": {"name": "Slovenj Gradec", "lat": 46.510, "lon": 15.081},
    "SI034": {"name": "Celje",          "lat": 46.231, "lon": 15.262},
    "SI035": {"name": "Trbovlje",       "lat": 46.155, "lon": 15.052},
    "SI036": {"name": "Krško",          "lat": 45.957, "lon": 15.491},
    "SI037": {"name": "Novo mesto",     "lat": 45.803, "lon": 15.169},
    "SI038": {"name": "Postojna",       "lat": 45.776, "lon": 14.214},
    "SI041": {"name": "Ljubljana",      "lat": 46.057, "lon": 14.506},
    "SI042": {"name": "Kranj",          "lat": 46.239, "lon": 14.356},
    "SI043": {"name": "Nova Gorica",    "lat": 45.953, "lon": 13.648},
    "SI044": {"name": "Koper",          "lat": 45.546, "lon": 13.730},
}

# Eager-load optional GeoSlovenija / eProstor context layers. Missing files
# return empty FeatureCollections so the UI stays robust.
_CONTEXT_LAYERS: dict[str, dict] = load_context_layers()
_CONTEXT_LAYER_AVAILABLE: dict[str, bool] = {
    key: bool((_CONTEXT_LAYERS.get(key) or {}).get("features"))
    for key in CONTEXT_LAYER_FILES
}


def _resolved_layer_source(layer_key: str) -> str:
    """Source label to show in the UI pill.

    Prefer FeatureCollection.properties.source from the loaded GeoJSON (so an
    OSM-mirrored fallback can transparently say "OpenStreetMap (zrcalo
    eProstor GJI)"). Fall back to the configured default.
    """
    fc = _CONTEXT_LAYERS.get(layer_key) or {}
    props = fc.get("properties") or {}
    src = props.get("source")
    if isinstance(src, str) and src.strip():
        return src.strip()
    return CONTEXT_LAYER_META.get(layer_key, {}).get("source", "")


def _resolve_events_list() -> list[dict]:
    """Return the canonical list of event metadata dicts (metadata > fallback)."""
    events = (_INITIAL_METADATA or {}).get("events") or []
    if events:
        return list(events)
    return list(_EVENTS_FALLBACK)


_EVENTS_LIST = _resolve_events_list()


def _compute_event_window(event: dict, max_day: int) -> dict | None:
    """Return {start_pct, label} for the timeline event-start marker.

    Marks the slider precisely at ``event_start``. For multi-day events the
    label says "Začetek dogodka" plus the date; for single-day events it
    says "Dan dogodka". No width is returned — the UI draws a thin vertical
    line at ``start_pct``, not a band.
    """
    if not event or max_day <= 1:
        return None
    es_raw = event.get("event_start")
    ee_raw = event.get("event_end")
    if not es_raw:
        return None
    try:
        es_day = pd.to_datetime(es_raw).day
    except (ValueError, TypeError):
        return None
    denom = max(max_day - 1, 1)
    start_pct = max(0.0, min(100.0, (es_day - 1) / denom * 100.0))
    single_day = bool(ee_raw) and es_raw == ee_raw
    short_label = "Dan dogodka" if single_day else "Začetek dogodka"
    return {
        "start_pct": start_pct,
        "label": short_label,
        "event_start": es_raw,
    }


def _empty_trend_figure() -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=300,
        margin=dict(l=40, r=20, t=30, b=40),
        annotations=[dict(
            text="Ni razpoložljivih podatkov.",
            x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
            font=dict(family="DM Sans, system-ui, sans-serif",
                      color="#6a7894", size=14),
        )],
        meta={"base_shape_count": 0},
    )
    return fig


def _build_trend_figure_base(
    df: pd.DataFrame,
    region_code: str,
    mode: str,
    event_meta: dict,
    pollutant: str,
) -> go.Figure:
    """Pure builder for the trend Plotly figure WITHOUT the day-marker.

    Same inputs ⇒ same output, so the result is safe to cache at module
    import and reuse across sessions. The day-marker is added client-side
    via the ``trend_day_marker`` custom message; that keeps slider drags
    from re-shipping the whole figure over the websocket.
    """
    if df.empty:
        return _empty_trend_figure()

    spec = POLLUTANT_SPEC.get(pollutant, POLLUTANT_SPEC["NO2"])
    unit = spec.get("display_unit", NO2_UNIT)
    p_short = spec.get("short", pollutant)
    decimals = spec.get("decimals", 1)

    if region_code:
        sub = df[df["region_code"] == region_code].sort_values("day_index").copy()
        if sub.empty:
            # Region not present in this event/pollutant slice — show composite.
            region_code = ""
    if not region_code:
        sub = (
            df.groupby(["day_index", "date"], as_index=False)
            .agg(
                value_mean=("value_mean", "mean"),
                value_min=("value_min", "min"),
                value_max=("value_max", "max"),
            )
            .sort_values("day_index")
        )
        title = "Povprečje vseh slovenskih regij"
    else:
        title = f"Trend za {sub['region_name'].iloc[0]} ({region_code})"

    if mode == "anomaly":
        baseline = sub["value_mean"].mean()
        sub["plot_value"] = sub["value_mean"] - baseline
        if "value_min" in sub.columns:
            sub["band_low"] = sub["value_min"] - baseline
            sub["band_high"] = sub["value_max"] - baseline
        y_title = f"Odstopanje {p_short} ({unit})"
    else:
        sub["plot_value"] = sub["value_mean"]
        sub["band_low"] = sub.get("value_min", sub["value_mean"])
        sub["band_high"] = sub.get("value_max", sub["value_mean"])
        y_title = f"{p_short} ({unit})"

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=sub["date"], y=sub["band_high"],
        mode="lines", line=dict(width=0),
        name="max", showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=sub["date"], y=sub["band_low"],
        mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor="rgba(14,155,209,0.12)",
        name="min–max", hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=sub["date"], y=sub["plot_value"],
        mode="lines+markers",
        line=dict(color="#0e9bd1", width=2.4,
                  shape="spline", smoothing=0.5),
        marker=dict(size=5, color="#0e9bd1",
                    line=dict(color="#ffffff", width=1)),
        name="povprečje",
        hovertemplate=(
            "<b>%{x}</b><br>"
            f"%{{y:.{decimals}f}} {unit}<extra></extra>"
        ),
    ))

    if event_meta and event_meta.get("event_start") and event_meta.get("event_end"):
        es = event_meta["event_start"]; ee = event_meta["event_end"]
        available = set(sub["date"].astype(str).tolist())
        if es in available and ee in available:
            if es == ee:
                fig.add_vline(
                    x=es,
                    line=dict(color="#d65336", width=2),
                )
                fig.add_annotation(
                    x=es, y=1, yref="paper", showarrow=False,
                    text="DAN DOGODKA", yanchor="bottom",
                    font=dict(family="JetBrains Mono, monospace",
                              color="#d65336", size=10),
                )
            else:
                fig.add_vrect(
                    x0=es, x1=ee,
                    fillcolor="rgba(217,102,55,0.14)",
                    line=dict(width=0),
                )
                fig.add_annotation(
                    x=es, y=1, yref="paper", showarrow=False,
                    text="OBDOBJE DOGODKA", yanchor="bottom",
                    xanchor="left",
                    font=dict(family="JetBrains Mono, monospace",
                              color="#d65336", size=10),
                )

    # Count baseline shapes so the JS day-marker handler knows where to
    # slice when replacing the per-day vertical line.
    base_shape_count = len(fig.layout.shapes or [])

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=dict(
            text=title.upper(),
            font=dict(family="JetBrains Mono, monospace",
                      color="#46546f", size=11),
            x=0.01, y=0.97,
        ),
        xaxis=dict(
            title=None,
            gridcolor="rgba(30,64,120,0.08)",
            zerolinecolor="rgba(30,64,120,0.14)",
            linecolor="rgba(30,64,120,0.20)",
            tickfont=dict(family="DM Sans, system-ui, sans-serif",
                          color="#46546f", size=11),
            showline=True,
            tickangle=-45,
        ),
        yaxis=dict(
            title=dict(text=y_title,
                       font=dict(family="DM Sans, system-ui, sans-serif",
                                 color="#46546f", size=11)),
            gridcolor="rgba(30,64,120,0.08)",
            zerolinecolor="rgba(30,64,120,0.14)",
            linecolor="rgba(14,155,209,0.30)",
            tickfont=dict(family="JetBrains Mono, monospace",
                          color="#46546f", size=10),
            showline=True,
        ),
        font=dict(family="DM Sans, system-ui, sans-serif", color="#1f2a3e"),
        height=300,
        margin=dict(l=60, r=20, t=46, b=60),
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.97)",
            bordercolor="rgba(14,155,209,0.45)",
            font=dict(family="DM Sans, system-ui, sans-serif",
                      color="#0b1424", size=12),
        ),
        showlegend=False,
        meta={"base_shape_count": base_shape_count},
    )
    return fig


def _build_event_pollutant_block(
    sub: pd.DataFrame,
    event_meta: dict | None = None,
    pollutant: str = "NO2",
) -> dict:
    """Build a single (event, pollutant) cache entry from a pre-filtered df.

    Also precomputes a trend figure for every (region_code, mode) combo so
    that the dashboard can serve chart clicks straight from the cache.
    """
    if sub.empty:
        return {
            "df": sub,
            "month_means": pd.Series(dtype=float),
            "region_choices": {"": "All regions (Slovenia composite)"},
            "max_day": 31,
            "days": {},
            "trend_figures": {},
            "trend_marker_values": {},
        }
    sub = sub.copy()
    month_means = sub.groupby("region_code")["value_mean"].mean()
    sub["value_anomaly"] = sub["value_mean"] - sub["region_code"].map(month_means)

    region_choices: dict[str, str] = {"": "Vse regije (povprečje Slovenije)"}
    regs = (
        sub[["region_code", "region_name"]]
        .drop_duplicates()
        .sort_values("region_name")
    )
    for _, row in regs.iterrows():
        region_choices[str(row["region_code"])] = (
            f"{row['region_code']} — {row['region_name']}"
        )

    max_day = int(sub["day_index"].max())
    days: dict[int, pd.DataFrame] = {}
    for day, group in sub.groupby("day_index"):
        days[int(day)] = group.reset_index(drop=True)

    # ---- precompute trend figures (no day-marker) -------------------------
    region_codes = [""] + [str(c) for c in regs["region_code"].tolist()]
    trend_figures: dict[tuple[str, str], go.Figure] = {}
    for rc in region_codes:
        for m in ("absolute", "anomaly"):
            trend_figures[(rc, m)] = _build_trend_figure_base(
                sub, rc, m, event_meta or {}, pollutant,
            )

    # ---- precompute per-day marker x/date for instant marker push ---------
    # day_index -> "YYYY-MM-DD" string used as Plotly x coord
    trend_marker_values: dict[int, str] = {}
    for day, group in sub.groupby("day_index"):
        date_val = group["date"].iloc[0]
        trend_marker_values[int(day)] = str(date_val)

    return {
        "df": sub,
        "month_means": month_means,
        "region_choices": region_choices,
        "max_day": max_day,
        "days": days,
        "trend_figures": trend_figures,
        "trend_marker_values": trend_marker_values,
    }


def build_event_cache(df: pd.DataFrame, events: list[dict]) -> dict[str, dict]:
    """Precompute everything the UI needs per event × pollutant.

    Returns {event_id: cache_block}. Each cache_block has:
      - event:          metadata dict
      - max_day:        day count (same across pollutants)
      - event_window:   {start_pct, width_pct, label} | None
      - pollutants:     [list of pollutant codes available for this event]
      - default_pollutant: preferred default for this event
      - by_pollutant:   {pollutant: {df, month_means, region_choices, days}}
    """
    cache: dict[str, dict] = {}

    if df.empty:
        return cache

    available_per_event = df.groupby("event_id")["pollutant"].apply(
        lambda s: sorted(set(s))
    ).to_dict()

    for event in events:
        eid = event.get("event_id")
        if not eid:
            continue

        # All pollutants present in CSV for this event
        present_pollutants = available_per_event.get(eid, [])

        # Build per-pollutant blocks
        by_pollutant: dict[str, dict] = {}
        for pollutant in present_pollutants:
            sub = df[(df["event_id"] == eid) & (df["pollutant"] == pollutant)]
            by_pollutant[pollutant] = _build_event_pollutant_block(
                sub, event_meta=event, pollutant=pollutant,
            )

        # Order pollutants: configured default-first, then any extras in stable order
        configured_order = EVENT_POLLUTANTS_DEFAULT.get(eid, [])
        ordered = [p for p in configured_order if p in by_pollutant]
        ordered += [p for p in present_pollutants if p not in ordered]

        # max_day is taken from the first pollutant's block (should match across).
        max_day = 31
        if ordered:
            max_day = by_pollutant[ordered[0]]["max_day"]

        cache[eid] = {
            "event": event,
            "max_day": max_day,
            "event_window": _compute_event_window(event, max_day),
            "pollutants": ordered,
            "default_pollutant": ordered[0] if ordered else "NO2",
            "by_pollutant": by_pollutant,
        }
    return cache


# Eager-load: prefer multi-pollutant CSV; otherwise fall back to NO2-only.
_COMBINED_DF = load_combined_pollutant_frame()
_EVENT_CACHE = build_event_cache(_COMBINED_DF, _EVENTS_LIST)


# ---------------------------------------------------------------------------
# Municipality-level dataset (data/dataset_municipalities.xlsx)
#
# Annual averages 2020–2025 for 212 Slovenian municipalities. Used only when
# the "Občine" scope is selected — completely independent of the event-based
# Sentinel-5P pipeline above.
# ---------------------------------------------------------------------------

_MUNI_XLSX = PROJECT_ROOT / "data" / "dataset_municipalities.xlsx"

MUNI_METRICS: dict[str, dict] = {
    "PM10": {
        "col": "PM10 (µg/m³)",
        "label": "PM10",  "unit": "µg/m³",
        "name_slo": "Drobni delci PM10",
    },
    "PM25": {
        "col": "PM2.5 (µg/m³)",
        "label": "PM2.5", "unit": "µg/m³",
        "name_slo": "Drobni delci PM2.5",
    },
    "O3": {
        "col": "Ozon (µg/m³)",
        "label": "O₃",    "unit": "µg/m³",
        "name_slo": "Ozon",
    },
    "SO2": {
        "col": "Žveplov dioksid (µg/m³)",
        "label": "SO₂",   "unit": "µg/m³",
        "name_slo": "Žveplov dioksid",
    },
    "NO2": {
        "col": "Dušikov dioksid (µg/m³)",
        "label": "NO₂",   "unit": "µg/m³",
        "name_slo": "Dušikov dioksid",
    },
    "CO": {
        "col": "Ogljikov monoksid (µg/m³)",
        "label": "CO",    "unit": "µg/m³",
        "name_slo": "Ogljikov monoksid",
    },
    "NPR": {
        "col": "Novi primeri pljučnega raka",
        "label": "Pljučni rak",
        "unit": "primerov/100 000",
        "name_slo": "Novi primeri pljučnega raka",
    },
    "UMR": {
        "col": "Umrljivost zaradi pljučnega raka (0–74 let)",
        "label": "Umrljivost",
        "unit": "primerov/100 000",
        "name_slo": "Umrljivost zaradi pljučnega raka (0–74 let)",
    },
}


def load_muni_df(path: Path = _MUNI_XLSX) -> pd.DataFrame:
    """Load the municipality xlsx into a long-form DataFrame.

    Coerces the mixed-type cancer columns to numeric (`n` placeholder → NaN).
    Renames columns to short ASCII keys matching ``MUNI_METRICS``.
    Returns an empty frame if the file is missing.
    """
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_excel(path, sheet_name="koncni_nabor_podatkov")
    for key, meta in MUNI_METRICS.items():
        col = meta["col"]
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    rename = {meta["col"]: key for key, meta in MUNI_METRICS.items()}
    df = df.rename(columns=rename)
    df = df.rename(columns={
        "Lattitude": "lat",
        "Longitude": "lon",
        "Občina":   "muni",
        "Leto":     "year",
    })
    df["year"] = df["year"].astype(int)
    return df


_MUNI_DF: pd.DataFrame = load_muni_df()
_MUNI_YEARS: list[int] = (
    sorted(_MUNI_DF["year"].unique().tolist())
    if not _MUNI_DF.empty else [2020, 2025]
)
_MUNI_DEFAULT_YEAR: int = _MUNI_YEARS[-1]


def _muni_metric_range(metric: str) -> tuple[float, float]:
    """Stable colour-scale range for a municipality metric across all years."""
    if _MUNI_DF.empty or metric not in _MUNI_DF.columns:
        return (0.0, 1.0)
    vals = pd.to_numeric(_MUNI_DF[metric], errors="coerce").dropna()
    if vals.empty:
        return (0.0, 1.0)
    lo = float(vals.quantile(0.02))
    hi = float(vals.quantile(0.98))
    return (lo, max(hi, lo + 1e-6))


def cache_pollutant_block(event_id: str, pollutant: str) -> dict:
    """Look up the per-(event, pollutant) sub-cache, with safe fallback."""
    entry = _EVENT_CACHE.get(event_id) or {}
    by_p = entry.get("by_pollutant") or {}
    if pollutant in by_p:
        return by_p[pollutant]
    # fall back to default pollutant, then to empty
    default = entry.get("default_pollutant")
    if default and default in by_p:
        return by_p[default]
    return _build_event_pollutant_block(pd.DataFrame())


# ---------------------------------------------------------------------------
# UI helpers — build the mission cards and other HTML primitives
# ---------------------------------------------------------------------------


# Slovene month names — used for date formatting throughout the UI.
SLO_MONTHS = {
    1: "januar", 2: "februar", 3: "marec", 4: "april",
    5: "maj", 6: "junij", 7: "julij", 8: "avgust",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}

# Slovene event type labels and short descriptions, written for a non-technical
# reader. Falls back to the event_type field if an event_id is unknown.
EVENT_COPY_SLO: dict[str, dict[str, str]] = {
    "spar_fire_2025": {
        "type": "Industrijski požar",
        "title": "Požar v skladišču SPAR",
        "desc": "Velik požar v logističnem centru SPAR v BTC območju Ljubljane.",
    },
    "kras_fire_2022": {
        "type": "Gozdni požar",
        "title": "Požar na Goriškem Krasu",
        "desc": "Eden največjih gozdnih požarov v zgodovini Slovenije.",
    },
    "cinkarna_celje_2019": {
        "type": "Industrijska študija",
        "title": "Cinkarna Celje",
        "desc": "Dolgoletni vpliv industrije na kakovost zraka v Celju.",
    },
}

EVENT_TYPE_FALLBACK_SLO: dict[str, str] = {
    "industrial_fire": "Industrijski požar",
    "wildfire": "Gozdni požar",
    "industrial_case": "Industrijska študija",
}


# Per-event Slovene narrative for the "Prostorska interpretacija" panel.
# Each entry has:
#   - `headline`: one short sentence framing what the spatial context is.
#   - `paragraphs`: list of plain-text paragraphs about the surrounding space.
#   - `relevant_layers`: ordered subset of CONTEXT_LAYER_FILES keys that are
#     most informative for this event. The panel lists them with their
#     availability status pulled from the already-loaded context layers.
#
# These texts describe the spatial setting only — they do not introduce any
# new measurement data and do not claim causation.
SPATIAL_INTERPRETATION_SLO: dict[str, dict] = {
    "spar_fire_2025": {
        "headline": (
            "Logistični, poslovni in prometni kontekst v BTC območju "
            "Ljubljane."
        ),
        "paragraphs": [
            "Lokacija dogodka je v skladiščno-logističnem delu BTC ob "
            "Letališki cesti, kjer se prepletajo trgovinska, poslovna in "
            "skladiščna raba prostora.",
            "V okolici se nahajata gosto prometno omrežje (mestne vpadnice "
            "in obvoznica) ter večja industrijska in poslovna območja, kar "
            "vpliva na ozadje signala onesnaževal v urbanem zraku.",
        ],
        "relevant_layers": ["industrial", "transport", "municipalities"],
    },
    "kras_fire_2022": {
        "headline": (
            "Lokalni in občinski kontekst Goriškega Krasa."
        ),
        "paragraphs": [
            "Območje požara obsega gozdne in kraške površine v več občinah "
            "Goriškega Krasa. Naselja so razmeroma redka, prevladujeta gozd "
            "in mediteranska makija.",
            "Občinske meje pomagajo umestiti dogodek v lokalni prostor, "
            "industrijska območja so v tem območju omejena, prometna "
            "infrastruktura pa redkejša kot v osrednji Sloveniji.",
        ],
        "relevant_layers": ["municipalities", "transport", "industrial"],
    },
    "cinkarna_celje_2019": {
        "headline": (
            "Industrijski in urbani kontekst Celja."
        ),
        "paragraphs": [
            "Lokacija je v industrijski coni Cinkarne Celje (Kidričeva), "
            "neposredno v urbanem tkivu Celja in v bližini stanovanjskih "
            "predelov.",
            "V okolici se prepletajo industrijska in poslovna območja, "
            "mestne ceste in železniške povezave — značilen primer "
            "soobstoja industrijske dejavnosti in mestnega prostora.",
        ],
        "relevant_layers": ["industrial", "municipalities", "transport"],
    },
}


# Shared disclaimer line shown in both new panels.
ASSOCIATION_NOTE_SLO = (
    "Prikaz kaže časovno-prostorsko povezavo v obdobju dogodka, ne dokazuje "
    "vzročnosti brez ARSO in vremenskih podatkov."
)


def _compute_event_impact(
    df: pd.DataFrame,
    event: dict,
    region_code: str,
) -> dict:
    """Compute before/during/after means and percent changes for one event.

    Splits the per-event/per-pollutant daily DataFrame by date relative to
    ``event_start`` / ``event_end`` (inclusive). When ``region_code`` is empty,
    averages across all available regions (Slovenia composite).

    Returns a dict with:
        status: one of
            "ok"          — before, during and after all have data.
            "full_month"  — before AND after are empty (event window covers
                             the whole analysis range, e.g. Cinkarna Celje).
            "no_event"    — event_start/event_end missing from metadata.
            "no_data"     — df is empty or no usable values at all.
            "no_before"   — before is empty (cannot compute % vs before).
            "no_after"    — after is empty (cannot compute % vs before for after).
        scope_label:        "Slovenija" or "<region_name>"
        n_before/during/after: row counts in each period
        mean_before/during/after: float | None
        change_during_vs_before_pct: float | None
        change_after_vs_before_pct: float | None
        event_start / event_end: ISO date strings (echoed for the UI)
    """
    if not event:
        return {"status": "no_event", "scope_label": "Slovenija"}
    es = event.get("event_start")
    ee = event.get("event_end")
    if not es or not ee:
        return {"status": "no_event", "scope_label": "Slovenija"}

    scope_label = "Slovenija"
    if region_code and not df.empty:
        sub = df[df["region_code"] == region_code]
        if not sub.empty:
            scope_label = str(sub["region_name"].iloc[0])
            df = sub
        else:
            # Region not present in this event slice — fall back to composite.
            region_code = ""

    if df.empty or "value_mean" not in df.columns:
        return {
            "status": "no_data",
            "scope_label": scope_label,
            "event_start": es, "event_end": ee,
        }

    # Date column is "YYYY-MM-DD" — string compare is safe for ISO dates.
    dates = df["date"].astype(str)
    before_mask = dates < es
    after_mask = dates > ee
    during_mask = (~before_mask) & (~after_mask)

    before_vals = df.loc[before_mask, "value_mean"]
    during_vals = df.loc[during_mask, "value_mean"]
    after_vals = df.loc[after_mask, "value_mean"]

    def _mean_or_none(s: pd.Series) -> float | None:
        s = s.dropna()
        if s.empty:
            return None
        return float(s.mean())

    mean_before = _mean_or_none(before_vals)
    mean_during = _mean_or_none(during_vals)
    mean_after = _mean_or_none(after_vals)

    # Full-month event window: before AND after slices are empty (e.g.
    # Cinkarna Celje where the whole month is the "event window").
    if before_vals.empty and after_vals.empty:
        return {
            "status": "full_month",
            "scope_label": scope_label,
            "event_start": es, "event_end": ee,
            "n_before": 0,
            "n_during": int(during_vals.notna().sum()),
            "n_after": 0,
            "mean_before": None,
            "mean_during": mean_during,
            "mean_after": None,
            "change_during_vs_before_pct": None,
            "change_after_vs_before_pct": None,
        }

    def _pct(numer: float | None, denom: float | None) -> float | None:
        if numer is None or denom is None:
            return None
        if denom == 0:
            return None
        return (numer - denom) / denom * 100.0

    change_during = _pct(mean_during, mean_before)
    change_after = _pct(mean_after, mean_before)

    if mean_before is None and mean_during is None and mean_after is None:
        status = "no_data"
    elif mean_before is None:
        status = "no_before"
    elif mean_after is None:
        status = "no_after"
    else:
        status = "ok"

    return {
        "status": status,
        "scope_label": scope_label,
        "event_start": es, "event_end": ee,
        "n_before": int(before_vals.notna().sum()),
        "n_during": int(during_vals.notna().sum()),
        "n_after": int(after_vals.notna().sum()),
        "mean_before": mean_before,
        "mean_during": mean_during,
        "mean_after": mean_after,
        "change_during_vs_before_pct": change_during,
        "change_after_vs_before_pct": change_after,
    }


def _slovene_date(date_str: str) -> str:
    """Format an ISO date string as e.g. '14. december 2025'."""
    if not date_str:
        return "—"
    try:
        d = pd.to_datetime(date_str)
    except (ValueError, TypeError):
        return str(date_str)
    return f"{d.day}. {SLO_MONTHS[d.month]} {d.year}"


def _slovene_window(event: dict) -> str:
    """Friendly event-window string in Slovene."""
    es, ee = event.get("event_start"), event.get("event_end")
    if not es or not ee:
        return ""
    if es == ee:
        return _slovene_date(es)
    try:
        d1 = pd.to_datetime(es); d2 = pd.to_datetime(ee)
    except (ValueError, TypeError):
        return f"{es} – {ee}"
    if d1.month == d2.month and d1.year == d2.year:
        return f"{d1.day}. – {d2.day}. {SLO_MONTHS[d1.month]} {d1.year}"
    return f"{_slovene_date(es)} – {_slovene_date(ee)}"


def _slovene_month_label(event: dict) -> str:
    """Return e.g. 'december 2025' from event metadata."""
    raw = event.get("month_label") or ""
    en_to_slo = {
        "January": "januar", "February": "februar", "March": "marec",
        "April": "april", "May": "maj", "June": "junij", "July": "julij",
        "August": "avgust", "September": "september", "October": "oktober",
        "November": "november", "December": "december",
    }
    for en, slo in en_to_slo.items():
        if en in raw:
            return raw.replace(en, slo).lower()
    # fall back to derived from analysis_start
    start = event.get("analysis_start") or event.get("event_start")
    if start:
        try:
            d = pd.to_datetime(start)
            return f"{SLO_MONTHS[d.month]} {d.year}"
        except (ValueError, TypeError):
            pass
    return raw


def _event_copy(event: dict) -> dict[str, str]:
    """Return {type, title, desc} for an event in Slovene, with fallbacks."""
    eid = event.get("event_id") or ""
    if eid in EVENT_COPY_SLO:
        return EVENT_COPY_SLO[eid]
    et = event.get("event_type") or ""
    return {
        "type": EVENT_TYPE_FALLBACK_SLO.get(et, "Primer"),
        "title": event.get("event_name") or event.get("event_id") or "Primer",
        "desc": event.get("description") or "",
    }


def _pollutant_choice_label(pollutant: str) -> ui.Tag:
    """Return a friendly HTML label for one pollutant chip."""
    spec = POLLUTANT_SPEC.get(pollutant, {"short": pollutant, "name_slo": pollutant})
    return ui.tags.span(
        ui.tags.span(spec["short"], class_="poll-short"),
        ui.tags.span(spec["name_slo"], class_="poll-name"),
    )


def _event_card_label(event: dict, index: int) -> ui.Tag:
    """Render a compact mission chip used as the label of a radio input.

    The radio input itself is hidden by CSS; clicking anywhere on this chip
    selects the event. The chip stays small enough to fit in the top
    mission-control header without crowding the map.
    """
    copy = _event_copy(event)
    code = f"M-{index:02d}"
    return ui.tags.span(
        ui.tags.span(
            ui.tags.span(code, class_="aw-mchip-code"),
            ui.tags.span(copy["title"], class_="aw-mchip-title"),
            ui.tags.span(copy["type"], class_="aw-mchip-type"),
            class_="aw-mchip",
        ),
    )


def _build_event_choices() -> dict[str, ui.Tag]:
    """Return {event_id: ui.Tag} for the mission-card radio group."""
    choices: dict[str, ui.Tag] = {}
    for idx, event in enumerate(_EVENTS_LIST, start=1):
        eid = event.get("event_id")
        if not eid:
            continue
        choices[eid] = _event_card_label(event, idx)
    return choices


_EVENT_CHOICES = _build_event_choices()
_DEFAULT_EVENT_ID = next(iter(_EVENT_CHOICES), None)


def _build_event_select_choices() -> dict[str, str]:
    """Plain-text {event_id: slovene title} for the top-left dropdown."""
    out: dict[str, str] = {}
    for event in _EVENTS_LIST:
        eid = event.get("event_id")
        if not eid:
            continue
        out[eid] = _event_copy(event)["title"]
    return out


_EVENT_SELECT_CHOICES = _build_event_select_choices()


# ---------------------------------------------------------------------------
# UI tree
# ---------------------------------------------------------------------------


# Plotly toolbar / mode-bar configuration: minimal, no clutter.
_PLOTLY_CONFIG = {
    "displayModeBar": False,
    "responsive": True,
    "scrollZoom": True,
    "doubleClick": "reset",
}


def _stat_cell(card_id: str, label: str, *,
               modifier: str = "", large: bool = False) -> ui.Tag:
    """Render a single statistic cell used in the summary grid."""
    cls = "aw-stat"
    if modifier:
        cls += f" {modifier}"
    if large:
        cls += " full"
    return ui.div(
        ui.div(label, class_="label"),
        ui.output_ui(card_id, inline=True),
        class_=cls,
    )


def _ctx_layer_row(input_id: str, layer_key: str) -> ui.Tag:
    """Render one toggle row in the GeoSlovenija context panel.

    When the matching GeoJSON file is missing on disk, the checkbox is
    disabled and a "Sloj ni naložen" hint is shown instead of the data
    source.
    """
    meta = CONTEXT_LAYER_META[layer_key]
    available = _CONTEXT_LAYER_AVAILABLE.get(layer_key, False)
    row_cls = "aw-ctx-row" if available else "aw-ctx-row aw-ctx-row-disabled"

    if available:
        checkbox = ui.input_checkbox(
            input_id, meta["label"], value=False,
        )
        source = ui.span(
            _resolved_layer_source(layer_key),
            class_="aw-ctx-source",
        )
    else:
        # Disabled stub: a non-interactive checkbox-like placeholder.
        checkbox = ui.tags.label(
            ui.tags.input(
                type="checkbox", disabled="disabled",
                class_="aw-ctx-disabled-input",
            ),
            ui.span(meta["label"], class_="aw-ctx-disabled-label"),
            class_="aw-ctx-disabled-row",
        )
        source = ui.span(
            "Sloj ni naložen",
            class_="aw-ctx-source aw-ctx-source-missing",
        )

    return ui.div(checkbox, source, class_=row_cls)


app_ui = ui.page_fluid(
    # ----- HEAD: humanist Google Fonts, custom CSS, custom JS --------------
    ui.head_content(
        ui.tags.meta(charset="utf-8"),
        ui.tags.meta(
            name="viewport",
            content="width=device-width, initial-scale=1",
        ),
        ui.tags.title("AirWatch SLO"),
        ui.tags.link(rel="icon", type="image/svg+xml", href="logo.png"),
        ui.tags.link(rel="preconnect", href="https://fonts.googleapis.com"),
        ui.tags.link(
            rel="preconnect",
            href="https://fonts.gstatic.com",
            crossorigin="",
        ),
        ui.tags.link(
            rel="stylesheet",
            href=(
                "https://fonts.googleapis.com/css2?"
                "family=Manrope:wght@400;500;600;700;800&"
                "family=DM+Sans:wght@400;500;600;700&"
                "family=JetBrains+Mono:wght@400;500;600;700&display=swap"
            ),
        ),
        ui.tags.link(rel="stylesheet", href="styles.css"),
        # Plotly.js — used by the custom-message map renderer. Loaded from CDN
        # explicitly so the map doesn't depend on shinywidgets bootstrapping.
        ui.tags.script(src="https://cdn.plot.ly/plotly-2.32.0.min.js"),
        ui.tags.script(src="app.js", defer="defer"),
    ),

    # ----- APP SHELL — map-first command center, no sidebar ----------------
    ui.div(

        # ===== STATUS BANNER (only renders if data missing) ===============
        ui.output_ui("status_banner"),

        # ===== MAIN MAP STAGE =============================================
        ui.tags.main(
            ui.div(

                # Two-column layout: map + timeline on the left, side rail
                # with controls and readouts on the right.
                ui.div(

                    # ---- LEFT COLUMN: map + timeline -------------------
                    ui.div(
                        ui.div(
                            ui.div(
                                # ----- regions scope block -----
                                ui.div(
                                    ui.div(
                                        "Dogodek",
                                        class_="aw-map-head-eyebrow",
                                    ),
                                    ui.input_select(
                                        "event_id",
                                        None,
                                        choices=(
                                            _EVENT_SELECT_CHOICES
                                            or {"": "Ni dogodkov"}
                                        ),
                                        selected=_DEFAULT_EVENT_ID,
                                    ),
                                    ui.div(
                                        ui.output_text(
                                            "map_title", inline=True
                                        ),
                                        class_="aw-map-head-date",
                                    ),
                                    ui.div(
                                        ui.output_text(
                                            "event_type_subtitle",
                                            inline=True,
                                        ),
                                        class_="aw-map-head-type",
                                    ),
                                    ui.div(
                                        "Onesnaževalo",
                                        class_="aw-map-head-eyebrow",
                                    ),
                                    ui.div(
                                        ui.input_radio_buttons(
                                            "pollutant",
                                            None,
                                            choices={
                                                "NO2": _pollutant_choice_label(
                                                    "NO2"
                                                )
                                            },
                                            selected="NO2",
                                            inline=True,
                                        ),
                                        class_="aw-poll-check",
                                    ),
                                    class_="aw-scope-regije-only",
                                ),

                                # ----- municipalities scope block -----
                                ui.div(
                                    ui.div(
                                        "Območje",
                                        class_="aw-map-head-eyebrow",
                                    ),
                                    ui.div(
                                        "Občine Slovenije",
                                        class_="aw-map-head-title-strong",
                                    ),
                                    ui.div(
                                        ui.output_text(
                                            "muni_year_label", inline=True
                                        ),
                                        class_="aw-map-head-date",
                                    ),
                                    ui.div(
                                        "Pokazatelj",
                                        class_="aw-map-head-eyebrow",
                                    ),
                                    ui.div(
                                        ui.input_radio_buttons(
                                            "muni_metric",
                                            None,
                                            choices={
                                                k: ui.tags.span(
                                                    spec["label"],
                                                    class_="poll-short",
                                                )
                                                for k, spec in MUNI_METRICS.items()
                                            },
                                            selected="PM10",
                                            inline=True,
                                        ),
                                        class_="aw-poll-check aw-poll-check-wide",
                                    ),
                                    class_="aw-scope-obcine-only",
                                ),
                                class_="aw-map-head",
                            ),
                            # Plotly mapbox is rendered into this static div
                            # by the `map_figure` custom message.
                            ui.tags.div(id="map_plot"),
                            # Floating colour + quality legend on bottom-right
                            # of the map. Rendered server-side so the ticks
                            # follow the current event / pollutant / mode.
                            ui.output_ui("map_legend_floating"),
                            class_="aw-map-canvas",
                            id="aw-map",
                        ),

                        # ---- Day timeline dock (under map) -------------
                        ui.div(
                            ui.tags.button(
                                ui.tags.span(class_="play-icon"),
                                ui.tags.span("Predvajaj", class_="play-label"),
                                id="aw-play-toggle",
                                type="button",
                                class_="aw-play-btn aw-scope-regije-only",
                                **{"aria-label": "Predvajaj animacijo skozi mesec"},
                            ),
                            # ----- regions: day-slider meta + slider -----
                            ui.div(
                                ui.div("Datum", class_="aw-tl-meta-label"),
                                ui.div(
                                    ui.output_text(
                                        "selected_date_display", inline=True
                                    ),
                                    class_="aw-tl-meta-value",
                                ),
                                class_="aw-tl-meta aw-scope-regije-only",
                            ),
                            ui.div(
                                ui.div("Razpon", class_="aw-tl-meta-label"),
                                ui.div(
                                    ui.output_ui(
                                        "day_counter_display", inline=True
                                    ),
                                    class_="aw-tl-meta-value",
                                ),
                                class_="aw-tl-meta aw-scope-regije-only",
                            ),
                            ui.div(
                                ui.output_ui("event_window_overlay"),
                                ui.input_slider(
                                    "day_index",
                                    None,
                                    min=1,
                                    max=31,
                                    value=1,
                                    step=1,
                                    ticks=True,
                                ),
                                class_="aw-slider-stage aw-scope-regije-only",
                            ),

                            # ----- municipalities: year-slider meta + slider -----
                            ui.div(
                                ui.div("Leto", class_="aw-tl-meta-label"),
                                ui.div(
                                    ui.output_text(
                                        "muni_year_value", inline=True
                                    ),
                                    class_="aw-tl-meta-value",
                                ),
                                class_="aw-tl-meta aw-scope-obcine-only",
                            ),
                            ui.div(
                                ui.div("Razpon", class_="aw-tl-meta-label"),
                                ui.div(
                                    f"{_MUNI_YEARS[0]} – {_MUNI_YEARS[-1]}",
                                    class_="aw-tl-meta-value",
                                ),
                                class_="aw-tl-meta aw-scope-obcine-only",
                            ),
                            ui.div(
                                ui.input_slider(
                                    "muni_year",
                                    None,
                                    min=_MUNI_YEARS[0],
                                    max=_MUNI_YEARS[-1],
                                    value=_MUNI_DEFAULT_YEAR,
                                    step=1,
                                    sep="",
                                    ticks=True,
                                ),
                                class_="aw-slider-stage aw-scope-obcine-only",
                            ),
                            class_="aw-timeline-dock",
                            id="aw-timeline",
                        ),
                        class_="aw-map-column",
                    ),

                    # ---- RIGHT COLUMN: side rail of cards --------------
                    ui.div(

                        # Card: scope + display mode toggle
                        ui.div(
                            ui.div("Način prikaza", class_="aw-card-title"),
                            ui.div(
                                ui.input_radio_buttons(
                                    "scope",
                                    None,
                                    choices={
                                        "regije": ui.tags.span("Regije"),
                                        "obcine": ui.tags.span("Občine"),
                                    },
                                    selected="regije",
                                    inline=True,
                                ),
                                class_="aw-mode-toggle aw-scope-toggle",
                            ),
                            # display_mode (Dejanske / Odstopanje) is meaningful
                            # only for the region view; hidden by CSS when the
                            # body has data-scope="obcine".
                            ui.div(
                                ui.div(
                                    "Prikaz",
                                    class_="aw-card-sublabel",
                                ),
                                ui.div(
                                    ui.input_radio_buttons(
                                        "display_mode",
                                        None,
                                        choices={
                                            "absolute": ui.tags.span("Dejanske"),
                                            "anomaly":  ui.tags.span("Odstopanje"),
                                        },
                                        selected="absolute",
                                        inline=True,
                                    ),
                                    class_="aw-mode-toggle",
                                ),
                                class_="aw-display-mode-wrap aw-scope-regije-only",
                            ),
                            class_="aw-card aw-card-mode",
                        ),

                        # Card: Slovenia composite value (no header, no date)
                        ui.div(
                            ui.div(
                                ui.div(
                                    ui.div("Povprečje SLO", class_="aw-tel-label"),
                                    ui.output_ui("t_slovenia_avg", inline=True),
                                    class_="aw-tel-cell aw-tel-primary",
                                ),
                                class_="aw-tel-grid",
                            ),
                            class_="aw-card",
                        ),

                        # Card: region selector + detail
                        ui.div(
                            ui.div("Izbrana regija", class_="aw-card-title"),
                            ui.input_select(
                                "region_code",
                                None,
                                choices={"": "Vse regije (povprečje Slovenije)"},
                                selected="",
                            ),
                            ui.output_ui("region_detail"),
                            class_="aw-card aw-card-region",
                        ),

                        # Card: GeoSlovenija context layers
                        ui.div(
                            ui.div("GeoSlovenija konteksti", class_="aw-card-title"),
                            ui.div(
                                "Satelitski podatki pokažejo, kako se signal "
                                "spreminja. Sloji eProstor in geo-peskovnik "
                                "pokažejo, kaj je v prostoru okoli dogodka.",
                                class_="aw-ctx-explain",
                            ),
                            ui.div(
                                ui.div(
                                    ui.input_checkbox(
                                        "ctx_event",
                                        "Lokacija dogodka",
                                        value=True,
                                    ),
                                    ui.span(
                                        "iz metapodatkov",
                                        class_="aw-ctx-source",
                                    ),
                                    class_="aw-ctx-row aw-ctx-row-event",
                                ),
                                _ctx_layer_row(
                                    "ctx_municipalities", "municipalities",
                                ),
                                _ctx_layer_row(
                                    "ctx_transport", "transport",
                                ),
                                _ctx_layer_row(
                                    "ctx_industrial", "industrial",
                                ),
                                class_="aw-ctx-list",
                            ),
                            class_="aw-card",
                        ),

                        class_="aw-side-rail",
                        id="aw-side-rail",
                    ),

                    class_="aw-stage-grid",
                ),

                class_="aw-stage",
            ),
            class_="aw-main",
        ),

        # ===== 3. TREND SECTION (below the map) ===========================
        ui.tags.section(
            ui.div(
                ui.div("Trend skozi mesec", class_="aw-sec-title"),
                ui.div(
                    "Cyan črta je dnevno povprečje, senčni pas je razpon "
                    "min–max. Oranžno označen je čas dogodka.",
                    class_="aw-sec-sub",
                ),
                class_="aw-sec-head",
            ),
            ui.div(
                output_widget("trend_plot"),
                class_="aw-trend-wrap",
            ),
            class_="aw-trend-section",
            id="aw-trend",
        ),

        # ===== 3. EVENT IMPACT + SPATIAL INTERPRETATION ===================
        ui.div(
            ui.div(
                ui.div(
                    ui.div("Vpliv dogodka", class_="aw-sec-title"),
                    ui.div(
                        "Primerjava povprečij pred dogodkom, med njim in po "
                        "njem za izbrano regijo in onesnaževalo.",
                        class_="aw-sec-sub",
                    ),
                    class_="aw-sec-head",
                ),
                ui.output_ui("impact_panel"),
                class_="aw-panel",
            ),
            ui.div(
                ui.div(
                    ui.div("Prostorska interpretacija", class_="aw-sec-title"),
                    ui.div(
                        "Kaj je v prostoru okoli dogodka — pomaga razumeti "
                        "satelitski signal v kontekstu.",
                        class_="aw-sec-sub",
                    ),
                    class_="aw-sec-head",
                ),
                ui.output_ui("spatial_panel"),
                class_="aw-panel",
            ),
            class_="aw-method-grid",
            id="aw-impact",
        ),

        # ===== 4. METHODOLOGY + EVENT META ================================
        ui.div(
            ui.div(
                ui.div(
                    ui.div("Kaj prikazuje ta nadzorna plošča",
                           class_="aw-sec-title"),
                    ui.div(
                        "Preberi pred razlago — pomaga razumeti, kaj številke "
                        "pomenijo in kaj ne.",
                        class_="aw-sec-sub",
                    ),
                    class_="aw-sec-head",
                ),
                ui.output_ui("methodology_block"),
                class_="aw-panel",
            ),
            ui.div(
                ui.div(
                    ui.div("Metapodatki misije", class_="aw-sec-title"),
                    ui.div(
                        ui.output_text("pollutant_subtitle", inline=True),
                        class_="aw-sec-sub",
                    ),
                    class_="aw-sec-head",
                ),
                ui.output_ui("event_metadata_summary"),
                class_="aw-panel",
            ),
            class_="aw-method-grid",
            id="aw-method",
        ),

        # ===== 5. STATUS FOOTER (plain-language mission log) ==============
        ui.div(
            ui.span("›", class_="icon"),
            ui.output_ui("mission_log", inline=True),
            class_="aw-status",
        ),

        # ===== APP FOOTER =================================================
        ui.div(
            ui.span(
                "AirWatch SLO © ",
                ui.output_ui("footer_year", inline=True),
            ),
            ui.span("·", class_="aw-footer-sep"),
            ui.span("Sentinel-5P · ESA Copernicus"),
            ui.span("·", class_="aw-footer-sep"),
            ui.span(
                "Univerza v Ljubljani — Fakulteta za računalništvo "
                "in informatiko"
            ),
            class_="aw-footer",
        ),

        class_="aw-app",
    ),
)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def _classify_day_status(event: dict, current_date: str) -> tuple[str, str]:
    """Return (slovene_label, css_class). Class is one of: pre / during / post."""
    if not event or not current_date:
        return ("—", "")
    es = event.get("event_start")
    ee = event.get("event_end")
    if not es or not ee:
        return ("—", "")
    if current_date < es:
        return ("Pred dogodkom", "pre")
    if current_date > ee:
        return ("Po dogodku", "post")
    return ("Med dogodkom", "during")


def _fmt_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, (int, np.integer)):
        return f"{int(value)}"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


# ---------------------------------------------------------------------------
# Map restyle helpers — used by the client-side Plotly.restyle pipeline that
# replaces only the choropleth's z/locations/customdata on each day tick,
# instead of rebuilding the whole mapbox figure.
# ---------------------------------------------------------------------------

_QUALITY_SLO = {"GOOD": "dobra", "PARTIAL": "delna", "MISSING": "ni podatkov"}


def _map_value_customdata(df: pd.DataFrame) -> list[list]:
    """Per-row hover payload for the values choropleth trace."""
    out: list[list] = []
    for _, r in df.iterrows():
        out.append([
            str(r["region_name"]),
            _slovene_date(str(r["date"])),
            float(r["value_mean"]) if pd.notna(r["value_mean"]) else None,
            float(r["value_min"]) if pd.notna(r["value_min"]) else None,
            float(r["value_max"]) if pd.notna(r["value_max"]) else None,
            float(r["sample_count"]) if pd.notna(r["sample_count"]) else None,
            _QUALITY_SLO.get(str(r.get("quality_status", "")).upper(), ""),
        ])
    return out


def _map_no_data_customdata(df: pd.DataFrame) -> list[list]:
    """Per-row hover payload for the no-data (grey) choropleth trace."""
    return [
        [str(r["region_name"]), _slovene_date(str(r["date"]))]
        for _, r in df.iterrows()
    ]


def _map_color_range(block: dict, mode: str) -> tuple[float, float]:
    """Stable colour-scale range across the whole event month.

    Computed once per (event, pollutant, mode) so the choropleth's colours
    stay comparable as we animate through the days. Without this, zmin/zmax
    would shift per day and identical concentrations would appear different.
    """
    days = block.get("days") or {}
    if not days:
        return (0.0, 1.0)
    if mode == "anomaly":
        series = [d["value_anomaly"] for d in days.values()
                  if "value_anomaly" in d.columns]
        if not series:
            return (-1.0, 1.0)
        vals = pd.concat(series).dropna()
        if vals.empty:
            return (-1.0, 1.0)
        amax = float(np.nanmax(np.abs(vals)))
        return (-amax, amax) if amax > 0 else (-1.0, 1.0)
    vals = pd.concat([d["value_mean"] for d in days.values()]).dropna()
    if vals.empty:
        return (0.0, 1.0)
    vmin = float(np.nanmin(vals))
    vmax = float(np.nanmax(vals))
    return (vmin, max(vmax, vmin + 1e-6))


# Esri "Dark Gray Canvas Base" raster tile service. Served over `white-bg`
# Plotly basemap so the canvas is the medium-dark gray the user asked for
# (the built-in `carto-darkmatter` reads almost pure black). Layer is placed
# `below="traces"` so the choropleth, labels and event markers paint on top.
_DARK_GRAY_BASEMAP_LAYER = dict(
    sourcetype="raster",
    sourceattribution=(
        "Esri, HERE, Garmin, FAO, NOAA, USGS, © OpenStreetMap contributors"
    ),
    source=[
        "https://services.arcgisonline.com/arcgis/rest/services/"
        "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
    ],
    below="traces",
)


def _mapbox_config_dark_gray(**overrides) -> dict:
    """Plotly `mapbox` config that uses the Dark Gray Canvas raster as basemap."""
    cfg = dict(
        style="white-bg",
        layers=[_DARK_GRAY_BASEMAP_LAYER],
        center=dict(lat=46.15, lon=14.99),
        zoom=7.0,
    )
    cfg.update(overrides)
    return cfg


def _build_municipality_figure(metric: str, year: int) -> go.Figure:
    """Bubble map of all municipalities coloured by ``metric`` for ``year``.

    Always uses the Dark Gray Canvas raster basemap. The colour-scale range
    is fixed across years so the same colour means the same value over time.
    """
    spec = MUNI_METRICS.get(metric, MUNI_METRICS["PM10"])
    fig = go.Figure()

    if _MUNI_DF.empty or metric not in _MUNI_DF.columns:
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            mapbox=_mapbox_config_dark_gray(uirevision="map-keep-view"),
            margin=dict(l=0, r=0, t=0, b=0),
            height=680,
            showlegend=False,
        )
        fig.add_annotation(
            text="Občinski podatki niso na voljo.",
            font=dict(color="#c0cbe0",
                      family="DM Sans, system-ui, sans-serif", size=14),
            showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper",
        )
        return fig

    zmin, zmax = _muni_metric_range(metric)
    sub = _MUNI_DF[_MUNI_DF["year"] == year].copy()
    sub[metric] = pd.to_numeric(sub[metric], errors="coerce")
    valid = sub.dropna(subset=[metric, "lat", "lon"])
    missing = sub[sub[metric].isna()]

    unit = spec["unit"]
    title = spec["name_slo"]

    # Municipalities with no data this year — small grey hollow dots.
    if not missing.empty:
        fig.add_trace(go.Scattermapbox(
            lat=missing["lat"], lon=missing["lon"],
            mode="markers",
            marker=dict(size=6, color="rgba(170,180,196,0.55)"),
            text=missing["muni"],
            hovertemplate=(
                "<b>%{text}</b><br>"
                f"{title} ({year}): ni podatka<extra></extra>"
            ),
            showlegend=False,
        ))

    if not valid.empty:
        fig.add_trace(go.Scattermapbox(
            lat=valid["lat"], lon=valid["lon"],
            mode="markers",
            marker=dict(
                size=13,
                color=valid[metric].astype(float).tolist(),
                colorscale=NO2_COLORSCALE,
                cmin=zmin, cmax=zmax,
                opacity=0.92,
            ),
            text=valid["muni"],
            customdata=valid[[metric]].values,
            hovertemplate=(
                "<b>%{text}</b><br>"
                f"{title}: %{{customdata[0]:.2f}} {unit}<br>"
                f"Leto: {year}<extra></extra>"
            ),
            showlegend=False,
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        mapbox=_mapbox_config_dark_gray(uirevision="map-keep-view"),
        margin=dict(l=0, r=0, t=0, b=0),
        height=680,
        showlegend=False,
        font=dict(family="DM Sans, system-ui, sans-serif", color="#e6edf6"),
        hoverlabel=dict(
            bgcolor="rgba(18,24,38,0.96)",
            bordercolor="rgba(14,155,209,0.55)",
            font=dict(family="DM Sans, system-ui, sans-serif",
                      color="#e6edf6", size=12),
        ),
    )
    return fig


def server(input, output, session):

    # -------- reactive data -------------------------------------------------
    # All heavy lifting is precomputed in _EVENT_CACHE at module import. The
    # reactive layer here is purely about dependency tracking on input.event_id
    # / input.day_index — no recomputation per render.

    @reactive.calc
    def data() -> pd.DataFrame:
        # Module-level cached frame; reactive.calc tags it as a stable dependency.
        return _COMBINED_DF

    @reactive.calc
    def metadata() -> dict:
        return _INITIAL_METADATA

    @reactive.calc
    def events_list() -> list[dict]:
        return _EVENTS_LIST

    @reactive.calc
    def event_cache_entry() -> dict:
        return _EVENT_CACHE.get(input.event_id() or "", {})

    @reactive.calc
    def selected_pollutant() -> str:
        """Currently selected pollutant for this event (with safe fallback)."""
        entry = event_cache_entry()
        available = entry.get("pollutants") or []
        chosen = input.pollutant() if "pollutant" in input else None
        if chosen and chosen in available:
            return chosen
        return entry.get("default_pollutant", "NO2")

    @reactive.calc
    def pollutant_block() -> dict:
        return cache_pollutant_block(input.event_id() or "", selected_pollutant())

    @reactive.calc
    def event_df() -> pd.DataFrame:
        return pollutant_block().get("df", pd.DataFrame())

    @reactive.calc
    def selected_event() -> dict:
        return event_cache_entry().get("event", {})

    @reactive.calc
    def max_day_index() -> int:
        return event_cache_entry().get("max_day", 31)

    @reactive.calc
    def pollutant_spec() -> dict:
        """Display spec for the currently selected pollutant."""
        return POLLUTANT_SPEC.get(selected_pollutant(), POLLUTANT_SPEC["NO2"])

    @reactive.calc
    def current_unit() -> str:
        return pollutant_spec().get("display_unit", NO2_UNIT)

    # -------- reactive effects: keep slider + region select in sync --------

    # NOTE on @reactive.event below: these effects must ONLY fire when the
    # event_id changes — never on every pollutant click or every day-slider
    # tick. Otherwise each tick rebuilds the radio-button / slider / select
    # DOM via ui.update_*, which causes the entire control to flash and feels
    # like a full-page refresh.

    @reactive.effect
    @reactive.event(input.event_id)
    def _update_day_slider():
        entry = event_cache_entry()
        if not entry:
            return
        max_day = max(entry.get("max_day", 1), 1)
        with reactive.isolate():
            current = input.day_index() or 1
        if current > max_day:
            current = 1
        ui.update_slider(
            "day_index", min=1, max=max_day, value=current, step=1,
        )

    @reactive.effect
    @reactive.event(input.event_id)
    def _update_pollutant_choices():
        """Sync pollutant chips to the current event's available pollutants.

        Fires only when the event changes — without this scope, every
        pollutant click would re-render the whole chip group.
        """
        if "pollutant" not in input:
            return
        entry = event_cache_entry()
        available = entry.get("pollutants") or ["NO2"]
        choices = {p: _pollutant_choice_label(p) for p in available}
        with reactive.isolate():
            current = input.pollutant() if "pollutant" in input else ""
        if current not in choices:
            current = entry.get("default_pollutant", available[0] if available else "NO2")
        ui.update_radio_buttons(
            "pollutant",
            choices=choices,
            selected=current,
        )

    @reactive.effect
    @reactive.event(input.event_id)
    def _update_region_choices():
        """Region list is the same across pollutants — only refresh per event."""
        entry = event_cache_entry()
        default_pollutant = entry.get("default_pollutant", "NO2")
        block = cache_pollutant_block(input.event_id() or "", default_pollutant)
        choices = block.get("region_choices") or {
            "": "Vse regije (povprečje Slovenije)"
        }
        with reactive.isolate():
            current_region = input.region_code() if "region_code" in input else ""
        ui.update_select(
            "region_code",
            choices=choices,
            selected=current_region if current_region in choices else "",
        )

    @reactive.calc
    def day_df() -> pd.DataFrame:
        block = pollutant_block()
        days = block.get("days") or {}
        day_index = input.day_index() or 1
        return days.get(int(day_index), pd.DataFrame())

    @reactive.calc
    def event_month_means() -> pd.Series:
        """Mean per region across the event month (for anomaly mode)."""
        return pollutant_block().get("month_means", pd.Series(dtype=float))

    @reactive.calc
    def day_df_display() -> pd.DataFrame:
        """day_df with a `value_display` column added (no recomputation).

        In `absolute` mode, value_display == value_mean.
        In `anomaly` mode,  value_display == precomputed value_anomaly column.
        """
        df = day_df()
        if df.empty:
            return df
        df = df.copy()
        mode = input.display_mode() if "display_mode" in input else "absolute"
        if mode == "anomaly" and "value_anomaly" in df.columns:
            df["value_display"] = df["value_anomaly"]
        else:
            df["value_display"] = df["value_mean"]
        return df

    @reactive.calc
    def current_date_str() -> str:
        df = day_df()
        if df.empty:
            return ""
        return str(df["date"].iloc[0])

    # -------- HERO badges --------------------------------------------------

    @output
    @render.ui
    def hero_status_badge():
        meta = metadata() or {}
        status = (meta.get("dataset_status") or "unknown").lower()
        if status == "live":
            return ui.span(
                ui.span(class_="dot"),
                "Podatki v živo",
                class_="aw-badge live",
            )
        if status == "sample":
            return ui.span(
                ui.span(class_="dot"),
                "Vzorčni podatki",
                class_="aw-badge sample",
            )
        return ui.span(
            ui.span(class_="dot"),
            "Stanje neznano",
            class_="aw-badge sample",
        )

    # -------- HEADER + STATUS derived UI ----------------------------------

    @output
    @render.ui
    def footer_year():
        from datetime import datetime as _dt
        return ui.HTML(str(_dt.now().year))

    # -------- POLLUTANT SUBTITLE ------------------------------------------

    @output
    @render.text
    def pollutant_subtitle():
        spec = pollutant_spec()
        entry = event_cache_entry()
        n_available = len(entry.get("pollutants") or [])
        more = (f"Za ta primer je na voljo {n_available} onesnaževalcev "
                "(spodaj jih lahko preklopiš).")
        return f"{spec.get('relevance_slo', '')} {more}"

    # -------- TIMELINE -----------------------------------------------------

    @output
    @render.text
    def selected_date_display():
        d = current_date_str()
        return _slovene_date(d) if d else "—"

    @output
    @render.text
    def selected_date_compact():
        """Short date shown in the floating telemetry overlay (e.g. '14. dec'). """
        d = current_date_str()
        if not d:
            return "—"
        try:
            dd = pd.to_datetime(d)
            month_short = SLO_MONTHS[dd.month][:3]
            return f"{dd.day}. {month_short} {dd.year}"
        except (ValueError, TypeError):
            return d

    @output
    @render.ui
    def day_counter_display():
        df = event_df()
        if df.empty:
            return ui.tags.span("Dan — od —")
        day = input.day_index() or 1
        total = max(int(df["day_index"].max()), 1)
        ev = selected_event()
        label, status_cls = _classify_day_status(ev, current_date_str())
        return ui.tags.span(
            f"Dan {day} od {total}",
            ui.tags.span(label, class_=f"status {status_cls}") if label != "—" else "",
        )

    @output
    @render.ui
    def event_window_overlay():
        """Thin vertical marker on the slider at the exact event-start day."""
        ew = event_cache_entry().get("event_window")
        if not ew:
            return ui.div()
        date_label = _slovene_date(ew.get("event_start", ""))
        return ui.div(
            ui.div(
                ui.div(ew["label"], class_="aw-event-marker-title"),
                ui.div(date_label, class_="aw-event-marker-date"),
                class_="aw-event-marker-pill",
            ),
            class_="aw-event-marker",
            style=(
                # 0.985 + 0.8% offset compensates for ionRangeSlider handle padding
                f"left: calc({ew['start_pct']:.2f}% * 0.985 + 0.8%);"
            ),
        )

    # -------- MAP ----------------------------------------------------------

    @output
    @render.text
    def map_title():
        d = current_date_str()
        return _slovene_date(d) if d else "Slovenija"

    @output
    @render.text
    def map_subtitle():
        ev = selected_event()
        if not ev:
            return "Izberi primer zgoraj."
        copy = _event_copy(ev)
        spec = pollutant_spec()
        return f"{copy['type']} · {copy['title']} · {spec['name_slo']} ({spec['short']})"

    @output
    @render.text
    def event_type_subtitle():
        """Short event-type label shown under the map-head dropdown."""
        ev = selected_event()
        if not ev:
            return ""
        return _event_copy(ev)["type"]

    # -- Municipality scope helpers ----------------------------------------

    @reactive.calc
    def scope_value() -> str:
        return (input.scope() if "scope" in input else "regije") or "regije"

    @reactive.calc
    def muni_year() -> int:
        if "muni_year" in input and input.muni_year() is not None:
            try:
                return int(input.muni_year())
            except (TypeError, ValueError):
                pass
        return _MUNI_DEFAULT_YEAR

    @reactive.calc
    def muni_metric() -> str:
        m = input.muni_metric() if "muni_metric" in input else None
        return m if m in MUNI_METRICS else "PM10"

    @output
    @render.text
    def muni_year_label():
        return f"Leto: {muni_year()}"

    @output
    @render.text
    def muni_year_value():
        return str(muni_year())

    @output
    @render.text
    def map_mode_label():
        mode = input.display_mode() if "display_mode" in input else "absolute"
        short = pollutant_spec()["short"]
        return ("Prikaz: odstopanje od povprečja"
                if mode == "anomaly"
                else f"Prikaz: dejanske vrednosti {short}")

    # ---- Floating bottom-right map legend (colour ramp + quality pips) ----

    @output
    @render.ui
    def map_legend_floating():
        # ---- Občine scope: bubble-map legend ----
        if scope_value() == "obcine":
            metric = muni_metric()
            mspec = MUNI_METRICS.get(metric, MUNI_METRICS["PM10"])
            zmin, zmax = _muni_metric_range(metric)
            mid_val = (zmin + zmax) / 2.0
            cscale = NO2_COLORSCALE
            gradient_css = ", ".join(
                f"{col} {pos * 100:.1f}%" for pos, col in cscale
            )
            ramp_title = f"{mspec['name_slo']} · {mspec['unit']}"
            return ui.div(
                ui.div(ramp_title, class_="aw-mlegend-title"),
                ui.div(
                    ui.span(
                        class_="aw-mlegend-ramp",
                        style=f"background: linear-gradient(90deg, {gradient_css});",
                    ),
                    ui.div(
                        ui.span(f"{zmin:.2f}", class_="aw-mlegend-tick"),
                        ui.span(f"{mid_val:.2f}", class_="aw-mlegend-tick"),
                        ui.span(f"{zmax:.2f}", class_="aw-mlegend-tick"),
                        class_="aw-mlegend-ticks",
                    ),
                    class_="aw-mlegend-ramp-wrap",
                ),
                ui.div(
                    f"Letno povprečje, leto {muni_year()} · 212 občin",
                    class_="aw-mlegend-note",
                ),
                class_="aw-mlegend",
            )

        # ---- Regije scope (existing event-based legend) ----
        block = pollutant_block()
        mode = input.display_mode() if "display_mode" in input else "absolute"
        spec = pollutant_spec()
        unit = spec.get("display_unit", NO2_UNIT)
        p_short = spec.get("short", "NO₂")
        decimals = int(spec.get("decimals", 1))

        zmin, zmax = _map_color_range(block, mode)
        cscale = ANOMALY_COLORSCALE if mode == "anomaly" else NO2_COLORSCALE
        gradient_css = ", ".join(
            f"{col} {pos * 100:.1f}%" for pos, col in cscale
        )

        if mode == "anomaly":
            ramp_title = f"Odstopanje {p_short} od povp. meseca"
            mid_val = 0.0
        else:
            ramp_title = f"{p_short} · {unit}"
            mid_val = (zmin + zmax) / 2.0

        def _fmt(v: float) -> str:
            return (f"{v:+.{decimals}f}" if mode == "anomaly"
                    else f"{v:.{decimals}f}")

        return ui.div(
            ui.div(ramp_title, class_="aw-mlegend-title"),
            ui.div(
                ui.span(
                    class_="aw-mlegend-ramp",
                    style=f"background: linear-gradient(90deg, {gradient_css});",
                ),
                ui.div(
                    ui.span(_fmt(zmin), class_="aw-mlegend-tick"),
                    ui.span(_fmt(mid_val), class_="aw-mlegend-tick"),
                    ui.span(_fmt(zmax), class_="aw-mlegend-tick"),
                    class_="aw-mlegend-ticks",
                ),
                class_="aw-mlegend-ramp-wrap",
            ),
            ui.div(
                ui.div(
                    ui.span(class_="aw-qpip good"),
                    ui.span("dobra", class_="aw-mlegend-qlabel"),
                    class_="aw-mlegend-qrow",
                ),
                ui.div(
                    ui.span(class_="aw-qpip partial"),
                    ui.span("delna", class_="aw-mlegend-qlabel"),
                    class_="aw-mlegend-qrow",
                ),
                ui.div(
                    ui.span(class_="aw-qpip missing"),
                    ui.span("ni podatkov", class_="aw-mlegend-qlabel"),
                    class_="aw-mlegend-qrow",
                ),
                class_="aw-mlegend-quality",
            ),
            class_="aw-mlegend",
        )

    # The map figure is rebuilt on every relevant input change INCLUDING the
    # day slider, so the choropleth fill always matches the current day's
    # values. mapbox-level `uirevision="map-keep-view"` keeps the user's
    # pan/zoom across rebuilds. Deps are read manually (not via @reactive.event)
    # so that no input-suppression rule can ever block a day-tick rebuild.
    @reactive.calc
    def map_figure():
        # Explicit reactive dep reads — Shiny tracks each call.
        _ = input.event_id()
        _ = input.day_index()
        if "pollutant" in input:
            _ = input.pollutant()
        if "display_mode" in input:
            _ = input.display_mode()
        if "region_code" in input:
            _ = input.region_code()
        # Scope dep — switches the whole figure when the user toggles Občine.
        _ = scope_value()
        if scope_value() == "obcine":
            return _build_municipality_figure(muni_metric(), muni_year())
        # GeoSlovenija / eProstor context-layer toggles — re-render the map
        # whenever a layer is shown or hidden.
        ctx_show_event = bool(input.ctx_event()) if "ctx_event" in input else True
        ctx_show_muni = (
            bool(input.ctx_municipalities())
            if "ctx_municipalities" in input else False
        )
        ctx_show_transport = (
            bool(input.ctx_transport())
            if "ctx_transport" in input else False
        )
        ctx_show_industrial = (
            bool(input.ctx_industrial())
            if "ctx_industrial" in input else False
        )
        df_disp = day_df_display()
        block = pollutant_block()
        ev = selected_event()
        mode = input.display_mode() if "display_mode" in input else "absolute"
        selected_region = input.region_code() if "region_code" in input else ""
        fig = go.Figure()

        # Empty-state map
        if not _REGIONS_GEOJSON.get("features"):
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                mapbox=_mapbox_config_dark_gray(),
                margin=dict(l=0, r=0, t=0, b=0),
                height=680,
                showlegend=False,
            )
            fig.add_annotation(
                text="Ni razpoložljivih podatkov.",
                font=dict(color="#c0cbe0",
                          family="DM Sans, system-ui, sans-serif", size=14),
                showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper",
            )
            return fig

        # Month-wide colour range — stable as we animate through the days.
        zmin, zmax = _map_color_range(block, mode)
        unit = current_unit()
        p_short = pollutant_spec()["short"]
        decimals = pollutant_spec().get("decimals", 1)
        if mode == "anomaly":
            cscale = ANOMALY_COLORSCALE
            color_title = f"Odstopanje {p_short} od povp. meseca"
        else:
            cscale = NO2_COLORSCALE
            color_title = f"{p_short} ({unit})"

        # Initial-paint slices (day at build time). After this, restyle owns it.
        if df_disp.empty:
            wv = pd.DataFrame(columns=["region_code", "value_display"])
            nv = pd.DataFrame(columns=["region_code"])
        else:
            wv = df_disp.dropna(subset=["value_display"])
            nv = df_disp[df_disp["value_display"].isna()]

        hovertemplate_val = (
            "<b>%{customdata[0]}</b><br>"
            "%{customdata[1]}<br>"
            f"{p_short}: %{{customdata[2]:.{decimals}f}} {unit}<br>"
            f"Najmanj/največ: %{{customdata[3]:.{decimals}f}} / %{{customdata[4]:.{decimals}f}}<br>"
            "Kakovost meritve: %{customdata[6]}"
            "<extra></extra>"
        )

        # ---- Trace 0: choropleth for regions WITH data
        fig.add_trace(
            go.Choroplethmapbox(
                geojson=_REGIONS_GEOJSON,
                locations=wv["region_code"].astype(str).tolist(),
                z=wv["value_display"].astype(float).tolist() if not wv.empty else [],
                featureidkey="properties.region_code",
                colorscale=cscale,
                zmin=zmin, zmax=zmax,
                marker=dict(
                    line=dict(color="rgba(0,0,0,0.55)", width=2.2),
                    opacity=0.85,
                ),
                customdata=_map_value_customdata(wv) if not wv.empty else [],
                hovertemplate=hovertemplate_val,
                name="",
                # On-map floating legend handles the colour ramp now.
                showscale=False,
            )
        )

        # ---- Trace 1: choropleth for regions WITHOUT data
        fig.add_trace(
            go.Choroplethmapbox(
                geojson=_REGIONS_GEOJSON,
                locations=nv["region_code"].astype(str).tolist(),
                z=[0.0] * len(nv),
                featureidkey="properties.region_code",
                colorscale=[[0, "rgba(70,80,100,0.55)"], [1, "rgba(70,80,100,0.55)"]],
                showscale=False,
                marker=dict(
                    line=dict(color="rgba(0,0,0,0.55)", width=2.2),
                    opacity=0.65,
                ),
                customdata=_map_no_data_customdata(nv) if not nv.empty else [],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "%{customdata[1]}<br>"
                    "Ni zanesljive satelitske meritve."
                    "<extra></extra>"
                ),
                name="",
            )
        )

        # ---- Layer 2.5: region-name text labels at each centroid ----
        if _REGION_CENTROIDS:
            lab_lats: list[float] = []
            lab_lons: list[float] = []
            lab_texts: list[str] = []
            for rc, (lat, lon) in _REGION_CENTROIDS.items():
                name = _REGION_NAMES.get(rc, rc)
                if not name:
                    continue
                lab_lats.append(lat); lab_lons.append(lon); lab_texts.append(name)
            if lab_lats:
                fig.add_trace(go.Scattermapbox(
                    lat=lab_lats, lon=lab_lons,
                    mode="text",
                    text=lab_texts,
                    textfont=dict(
                        family="Manrope, system-ui, sans-serif",
                        size=12,
                        color="rgba(245,248,252,0.85)",
                    ),
                    textposition="middle center",
                    hoverinfo="skip",
                    showlegend=False,
                ))

        # ---- Layer 2.6: capital / main town of each region ----
        # Small white dot at the city centre + town name below it. Orients
        # the reader; no measurement data attached.
        if _REGION_CAPITALS:
            cap_lats: list[float] = []
            cap_lons: list[float] = []
            cap_names: list[str] = []
            for cap in _REGION_CAPITALS.values():
                cap_lats.append(cap["lat"])
                cap_lons.append(cap["lon"])
                cap_names.append(cap["name"])
            if cap_lats:
                # dot markers
                fig.add_trace(go.Scattermapbox(
                    lat=cap_lats, lon=cap_lons,
                    mode="markers",
                    marker=dict(
                        size=6,
                        color="#ffffff",
                    ),
                    hovertext=cap_names,
                    hovertemplate="<b>%{hovertext}</b><extra></extra>",
                    showlegend=False,
                ))
                # town-name text labels just below each dot
                fig.add_trace(go.Scattermapbox(
                    lat=cap_lats, lon=cap_lons,
                    mode="text",
                    text=cap_names,
                    textfont=dict(
                        family="DM Sans, system-ui, sans-serif",
                        size=10,
                        color="#ffffff",
                    ),
                    textposition="bottom right",
                    hoverinfo="skip",
                    showlegend=False,
                ))

        # ---- Layer 3: strong highlight ring on selected region's centroid
        if selected_region and selected_region in _REGION_CENTROIDS:
            clat, clon = _REGION_CENTROIDS[selected_region]
            # outer glow
            fig.add_trace(go.Scattermapbox(
                lat=[clat], lon=[clon],
                mode="markers",
                marker=dict(size=64, color="rgba(14,155,209,0.22)"),
                hoverinfo="skip", showlegend=False,
            ))
            # inner ring
            fig.add_trace(go.Scattermapbox(
                lat=[clat], lon=[clon],
                mode="markers",
                marker=dict(size=22, color="rgba(14,155,209,0.95)"),
                hoverinfo="skip", showlegend=False,
            ))

        # ---- Layer 4: event location marker — pulsing-style halo + core
        # Always shown by default (toggle defaults to True). Provenance:
        # event metadata (data_pipeline/events/events.json or the multipollutant
        # metadata file). Coordinates are EPSG:4326.
        if (
            ctx_show_event and ev
            and ev.get("event_lat") is not None
            and ev.get("event_lon") is not None
        ):
            elat = ev["event_lat"]; elon = ev["event_lon"]
            label = ev.get("event_location_name") or ev.get("event_name") or "Lokacija dogodka"
            copy = _event_copy(ev)
            # outer halo
            fig.add_trace(go.Scattermapbox(
                lat=[elat], lon=[elon],
                mode="markers",
                marker=dict(size=58, color="rgba(255,90,90,0.18)"),
                hoverinfo="skip", showlegend=False,
            ))
            # middle halo
            fig.add_trace(go.Scattermapbox(
                lat=[elat], lon=[elon],
                mode="markers",
                marker=dict(size=32, color="rgba(255,90,90,0.32)"),
                hoverinfo="skip", showlegend=False,
            ))
            # core marker
            fig.add_trace(go.Scattermapbox(
                lat=[elat], lon=[elon],
                mode="markers+text",
                marker=dict(size=14, color="#ff6a6a"),
                text=[copy["title"]],
                textposition="top right",
                textfont=dict(family="Manrope, system-ui, sans-serif",
                              color="#ffd1d1", size=12),
                hovertemplate=(
                    f"<b>{copy['title']}</b><br>{label}<extra></extra>"
                ),
                showlegend=False,
            ))

        # ---- Layer 5+: GeoSlovenija / eProstor context overlays ----
        # Each layer is drawn only if (a) its file is present on disk AND
        # (b) the matching toggle is on. Styles are subtle so the NUTS3
        # choropleth stays the primary reading.
        if ctx_show_muni and _CONTEXT_LAYER_AVAILABLE.get("municipalities"):
            _add_polygon_outline_layer(
                fig,
                _CONTEXT_LAYERS["municipalities"],
                line_color="rgba(255,255,255,0.32)",
                line_width=0.7,
                name="Občine (eProstor)",
            )

        if ctx_show_transport and _CONTEXT_LAYER_AVAILABLE.get("transport"):
            _add_line_layer(
                fig,
                _CONTEXT_LAYERS["transport"],
                line_color="rgba(14,155,209,0.85)",
                line_width=1.2,
                name="Prometna infrastruktura (eProstor)",
            )

        if ctx_show_industrial and _CONTEXT_LAYER_AVAILABLE.get("industrial"):
            _add_industrial_layer(
                fig,
                _CONTEXT_LAYERS["industrial"],
                fill_color="rgba(217,102,55,0.22)",
                line_color="rgba(217,102,55,0.85)",
                point_color="rgba(217,102,55,0.95)",
                name="Industrijska in poslovna območja (geo-peskovnik)",
            )

        # ---- Layout
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            mapbox=_mapbox_config_dark_gray(uirevision="map-keep-view"),
            margin=dict(l=0, r=0, t=0, b=0),
            height=680,
            showlegend=False,
            font=dict(family="DM Sans, system-ui, sans-serif", color="#e6edf6"),
            hoverlabel=dict(
                bgcolor="rgba(18,24,38,0.96)",
                bordercolor="rgba(14,155,209,0.55)",
                font=dict(family="DM Sans, system-ui, sans-serif",
                          color="#e6edf6", size=12),
            ),
        )
        return fig

    @reactive.effect
    async def _push_map_figure():
        # Ship the full Plotly figure to the client and let JS call
        # Plotly.newPlot on the static #map_plot div. This avoids shinywidgets
        # and Plotly.react diffing entirely, so the choropleth fill is always
        # freshly drawn for the current day.
        fig = map_figure()
        try:
            payload = json.loads(pio.to_json(fig))
        except Exception:
            return
        try:
            await session.send_custom_message("map_figure", payload)
        except Exception:
            # Session can be torn down mid-animation; swallow gracefully.
            pass

    # -------- SUMMARY READOUTS --------------------------------------------

    def _stat_value(text: str, unit: str | None = None, sub: str | None = None) -> ui.Tag:
        """Build the .value span used inside an aw-stat cell.

        Defaults the unit to the currently selected pollutant's display unit.
        """
        if unit is None:
            unit = current_unit()
        children: list = [text]
        if unit:
            children.append(ui.span(unit, class_="unit"))
        if sub:
            children.append(ui.span(sub, class_="sub"))
        return ui.span(*children, class_="value")

    @output
    @render.ui
    def t_slovenia_avg():
        df = day_df_display().dropna(subset=["value_display"])
        if df.empty:
            return _stat_value("—", unit="")
        val = float(df["value_display"].mean())
        sub = ("odstopanje od povprečja"
               if input.display_mode() == "anomaly"
               else "povprečje 12 regij")
        return _stat_value(_fmt_value(val), sub=sub)

    @output
    @render.ui
    def t_highest():
        df = day_df_display().dropna(subset=["value_display"])
        if df.empty:
            return _stat_value("—", unit="")
        row = df.loc[df["value_display"].idxmax()]
        return _stat_value(
            _fmt_value(row["value_display"]),
            sub=str(row["region_name"]),
        )

    @output
    @render.ui
    def t_lowest():
        df = day_df_display().dropna(subset=["value_display"])
        if df.empty:
            return _stat_value("—", unit="")
        row = df.loc[df["value_display"].idxmin()]
        return _stat_value(
            _fmt_value(row["value_display"]),
            sub=str(row["region_name"]),
        )

    @output
    @render.ui
    def t_valid():
        df = day_df()
        if df.empty:
            return _stat_value("—", unit="")
        total = len(df)
        valid = int(df["value_mean"].notna().sum())
        return _stat_value(
            f"{valid} / {total}",
            unit="",
            sub="regij ima meritev",
        )

    @output
    @render.ui
    def t_quality():
        df = day_df()
        if df.empty:
            return _stat_value("—", unit="")
        counts = df["quality_status"].fillna("missing").value_counts()
        good = int(counts.get("good", 0))
        partial = int(counts.get("partial", 0))
        missing = int(counts.get("missing", 0))
        total = len(df) or 1
        share = (good + partial) / total * 100
        return _stat_value(
            f"{share:.0f}",
            unit="%",
            sub=f"dobra: {good} · delna: {partial} · ni: {missing}",
        )

    # -------- REGION DETAIL ------------------------------------------------

    @output
    @render.ui
    def region_detail():
        df_disp = day_df_display()
        region_code = input.region_code() if "region_code" in input else ""
        mode = input.display_mode() if "display_mode" in input else "absolute"
        if df_disp.empty or not region_code:
            return ui.div(
                ui.div(
                    "Trenutno prikazano: vse regije",
                    class_="region-name",
                ),
                ui.div(
                    "Izberi eno od slovenskih statističnih regij iz seznama "
                    "zgoraj, da vidiš njeno meritev za izbrani dan in "
                    "primerjavo s povprečjem meseca.",
                    class_="interp",
                ),
            )

        row = df_disp[df_disp["region_code"] == region_code]
        if row.empty:
            return ui.div(
                ui.div(
                    "Za to regijo ni podatkov za izbrani dan.",
                    class_="region-name",
                ),
            )
        row = row.iloc[0]
        value_display = row["value_display"]
        value_mean = row["value_mean"]
        quality = str(row.get("quality_status", "missing")).lower()
        quality_label_slo = {
            "good": "Dobra meritev",
            "partial": "Delna meritev",
            "missing": "Ni podatkov",
        }.get(quality, quality.capitalize())
        quality_cls = (
            "quality-pill" if quality == "good"
            else f"quality-pill {quality}"
        )

        # Monthly rank
        month_means = event_month_means()
        rank_text = ""
        if region_code in month_means.index and len(month_means) > 1:
            month_means_sorted = month_means.dropna().sort_values(ascending=False)
            if region_code in month_means_sorted.index:
                rank = list(month_means_sorted.index).index(region_code) + 1
                rank_text = (
                    f"V tem mesecu: {rank}. mesto od {len(month_means_sorted)} "
                    f"po povprečni vrednosti."
                )

        unit = current_unit()
        p_short = pollutant_spec()["short"]
        decimals = pollutant_spec().get("decimals", 1)

        # Plain Slovene interpretation sentence
        interp = ""
        if pd.notna(value_mean) and region_code in month_means.index:
            baseline = month_means[region_code]
            delta = value_mean - baseline
            if pd.notna(baseline) and baseline > 0:
                pct = abs(delta / baseline * 100)
                if delta > 0:
                    interp = (
                        f"Regija {row['region_name']} ima ta dan vrednost "
                        f"{p_short} za {pct:.0f}% višjo od svojega povprečja tega "
                        f"meseca ({value_mean:.{decimals}f} v primerjavi z "
                        f"{baseline:.{decimals}f} {unit})."
                    )
                else:
                    interp = (
                        f"Regija {row['region_name']} ima ta dan vrednost "
                        f"{p_short} za {pct:.0f}% nižjo od svojega povprečja tega "
                        f"meseca ({value_mean:.{decimals}f} v primerjavi z "
                        f"{baseline:.{decimals}f} {unit})."
                    )

        # Build the value-line element
        value_label = ("Odstopanje od povprečja meseca"
                       if mode == "anomaly"
                       else f"Izmerjena vrednost {p_short} ta dan")
        if pd.isna(value_display):
            value_node = ui.div(
                "Ni podatka",
                class_="value-line",
                style="color: var(--text-3);",
            )
        else:
            shown = (f"{value_display:+.{decimals}f}"
                     if mode == "anomaly"
                     else f"{value_display:.{decimals}f}")
            value_node = ui.div(
                shown,
                ui.span(unit, class_="unit"),
                class_="value-line",
            )

        return ui.div(
            ui.div(
                row["region_name"],
                ui.span(row["region_code"], class_="region-code"),
                class_="region-name",
            ),
            ui.div(
                ui.div(value_label, class_="measurement-label"),
                value_node,
                class_="measurement",
            ),
            ui.span(
                ui.span(class_="dot"),
                quality_label_slo,
                class_=quality_cls,
            ),
            ui.div(interp, class_="interp") if interp else "",
            ui.div(
                ui.div(
                    ui.div("Najnižja meritev", class_="k"),
                    ui.div(_fmt_value(row.get("value_min")), class_="v"),
                    class_="stat-cell",
                ),
                ui.div(
                    ui.div("Najvišja meritev", class_="k"),
                    ui.div(_fmt_value(row.get("value_max")), class_="v"),
                    class_="stat-cell",
                ),
                ui.div(
                    ui.div("Št. vzorcev", class_="k"),
                    ui.div(_fmt_value(row.get("sample_count")), class_="v"),
                    class_="stat-cell",
                ),
                class_="stat-row",
            ),
            ui.div(rank_text, class_="rank") if rank_text else "",
        )

    # -------- TREND CHART --------------------------------------------------

    # The trend figure is precomputed at module import for every
    # (event, pollutant, region, mode) combination, so each user click is a
    # dict lookup with no pandas/Plotly work. The slider's selected-day
    # vertical line is pushed via the `trend_day_marker` custom message
    # (see effect below) and rendered client-side with Plotly.relayout —
    # so dragging the slider never re-ships the whole chart.
    @reactive.calc
    @reactive.event(input.event_id,
                    input.pollutant,
                    input.display_mode,
                    input.region_code)
    def trend_figure_cached():
        block = pollutant_block()
        figs = block.get("trend_figures") or {}
        region = input.region_code() if "region_code" in input else ""
        mode = input.display_mode() if "display_mode" in input else "absolute"
        fig = figs.get((region, mode))
        if fig is None:
            fig = figs.get(("", mode))
        return fig if fig is not None else _empty_trend_figure()

    @output
    @render_widget
    def trend_plot():
        return trend_figure_cached()

    @reactive.effect
    async def _push_trend_day_marker():
        # Re-fires when the day slider, the event, the pollutant, the
        # display mode or the region changes. Ships only the current
        # day's x coordinate — the JS handler does a Plotly.relayout to
        # add/replace a single dotted line.
        _ = input.event_id()
        if "pollutant" in input:
            input.pollutant()
        if "display_mode" in input:
            input.display_mode()
        if "region_code" in input:
            input.region_code()
        day = input.day_index() or 1

        block = pollutant_block()
        marker_values = block.get("trend_marker_values") or {}
        date = marker_values.get(int(day))
        try:
            await session.send_custom_message(
                "trend_day_marker", {"date": date}
            )
        except Exception:
            # Session can be torn down mid-animation; swallow gracefully.
            pass

    # -------- EVENT IMPACT PANEL ------------------------------------------

    @output
    @render.ui
    def impact_panel():
        ev = selected_event()
        df = event_df()
        region_code = input.region_code() if "region_code" in input else ""
        spec = pollutant_spec()
        unit = spec.get("display_unit", NO2_UNIT)
        p_short = spec.get("short", "NO₂")
        decimals = int(spec.get("decimals", 1))

        def _note() -> ui.Tag:
            return ui.div(ASSOCIATION_NOTE_SLO, class_="aw-impact-note")

        if not ev:
            return ui.div(
                ui.div(
                    "Izberi primer zgoraj, da prikažeš primerjavo pred / med / po dogodku.",
                    class_="aw-impact-msg",
                ),
                _note(),
                class_="aw-impact",
            )

        impact = _compute_event_impact(df, ev, region_code)
        status = impact.get("status")
        scope = impact.get("scope_label", "Slovenija")

        # Header: scope (region or Slovenija) + window summary
        header = ui.div(
            ui.div(
                ui.span("OBSEG", class_="aw-impact-k"),
                ui.span(
                    "Slovenija (povprečje regij)" if scope == "Slovenija"
                    else scope,
                    class_="aw-impact-v",
                ),
                class_="aw-impact-row",
            ),
            ui.div(
                ui.span("DOGODEK", class_="aw-impact-k"),
                ui.span(_slovene_window(ev) or "—", class_="aw-impact-v"),
                class_="aw-impact-row",
            ),
            ui.div(
                ui.span("ONESNAŽEVALO", class_="aw-impact-k"),
                ui.span(
                    f"{spec.get('name_slo', p_short)} ({p_short}) · {unit}",
                    class_="aw-impact-v",
                ),
                class_="aw-impact-row",
            ),
            class_="aw-impact-header",
        )

        if status == "no_event":
            return ui.div(
                header,
                ui.div(
                    "Za ta primer ni določenega obdobja dogodka, zato "
                    "primerjava pred / med / po ni mogoča.",
                    class_="aw-impact-msg",
                ),
                _note(),
                class_="aw-impact",
            )

        if status == "full_month":
            return ui.div(
                header,
                ui.div(
                    "Ta primer je industrijska študija za celoten mesec, "
                    "zato primerjava pred/med/po ni uporabljena.",
                    class_="aw-impact-msg aw-impact-msg-info",
                ),
                _note(),
                class_="aw-impact",
            )

        if status == "no_data":
            return ui.div(
                header,
                ui.div(
                    "Za izbrano kombinacijo onesnaževala in regije ni "
                    "razpoložljivih meritev v obdobju primera.",
                    class_="aw-impact-msg",
                ),
                _note(),
                class_="aw-impact",
            )

        def _fmt_val(v: float | None) -> ui.Tag:
            if v is None or pd.isna(v):
                return ui.span("ni podatka", class_="aw-impact-na")
            return ui.span(
                f"{v:.{decimals}f}",
                ui.span(unit, class_="aw-impact-unit"),
                class_="aw-impact-num",
            )

        def _fmt_pct(p: float | None) -> ui.Tag:
            if p is None or pd.isna(p):
                return ui.span("ni primerjave", class_="aw-impact-na")
            sign = "+" if p > 0 else ("" if p == 0 else "")
            cls = (
                "aw-impact-pct up" if p > 0
                else ("aw-impact-pct down" if p < 0 else "aw-impact-pct flat")
            )
            return ui.span(f"{sign}{p:.1f}%", class_=cls)

        n_b = impact.get("n_before", 0)
        n_d = impact.get("n_during", 0)
        n_a = impact.get("n_after", 0)

        cells = ui.div(
            ui.div(
                ui.div("Pred dogodkom", class_="aw-impact-cell-label"),
                ui.div(_fmt_val(impact.get("mean_before")),
                       class_="aw-impact-cell-value"),
                ui.div(f"{n_b} dnevnih meritev", class_="aw-impact-cell-sub"),
                class_="aw-impact-cell",
            ),
            ui.div(
                ui.div("Med dogodkom", class_="aw-impact-cell-label"),
                ui.div(_fmt_val(impact.get("mean_during")),
                       class_="aw-impact-cell-value"),
                ui.div(f"{n_d} dnevnih meritev", class_="aw-impact-cell-sub"),
                class_="aw-impact-cell aw-impact-cell-during",
            ),
            ui.div(
                ui.div("Po dogodku", class_="aw-impact-cell-label"),
                ui.div(_fmt_val(impact.get("mean_after")),
                       class_="aw-impact-cell-value"),
                ui.div(f"{n_a} dnevnih meritev", class_="aw-impact-cell-sub"),
                class_="aw-impact-cell",
            ),
            class_="aw-impact-grid",
        )

        deltas_rows = []
        if impact.get("mean_before") is None:
            deltas_rows.append(ui.div(
                ui.span("Sprememba med vs. pred", class_="aw-impact-delta-k"),
                ui.span(
                    "Pred dogodkom ni razpoložljivih meritev — primerjava ni mogoča.",
                    class_="aw-impact-delta-msg",
                ),
                class_="aw-impact-delta-row",
            ))
        else:
            deltas_rows.append(ui.div(
                ui.span("Sprememba med vs. pred", class_="aw-impact-delta-k"),
                _fmt_pct(impact.get("change_during_vs_before_pct")),
                class_="aw-impact-delta-row",
            ))
            if impact.get("mean_after") is None:
                deltas_rows.append(ui.div(
                    ui.span("Sprememba po vs. pred",
                            class_="aw-impact-delta-k"),
                    ui.span(
                        "Po dogodku ni razpoložljivih meritev — primerjava ni mogoča.",
                        class_="aw-impact-delta-msg",
                    ),
                    class_="aw-impact-delta-row",
                ))
            else:
                deltas_rows.append(ui.div(
                    ui.span("Sprememba po vs. pred",
                            class_="aw-impact-delta-k"),
                    _fmt_pct(impact.get("change_after_vs_before_pct")),
                    class_="aw-impact-delta-row",
                ))

        deltas = ui.div(*deltas_rows, class_="aw-impact-deltas")

        return ui.div(
            header,
            cells,
            deltas,
            _note(),
            class_="aw-impact",
        )

    # -------- SPATIAL INTERPRETATION PANEL --------------------------------

    @output
    @render.ui
    def spatial_panel():
        ev = selected_event()
        if not ev:
            return ui.div(
                ui.div(
                    "Izberi primer zgoraj, da prikažeš prostorsko "
                    "interpretacijo.",
                    class_="aw-spatial-msg",
                ),
                class_="aw-spatial",
            )

        eid = str(ev.get("event_id") or "")
        copy = _event_copy(ev)
        narrative = SPATIAL_INTERPRETATION_SLO.get(eid)

        # Header line
        loc_name = ev.get("event_location_name") or "—"
        header = ui.div(
            ui.div(
                ui.span("PRIMER", class_="aw-spatial-k"),
                ui.span(copy["title"], class_="aw-spatial-v"),
                class_="aw-spatial-row",
            ),
            ui.div(
                ui.span("LOKACIJA", class_="aw-spatial-k"),
                ui.span(loc_name, class_="aw-spatial-v"),
                class_="aw-spatial-row",
            ),
            class_="aw-spatial-header",
        )

        if not narrative:
            return ui.div(
                header,
                ui.div(
                    "Za ta primer nimamo zapisane prostorske interpretacije.",
                    class_="aw-spatial-msg",
                ),
                class_="aw-spatial",
            )

        headline = ui.div(narrative["headline"], class_="aw-spatial-headline")
        paragraphs = ui.div(
            *[ui.tags.p(p, class_="aw-spatial-paragraph")
              for p in narrative.get("paragraphs", [])],
            class_="aw-spatial-body",
        )

        # Layers list — use availability flags computed at import.
        layer_rows: list[ui.Tag] = []
        for key in narrative.get("relevant_layers", []):
            meta = CONTEXT_LAYER_META.get(key)
            if not meta:
                continue
            available = _CONTEXT_LAYER_AVAILABLE.get(key, False)
            status_label = (
                _resolved_layer_source(key) if available else "Sloj ni naložen"
            )
            status_cls = (
                "aw-spatial-layer-status"
                if available
                else "aw-spatial-layer-status missing"
            )
            row_cls = (
                "aw-spatial-layer"
                if available
                else "aw-spatial-layer disabled"
            )
            layer_rows.append(ui.div(
                ui.span(meta["label"], class_="aw-spatial-layer-label"),
                ui.span(status_label, class_=status_cls),
                class_=row_cls,
            ))

        layers_block = (
            ui.div(
                ui.div("Razpoložljivi prostorski sloji",
                       class_="aw-spatial-layers-title"),
                ui.div(*layer_rows, class_="aw-spatial-layers-list"),
                class_="aw-spatial-layers",
            )
            if layer_rows
            else ui.div()
        )

        return ui.div(
            header,
            headline,
            paragraphs,
            layers_block,
            ui.div(ASSOCIATION_NOTE_SLO, class_="aw-spatial-note"),
            class_="aw-spatial",
        )

    # -------- METHODOLOGY + EVENT META -------------------------------------

    @output
    @render.ui
    def methodology_block():
        items = [
            (
                "Kaj merimo",
                "Satelit Sentinel-5P meri količino dušikovega dioksida (NO₂) "
                "v stolpcu zraka nad Slovenijo. To ni meritev neposredno pri "
                "tleh, ampak v celotnem ozračju.",
            ),
            (
                "Kaj pomeni višja vrednost",
                "Običajno onesnaženje iz prometa, požarov ali industrije. "
                "Visoka številka ni sama po sebi dokaz vzroka — lahko jo "
                "razloži tudi vreme ali običajno ozadje.",
            ),
            (
                "Kdaj manjkajo podatki",
                "Kadar so oblaki pregosti ali satelit ni opravil zanesljive "
                "meritve. Prostorska ločljivost je približno 5,5 × 3,5 km.",
            ),
            (
                "Kako preveriti zaznavo",
                "Za potrditev so potrebne meritve na tleh (ARSO) in "
                "vremenski podatki.",
            ),
            (
                "Prostorski kontekst (GeoSlovenija / eProstor)",
                "Prostorski sloji dodajo kontekst urbanega, prometnega, "
                "industrijskega ali poseljenega prostora. Ne dokazujejo "
                "vzročnosti, ampak pomagajo interpretirati satelitski signal. "
                "Viri: eProstor (občine, prometna infrastruktura) in "
                "GeoSlovenija geo-peskovnik (industrijska in poslovna območja).",
            ),
        ]
        return ui.div(
            *[
                ui.div(
                    ui.span(f"{i + 1}", class_="icon"),
                    ui.div(
                        ui.div(head, class_="head"),
                        ui.div(desc, class_="desc"),
                        class_="body",
                    ),
                    class_="aw-method-item",
                )
                for i, (head, desc) in enumerate(items)
            ],
            class_="aw-method-list",
        )

    @output
    @render.ui
    def event_metadata_summary():
        ev = selected_event()
        meta = metadata() or {}
        if not ev and not meta:
            return ui.div()
        rows: list[ui.Tag] = []
        if ev:
            rows.append(ui.div(
                ui.span("Primer", class_="k"),
                ui.span(_event_copy(ev)["title"], class_="v"),
                class_="row",
            ))
            rows.append(ui.div(
                ui.span("Lokacija", class_="k"),
                ui.span(ev.get("event_location_name", "—"), class_="v"),
                class_="row",
            ))
            rows.append(ui.div(
                ui.span("Mesec analize", class_="k"),
                ui.span(_slovene_month_label(ev), class_="v"),
                class_="row",
            ))
            rows.append(ui.div(
                ui.span("Obdobje dogodka", class_="k"),
                ui.span(_slovene_window(ev) or "—", class_="v"),
                class_="row",
            ))
        rows.append(ui.div(
            ui.span("Vir podatkov", class_="k"),
            ui.span(meta.get("source",
                             "Sentinel Hub Statistical API / Sentinel-5P"),
                    class_="v"),
            class_="row",
        ))
        if meta.get("generated_at"):
            rows.append(ui.div(
                ui.span("Zadnja osvežitev", class_="k"),
                ui.span(meta["generated_at"], class_="v"),
                class_="row",
            ))
        return ui.div(*rows, class_="aw-event-summary")

    # -------- STATUS FOOTER (plain-language summary line) -----------------

    @output
    @render.ui
    def mission_log():
        df_disp = day_df_display().dropna(subset=["value_display"])
        ev = selected_event()
        day = input.day_index() or 1
        total = max_day_index()
        date_str = current_date_str()
        slo_date = _slovene_date(date_str) if date_str else "—"
        status_label, _ = _classify_day_status(ev, date_str)
        copy = _event_copy(ev) if ev else {"title": "—"}

        unit = current_unit()
        p_short = pollutant_spec()["short"]
        decimals = pollutant_spec().get("decimals", 1)

        # Build a natural-language summary
        if df_disp.empty:
            return ui.tags.span(
                "Prikazujem ", ui.tags.strong(slo_date), " — primer ",
                ui.tags.strong(copy["title"]),
                f". Za ta dan ni zanesljivih meritev za {p_short}.",
            )

        peak_row = df_disp.loc[df_disp["value_display"].idxmax()]
        mode = input.display_mode() if "display_mode" in input else "absolute"
        if mode == "anomaly":
            peak_text = (
                f"Največje odstopanje od povprečja: "
                f"{float(peak_row['value_display']):+.{decimals}f} {unit} "
                f"v regiji {peak_row['region_name']}."
            )
        else:
            peak_text = (
                f"Najvišja izmerjena vrednost {p_short}: "
                f"{float(peak_row['value_display']):.{decimals}f} {unit} "
                f"v regiji {peak_row['region_name']}."
            )
        status_suffix = f" ({status_label.lower()})" if status_label != "—" else ""
        _ = (day, total)  # day/total prefix reserved for future
        return ui.tags.span(
            "Prikazujem ", ui.tags.strong(slo_date), " — primer ",
            ui.tags.strong(copy["title"]),
            status_suffix, ". ", peak_text,
        )

    # -------- STATUS BANNER -----------------------------------------------

    @output
    @render.ui
    def status_banner():
        df = data()
        meta = metadata()
        banners = []
        if df.empty:
            banners.append(ui.div(
                "Datoteka event_no2_nuts3_daily.csv ni najdena. "
                "Najprej zaženi Sentinel Hub pipeline ali generiraj vzorčne podatke.",
                class_="alert",
            ))
        if not meta:
            banners.append(ui.div(
                "Datoteka z metapodatki ni najdena.",
                class_="alert",
            ))
        if not _REGIONS_GEOJSON.get("features"):
            banners.append(ui.div(
                "GeoJSON regij ni najden — zemljevid bo prazen.",
                class_="alert",
            ))
        return ui.div(*banners) if banners else ui.div()


# ---------------------------------------------------------------------------
# App entry
# ---------------------------------------------------------------------------


app = App(app_ui, server, static_assets=str(Path(__file__).resolve().parent / "www"))


if __name__ == "__main__":
    from shiny import run_app
    run_app("app:app", app_dir=str(Path(__file__).resolve().parent))
