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

# Sequential color scale for absolute NO₂ values — calm but informative.
# Goes from dark teal (low) through warm amber to muted red (high).
NO2_COLORSCALE = [
    [0.00, "#1e4d40"],   # dark teal — clean
    [0.25, "#4ba87f"],   # sea-foam — low
    [0.55, "#e6b052"],   # amber — moderate
    [0.80, "#e6824c"],   # orange — elevated
    [1.00, "#d96a72"],   # muted red — high
]

# Diverging color scale for anomaly mode (negative ↔ positive vs month mean).
ANOMALY_COLORSCALE = [
    [0.00, "#4ba87f"],   # cleaner than usual
    [0.45, "#2a3540"],
    [0.55, "#2a3540"],   # neutral band
    [1.00, "#d96a72"],   # elevated above usual
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


def _resolve_events_list() -> list[dict]:
    """Return the canonical list of event metadata dicts (metadata > fallback)."""
    events = (_INITIAL_METADATA or {}).get("events") or []
    if events:
        return list(events)
    return list(_EVENTS_FALLBACK)


_EVENTS_LIST = _resolve_events_list()


def _compute_event_window(event: dict, max_day: int) -> dict | None:
    """Return {start_pct, width_pct, label} for the timeline overlay."""
    if not event or max_day <= 1:
        return None
    es_raw = event.get("event_start")
    ee_raw = event.get("event_end")
    if not es_raw or not ee_raw:
        return None
    try:
        es_day = pd.to_datetime(es_raw).day
        ee_day = pd.to_datetime(ee_raw).day
    except (ValueError, TypeError):
        return None
    denom = max(max_day - 1, 1)
    start_pct = max(0.0, (es_day - 1) / denom * 100.0)
    end_pct = min(100.0, (ee_day - 1) / denom * 100.0)
    width_pct = max(end_pct - start_pct, 1.6)
    label = "EVENT" if es_raw == ee_raw else "EVENT WINDOW"
    return {"start_pct": start_pct, "width_pct": width_pct, "label": label}


def _empty_trend_figure() -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=360,
        margin=dict(l=40, r=20, t=30, b=40),
        annotations=[dict(
            text="Ni razpoložljivih podatkov.",
            x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
            font=dict(family="DM Sans, system-ui, sans-serif",
                      color="#b7c3cc", size=14),
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
        fill="tonexty", fillcolor="rgba(108,200,176,0.12)",
        name="min–max", hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=sub["date"], y=sub["plot_value"],
        mode="lines+markers",
        line=dict(color="#6cc8b0", width=2.4,
                  shape="spline", smoothing=0.5),
        marker=dict(size=5, color="#6cc8b0",
                    line=dict(color="#0f141a", width=1)),
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
                    line=dict(color="#e6824c", width=2),
                )
                fig.add_annotation(
                    x=es, y=1, yref="paper", showarrow=False,
                    text="Dan dogodka", yanchor="bottom",
                    font=dict(family="Manrope, system-ui, sans-serif",
                              color="#e6824c", size=11),
                )
            else:
                fig.add_vrect(
                    x0=es, x1=ee,
                    fillcolor="rgba(230,130,76,0.12)",
                    line=dict(width=0),
                )
                fig.add_annotation(
                    x=es, y=1, yref="paper", showarrow=False,
                    text="Obdobje dogodka", yanchor="bottom",
                    xanchor="left",
                    font=dict(family="Manrope, system-ui, sans-serif",
                              color="#e6824c", size=11),
                )

    # Count baseline shapes so the JS day-marker handler knows where to
    # slice when replacing the per-day vertical line.
    base_shape_count = len(fig.layout.shapes or [])

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(28,37,48,0.45)",
        title=dict(
            text=title,
            font=dict(family="Manrope, system-ui, sans-serif",
                      color="#ebf0f3", size=14),
            x=0.01, y=0.96,
        ),
        xaxis=dict(
            title=None,
            gridcolor="rgba(255,255,255,0.05)",
            zerolinecolor="rgba(255,255,255,0.12)",
            linecolor="rgba(255,255,255,0.12)",
            tickfont=dict(family="DM Sans, system-ui, sans-serif",
                          color="#b7c3cc", size=11),
            showline=True,
            tickangle=-45,
        ),
        yaxis=dict(
            title=dict(text=y_title,
                       font=dict(family="DM Sans, system-ui, sans-serif",
                                 color="#b7c3cc", size=11)),
            gridcolor="rgba(255,255,255,0.05)",
            zerolinecolor="rgba(255,255,255,0.12)",
            linecolor="rgba(80,200,165,0.25)",
            tickfont=dict(family="JetBrains Mono, monospace",
                          color="#95aaa3", size=10),
            showline=True,
        ),
        font=dict(family="DM Sans, system-ui, sans-serif", color="#b7c3cc"),
        height=360,
        margin=dict(l=60, r=20, t=50, b=70),
        hoverlabel=dict(
            bgcolor="rgba(22,29,37,0.96)",
            bordercolor="rgba(108,200,176,0.40)",
            font=dict(family="DM Sans, system-ui, sans-serif",
                      color="#ebf0f3", size=12),
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


def _event_card_label(event: dict) -> ui.Tag:
    """Render a single case-study card used as the label of a radio input.

    The radio input itself is hidden by CSS; clicking anywhere on this card
    selects the event.
    """
    copy = _event_copy(event)
    when = _slovene_window(event)
    where = event.get("event_location_name") or ""
    # Trim "long location" for readability — keep up to the first comma.
    where_short = where.split(",")[0] if where else ""

    return ui.tags.span(
        ui.div(
            ui.div(
                ui.span(copy["type"], class_="type-tag"),
                ui.span("✓ Izbrano", class_="selected-indicator"),
                class_="type-row",
            ),
            ui.div(copy["title"], class_="ev-title"),
            ui.div(copy["desc"], class_="ev-desc"),
            ui.div(
                ui.div(when, class_="when") if when else "",
                ui.div(where_short, class_="where") if where_short else "",
                class_="ev-foot",
            ),
            class_="aw-event-card",
        )
    )


def _build_event_choices() -> dict[str, ui.Tag]:
    """Return {event_id: ui.Tag} for the mission-card radio group."""
    choices: dict[str, ui.Tag] = {}
    for event in _EVENTS_LIST:
        eid = event.get("event_id")
        if not eid:
            continue
        choices[eid] = _event_card_label(event)
    return choices


_EVENT_CHOICES = _build_event_choices()
_DEFAULT_EVENT_ID = next(iter(_EVENT_CHOICES), None)


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


app_ui = ui.page_fluid(
    # ----- HEAD: humanist Google Fonts, custom CSS, custom JS --------------
    ui.head_content(
        ui.tags.meta(charset="utf-8"),
        ui.tags.meta(
            name="viewport",
            content="width=device-width, initial-scale=1",
        ),
        ui.tags.title("AirWatch GeoSlovenija — kakovost zraka iz satelita"),
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
                "family=Manrope:wght@400;500;600;700&"
                "family=DM+Sans:wght@400;500;600;700&"
                "family=JetBrains+Mono:wght@400;500;600&display=swap"
            ),
        ),
        ui.tags.link(rel="stylesheet", href="styles.css"),
        ui.tags.script(src="app.js", defer="defer"),
    ),

    # ----- APP SHELL -------------------------------------------------------
    ui.div(

        # ===== 1. HEADER ==================================================
        ui.div(
            ui.div(
                ui.tags.h1(
                    "AirWatch ",
                    ui.span("GeoSlovenija", class_="accent"),
                ),
                ui.tags.p(
                    "Spremljanje onesnaženosti zraka nad Slovenijo s satelitskimi "
                    "meritvami. Izberi enega od primerov spodaj in se pomikaj po "
                    "dnevih, da vidiš, kako se je spreminjala koncentracija.",
                    class_="subtitle",
                ),
                class_="aw-hero-text",
            ),
            ui.div(
                ui.output_ui("hero_status_badge"),
                ui.span(
                    ui.span(class_="dot"),
                    "Vir: Sentinel-5P (ESA Copernicus)",
                    class_="aw-badge signal",
                ),
                ui.span(
                    ui.span(class_="dot"),
                    "Onesnaževalo: NO₂",
                    class_="aw-badge no2",
                ),
                ui.span(
                    ui.span(class_="dot"),
                    "Dnevne meritve",
                    class_="aw-badge cadence",
                ),
                class_="aw-hero-badges",
            ),
            class_="aw-hero",
        ),

        # ===== 2. CASE-STUDY SELECTOR =====================================
        ui.div(
            ui.div(
                ui.div("1. korak", class_="aw-section-label"),
                ui.h2("Izberi primer za prikaz", class_="aw-section-title"),
                ui.div(
                    "Vsak primer prikazuje meritve satelita Sentinel-5P "
                    "za en mesec, ki vsebuje pomemben dogodek.",
                    class_="aw-section-hint",
                ),
            ),
            ui.div(
                ui.input_radio_buttons(
                    "event_id",
                    None,
                    choices=_EVENT_CHOICES or {"": "Ni dogodkov"},
                    selected=_DEFAULT_EVENT_ID,
                    inline=True,
                ),
                class_="aw-events-wrap",
            ),
            class_="aw-events-section",
        ),

        # ===== 2.5. POLLUTANT SELECTOR ====================================
        ui.div(
            ui.div(
                ui.div("Onesnaževalo za prikaz", class_="aw-card-title"),
                ui.div(
                    ui.output_text("pollutant_subtitle", inline=True),
                    class_="aw-card-subtitle",
                ),
                ui.div(
                    ui.input_radio_buttons(
                        "pollutant",
                        None,
                        choices={"NO2": _pollutant_choice_label("NO2")},
                        selected="NO2",
                        inline=True,
                    ),
                    class_="aw-pollutant-toggle",
                ),
                class_="aw-card",
            ),
            class_="aw-pollutant-section",
        ),

        # ===== 3. TIMELINE ================================================
        ui.div(
            ui.div(
                ui.div(
                    ui.div("Povleci ali predvajaj animacijo skozi mesec",
                           class_="label"),
                    ui.div(
                        ui.tags.button(
                            ui.tags.span(class_="play-icon"),
                            ui.tags.span("Predvajaj", class_="play-label"),
                            id="aw-play-toggle",
                            type="button",
                            class_="aw-play-btn",
                            **{"aria-label": "Predvajaj animacijo skozi mesec"},
                        ),
                        ui.div(
                            ui.output_text("selected_date_display", inline=True),
                            class_="current-date",
                        ),
                        class_="aw-timeline-current",
                    ),
                ),
                ui.div(
                    ui.output_ui("day_counter_display", inline=True),
                    class_="day-counter",
                ),
                class_="aw-timeline-header",
            ),
            ui.div(
                # event-window overlay is positioned absolutely over the slider
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
                class_="aw-slider-stage",
            ),
            ui.div(
                ui.span("← Pred dogodkom"),
                ui.span("Med dogodkom", class_="mid"),
                ui.span("Po dogodku →"),
                class_="aw-timeline-labels",
            ),
            class_="aw-timeline-wrap",
        ),

        # ===== 4. MAIN GRID: map + side panels ============================
        ui.div(
            # --- Map column ---
            ui.div(
                ui.div(
                    ui.div(
                        ui.div(
                            ui.output_text("map_title", inline=True),
                            class_="title",
                        ),
                        ui.div(
                            ui.output_text("map_subtitle", inline=True),
                            class_="sub",
                        ),
                        class_="left",
                    ),
                    ui.div(
                        ui.span(
                            ui.output_text("map_mode_label", inline=True),
                            class_="mode-pill",
                        ),
                        class_="right",
                    ),
                    class_="aw-map-toolbar",
                ),
                ui.div(
                    # Friendly help bubble — explains what the user is looking at
                    ui.div(
                        ui.span("i", class_="icon"),
                        ui.span(
                            "Bolj rdeča regija = višja koncentracija NO₂ tisti dan. "
                            "Sivkasto pomeni, da satelit ni izmeril zanesljivih podatkov.",
                        ),
                        class_="aw-map-help",
                    ),
                    # legend
                    ui.div(
                        ui.div("Koncentracija NO₂ v ozračju",
                               class_="legend-title"),
                        ui.div("nižja → višja", class_="legend-sub"),
                        ui.span(class_="ramp"),
                        ui.div(
                            ui.span("manj"),
                            ui.span("srednje"),
                            ui.span("več"),
                            class_="ramp-labels",
                        ),
                        class_="aw-map-overlay",
                    ),
                    output_widget("map_plot"),
                    class_="aw-map-wrap",
                ),
                class_="aw-map-card",
            ),

            # --- Side column ---
            ui.div(
                # Summary stats
                ui.div(
                    ui.div("Pregled za izbrani dan", class_="aw-card-title"),
                    ui.div(
                        "Hitre številke za vse slovenske statistične regije.",
                        class_="aw-card-subtitle",
                    ),
                    ui.div(
                        _stat_cell("t_slovenia_avg",
                                   "Povprečje Slovenije",
                                   large=True),
                        _stat_cell("t_highest",
                                   "Najbolj onesnažena regija",
                                   modifier="alert"),
                        _stat_cell("t_lowest",
                                   "Najmanj onesnažena regija",
                                   modifier="cool"),
                        _stat_cell("t_valid",
                                   "Regije s podatki"),
                        _stat_cell("t_quality",
                                   "Kakovost meritev",
                                   modifier="warn"),
                        class_="aw-summary-grid",
                    ),
                    class_="aw-card",
                ),
                # Region focus
                ui.div(
                    ui.div("Podrobnosti regije", class_="aw-card-title"),
                    ui.div(
                        "Izberi regijo, da vidiš njeno vrednost in primerjavo "
                        "s povprečjem meseca.",
                        class_="aw-card-subtitle",
                    ),
                    ui.input_select(
                        "region_code",
                        None,
                        choices={"": "Vse regije (povprečje Slovenije)"},
                        selected="",
                    ),
                    ui.output_ui("region_detail"),
                    class_="aw-card aw-region-detail",
                ),
                # Display mode toggle
                ui.div(
                    ui.div("Način prikaza", class_="aw-card-title"),
                    ui.div(
                        "Preklopi med dejansko izmerjenimi vrednostmi in "
                        "odstopanjem od povprečja tega meseca.",
                        class_="aw-card-subtitle",
                    ),
                    ui.div(
                        ui.input_radio_buttons(
                            "display_mode",
                            None,
                            choices={
                                "absolute": ui.tags.span("Dejanske vrednosti"),
                                "anomaly":  ui.tags.span("Odstopanje od povprečja"),
                            },
                            selected="absolute",
                            inline=True,
                        ),
                        class_="aw-mode-toggle",
                    ),
                    class_="aw-card",
                ),
                class_="aw-side",
            ),
            class_="aw-main-grid",
        ),

        # ===== 5. TREND CHART =============================================
        ui.div(
            ui.div("Trend skozi mesec", class_="aw-card-title"),
            ui.div(
                "Senčen pas prikazuje razpon med najnižjo in najvišjo "
                "dnevno meritvijo. Oranžno označen je čas dogodka.",
                class_="aw-card-subtitle",
            ),
            ui.div(
                output_widget("trend_plot"),
                class_="aw-trend-wrap",
            ),
            class_="aw-card",
        ),

        # ===== 6. BOTTOM: methodology + quality legend ====================
        ui.div(
            ui.div(
                ui.div("Kaj prikazuje ta nadzorna plošča",
                       class_="aw-card-title"),
                ui.div(
                    "Preberi pred razlago — pomaga razumeti, kaj številke "
                    "pomenijo in kaj ne.",
                    class_="aw-card-subtitle",
                ),
                ui.output_ui("methodology_block"),
                class_="aw-card",
            ),
            ui.div(
                ui.div("Kakovost meritve", class_="aw-card-title"),
                ui.div(
                    "Satelit ne izmeri vsakega dne enako zanesljivo — oblaki "
                    "in kotni pregled lahko meritev poslabšajo.",
                    class_="aw-card-subtitle",
                ),
                ui.div(
                    ui.div(
                        ui.span(class_="indicator"),
                        ui.div(
                            ui.div("Dobra meritev", class_="name"),
                            ui.div("Podatkom lahko zaupaš.",
                                   class_="desc"),
                        ),
                        class_="aw-quality-item good",
                    ),
                    ui.div(
                        ui.span(class_="indicator"),
                        ui.div(
                            ui.div("Delna meritev", class_="name"),
                            ui.div(
                                "Del območja ni bil pokrit ali je bila "
                                "kakovost slabša.",
                                class_="desc",
                            ),
                        ),
                        class_="aw-quality-item partial",
                    ),
                    ui.div(
                        ui.span(class_="indicator"),
                        ui.div(
                            ui.div("Ni podatkov", class_="name"),
                            ui.div(
                                "Satelit tisti dan nad regijo ni opravil "
                                "zanesljive meritve.",
                                class_="desc",
                            ),
                        ),
                        class_="aw-quality-item missing",
                    ),
                    class_="aw-quality-legend",
                ),
                ui.output_ui("event_metadata_summary"),
                class_="aw-card",
            ),
            class_="aw-bottom-grid",
        ),

        # ===== 7. STATUS FOOTER (replaces mission log) ====================
        ui.div(
            ui.span("›", class_="icon"),
            ui.output_ui("mission_log", inline=True),
            class_="aw-status",
        ),

        # ===== STATUS BANNER (only shows if data missing) =================
        ui.output_ui("status_banner"),

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


def _map_restyle_payload(df_disp: pd.DataFrame) -> dict:
    """Build the JSON payload pushed to the client on each day tick.

    `df_disp` must already have a `value_display` column (set by the
    `day_df_display` reactive — value_mean in absolute mode, value_anomaly
    in anomaly mode). Returns {with_value: …, without_value: …} where each
    block carries the arrays needed by Plotly.restyle.
    """
    if df_disp.empty:
        return {
            "with_value": {"locations": [], "z": [], "customdata": []},
            "without_value": {"locations": [], "customdata": []},
        }
    wv = df_disp.dropna(subset=["value_display"])
    nv = df_disp[df_disp["value_display"].isna()]
    return {
        "with_value": {
            "locations": wv["region_code"].astype(str).tolist(),
            "z": wv["value_display"].astype(float).tolist(),
            "customdata": _map_value_customdata(wv),
        },
        "without_value": {
            "locations": nv["region_code"].astype(str).tolist(),
            "customdata": _map_no_data_customdata(nv),
        },
    }


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
        """Position a highlighted band over the slider track (precomputed)."""
        ew = event_cache_entry().get("event_window")
        if not ew:
            return ui.div()
        return ui.div(
            class_="aw-event-window-overlay",
            **{"data-label": ew["label"]},
            style=(
                # 0.985 + 0.8% offset compensates for ionRangeSlider handle padding
                f"left: calc({ew['start_pct']:.2f}% * 0.985 + 0.8%);"
                f" width: calc({ew['width_pct']:.2f}% * 0.985);"
            ),
        )

    # -------- MAP ----------------------------------------------------------

    @output
    @render.text
    def map_title():
        d = current_date_str()
        return f"Slovenija — {_slovene_date(d)}" if d else "Slovenija"

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
    def map_mode_label():
        mode = input.display_mode() if "display_mode" in input else "absolute"
        short = pollutant_spec()["short"]
        return ("Prikaz: odstopanje od povprečja"
                if mode == "anomaly"
                else f"Prikaz: dejanske vrednosti {short}")

    # The map figure is rebuilt only when event / pollutant / display_mode /
    # region_code change — NOT on every day tick. The current day's values are
    # pushed via a custom message (`map_restyle`) that the client applies with
    # Plotly.restyle, so the mapbox tiles and geojson stay mounted between
    # frames. Without this scoping the entire figure shipped over the
    # websocket on each tick and the browser tore down the choropleth.
    @reactive.calc
    @reactive.event(input.event_id,
                    input.pollutant,
                    input.display_mode,
                    input.region_code)
    def map_figure():
        with reactive.isolate():
            df_disp = day_df_display()
        block = pollutant_block()
        ev = selected_event()
        mode = input.display_mode() if "display_mode" in input else "absolute"
        selected_region = input.region_code() if "region_code" in input else ""
        fig = go.Figure()

        # Empty-state map
        if not _REGIONS_GEOJSON.get("features"):
            fig.update_layout(
                paper_bgcolor="#0a0e13",
                plot_bgcolor="#0a0e13",
                mapbox=dict(
                    style="carto-darkmatter",
                    center=dict(lat=46.15, lon=14.99),
                    zoom=6.6,
                ),
                margin=dict(l=0, r=0, t=0, b=0),
                height=580,
                showlegend=False,
            )
            fig.add_annotation(
                text="Ni razpoložljivih podatkov.",
                font=dict(color="#b7c3cc",
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
        # Always added (possibly empty) so the trace index stays stable for
        # client-side Plotly.restyle.
        fig.add_trace(
            go.Choroplethmapbox(
                geojson=_REGIONS_GEOJSON,
                locations=wv["region_code"].astype(str).tolist(),
                z=wv["value_display"].astype(float).tolist() if not wv.empty else [],
                featureidkey="properties.region_code",
                colorscale=cscale,
                zmin=zmin, zmax=zmax,
                marker=dict(
                    line=dict(color="rgba(255,255,255,0.18)", width=0.6),
                    opacity=0.85,
                ),
                customdata=_map_value_customdata(wv) if not wv.empty else [],
                hovertemplate=hovertemplate_val,
                colorbar=dict(
                    title=dict(
                        text=color_title,
                        font=dict(family="Manrope, system-ui, sans-serif",
                                  color="#b7c3cc", size=11),
                    ),
                    thickness=10,
                    len=0.55,
                    x=0.985,
                    y=0.45,
                    bgcolor="rgba(22,29,37,0.85)",
                    bordercolor="rgba(255,255,255,0.10)",
                    borderwidth=1,
                    tickfont=dict(family="JetBrains Mono, monospace",
                                  color="#b7c3cc", size=10),
                    outlinecolor="rgba(255,255,255,0.10)",
                    ticks="outside",
                ),
                name="",
                showscale=True,
                uirevision="map-keep-view",
            )
        )

        # ---- Trace 1: choropleth for regions WITHOUT data (always added)
        fig.add_trace(
            go.Choroplethmapbox(
                geojson=_REGIONS_GEOJSON,
                locations=nv["region_code"].astype(str).tolist(),
                z=[0.0] * len(nv),
                featureidkey="properties.region_code",
                colorscale=[[0, "rgba(60,72,82,0.55)"], [1, "rgba(60,72,82,0.55)"]],
                showscale=False,
                marker=dict(
                    line=dict(color="rgba(255,255,255,0.12)", width=0.5),
                    opacity=0.55,
                ),
                customdata=_map_no_data_customdata(nv) if not nv.empty else [],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "%{customdata[1]}<br>"
                    "Ni zanesljive satelitske meritve."
                    "<extra></extra>"
                ),
                name="",
                uirevision="map-keep-view",
            )
        )

        # ---- Layer 3: subtle highlight ring on selected region's centroid
        if selected_region and selected_region in _REGION_CENTROIDS:
            clat, clon = _REGION_CENTROIDS[selected_region]
            fig.add_trace(go.Scattermapbox(
                lat=[clat], lon=[clon],
                mode="markers",
                marker=dict(size=38, color="rgba(108,200,176,0.20)"),
                hoverinfo="skip", showlegend=False,
            ))
            fig.add_trace(go.Scattermapbox(
                lat=[clat], lon=[clon],
                mode="markers",
                marker=dict(size=14, color="#6cc8b0"),
                hoverinfo="skip", showlegend=False,
            ))

        # ---- Layer 4: event location marker — calm orange/red dot with halo
        if ev and ev.get("event_lat") is not None and ev.get("event_lon") is not None:
            elat = ev["event_lat"]; elon = ev["event_lon"]
            label = ev.get("event_location_name") or ev.get("event_name") or "Lokacija dogodka"
            copy = _event_copy(ev)
            # halo
            fig.add_trace(go.Scattermapbox(
                lat=[elat], lon=[elon],
                mode="markers",
                marker=dict(size=44, color="rgba(217,106,114,0.18)"),
                hoverinfo="skip", showlegend=False,
            ))
            # core marker
            fig.add_trace(go.Scattermapbox(
                lat=[elat], lon=[elon],
                mode="markers+text",
                marker=dict(size=14, color="#d96a72"),
                text=[copy["title"]],
                textposition="top right",
                textfont=dict(family="Manrope, system-ui, sans-serif",
                              color="#f3c4c8", size=12),
                hovertemplate=(
                    f"<b>{copy['title']}</b><br>{label}<extra></extra>"
                ),
                showlegend=False,
            ))

        # ---- Layout
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            mapbox=dict(
                style="carto-darkmatter",
                center=dict(lat=46.15, lon=14.99),
                zoom=6.6,
            ),
            margin=dict(l=0, r=0, t=0, b=0),
            height=560,
            showlegend=False,
            font=dict(family="DM Sans, system-ui, sans-serif", color="#b7c3cc"),
            hoverlabel=dict(
                bgcolor="rgba(22,29,37,0.96)",
                bordercolor="rgba(108,200,176,0.40)",
                font=dict(family="DM Sans, system-ui, sans-serif",
                          color="#ebf0f3", size=12),
            ),
            transition=dict(duration=320, easing="cubic-in-out"),
        )
        return fig

    @output
    @render_widget
    def map_plot():
        # The widget is bound to the slow-changing figure. Day-by-day data
        # arrives via the `map_restyle` custom message (see effect below).
        return map_figure()

    @reactive.effect
    async def _push_map_restyle():
        # Re-fires when the slider day, the event, the pollutant or the mode
        # changes. The full figure is rebuilt only on the latter three; this
        # effect ships only the day's z/locations/customdata.
        _ = input.event_id()
        if "pollutant" in input:
            input.pollutant()
        if "display_mode" in input:
            input.display_mode()
        _ = input.day_index()

        df = day_df_display()
        if df.empty:
            return
        payload = _map_restyle_payload(df)
        try:
            await session.send_custom_message("map_restyle", payload)
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
