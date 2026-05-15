#!/usr/bin/env python3
import json
import os
from pathlib import Path

import pandas as pd
import geopandas as gpd
from dash import Dash, html, dcc, Input, Output
import plotly.express as px
import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIMESERIES_CSV = PROJECT_ROOT / "outputs" / "timeseries" / "no2_nuts3_timeseries.csv"
REGIONS_GEOJSON = (
    PROJECT_ROOT / "reference_data" / "regions" / "processed"
    / "slovenia_nuts3_regions_2024_4326.geojson"
)

# Sentinel-5P returns mol/m² — display as µmol/m² for readability
NO2_SCALE = 1e6
NO2_UNIT = "µmol/m²"


def load_regions():
    gdf = gpd.read_file(REGIONS_GEOJSON)[["region_code", "region_name", "geometry"]].copy()
    geojson = json.loads(gdf.to_json())
    for feat in geojson["features"]:
        feat["id"] = feat["properties"]["region_code"]
    return gdf, geojson


def load_timeseries():
    if not TIMESERIES_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(TIMESERIES_CSV)
    df["date_from"] = pd.to_datetime(df["date_from"], utc=True)
    df["period"] = df["date_from"].dt.strftime("%Y-%m")
    for col in ("value_mean", "value_min", "value_max", "value_stdev"):
        df[col + "_µ"] = df[col] * NO2_SCALE
    return df


regions_gdf, regions_geojson = load_regions()
df = load_timeseries()
periods = sorted(df["period"].unique()) if not df.empty else []

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H3("NO2 — Slovenija NUTS3", className="mb-0"), width=8),
        dbc.Col(
            dcc.Dropdown(
                id="period",
                options=[{"label": p, "value": p} for p in periods],
                value=periods[-1] if periods else None,
                clearable=False,
                placeholder="Ni podatkov",
            ),
            width=4,
        ),
    ], className="my-3 align-items-center"),

    dbc.Row([
        dbc.Col(dcc.Graph(id="map", style={"height": "460px"}), width=8),
        dbc.Col([
            html.H5(id="stats_title", children="Klikni na regijo"),
            html.Hr(className="my-2"),
            html.Div(id="stats_panel", children=html.P("—", className="text-muted")),
        ], width=4, className="pt-2"),
    ]),

    dbc.Row([
        dbc.Col(dcc.Graph(id="trend"), width=12),
    ], className="mt-3"),

    dcc.Store(id="selected_region"),
], fluid=True)


@app.callback(
    Output("map", "figure"),
    Input("period", "value"),
)
def update_map(period):
    if not period or df.empty:
        return go.Figure().update_layout(
            mapbox_style="carto-positron",
            mapbox_center={"lat": 46.15, "lon": 14.99},
            mapbox_zoom=6.5,
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
        )

    filtered = df[df["period"] == period]
    merged = regions_gdf.merge(
        filtered[["region_code", "value_mean_µ", "value_min_µ", "value_max_µ", "quality_status"]],
        on="region_code",
        how="left",
    )

    color_max = df["value_mean_µ"].quantile(0.95) if not df.empty else 1

    fig = px.choropleth_mapbox(
        merged,
        geojson=regions_geojson,
        locations="region_code",
        color="value_mean_µ",
        hover_name="region_name",
        hover_data={
            "region_code": False,
            "value_mean_µ": ":.4f",
            "value_min_µ": ":.4f",
            "value_max_µ": ":.4f",
        },
        mapbox_style="carto-positron",
        center={"lat": 46.15, "lon": 14.99},
        zoom=6.5,
        color_continuous_scale="YlOrRd",
        range_color=[0, color_max],
        labels={
            "value_mean_µ": f"NO2 ({NO2_UNIT})",
            "value_min_µ": f"Min ({NO2_UNIT})",
            "value_max_µ": f"Max ({NO2_UNIT})",
        },
    )
    fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})
    return fig


@app.callback(
    Output("selected_region", "data"),
    Input("map", "clickData"),
)
def store_region(click_data):
    if not click_data:
        raise PreventUpdate
    return click_data["points"][0]["location"]


@app.callback(
    Output("stats_title", "children"),
    Output("stats_panel", "children"),
    Input("selected_region", "data"),
    Input("period", "value"),
)
def update_stats(region_code, period):
    if not region_code or not period or df.empty:
        return "Klikni na regijo", html.P("—", className="text-muted")

    row = df[(df["region_code"] == region_code) & (df["period"] == period)]
    if row.empty:
        return region_code, html.P("Ni podatkov za ta mesec.", className="text-muted")

    r = row.iloc[0]

    def stat(label, value):
        return dbc.Row([
            dbc.Col(html.Small(label, className="text-muted"), width=7),
            dbc.Col(html.Strong(value), width=5),
        ], className="mb-1")

    panel = html.Div([
        stat(f"Povprečje ({NO2_UNIT})", f"{r['value_mean_µ']:.4f}"),
        stat(f"Min ({NO2_UNIT})", f"{r['value_min_µ']:.4f}"),
        stat(f"Max ({NO2_UNIT})", f"{r['value_max_µ']:.4f}"),
        stat("Std. odklon", f"{r['value_stdev_µ']:.4f}"),
        stat("Vzorci", str(int(r["sample_count"])) if pd.notna(r.get("sample_count")) else "—"),
        stat("Kakovost", str(r.get("quality_status", "—"))),
        stat("Interval", str(r.get("aggregation_interval", "—"))),
    ])
    return r.get("region_name", region_code), panel


@app.callback(
    Output("trend", "figure"),
    Input("selected_region", "data"),
)
def update_trend(region_code):
    empty = go.Figure().update_layout(
        title="NO2 trend — klikni na regijo",
        xaxis_title="Mesec",
        yaxis_title=f"NO2 ({NO2_UNIT})",
    )
    if not region_code or df.empty:
        return empty

    region_df = df[df["region_code"] == region_code].sort_values("period")
    if region_df.empty:
        return empty

    name = region_df["region_name"].iloc[0]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pd.concat([region_df["period"], region_df["period"].iloc[::-1]]),
        y=pd.concat([region_df["value_max_µ"], region_df["value_min_µ"].iloc[::-1]]),
        fill="toself",
        fillcolor="rgba(224,92,0,0.12)",
        line=dict(color="rgba(0,0,0,0)"),
        showlegend=False,
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=region_df["period"],
        y=region_df["value_mean_µ"],
        mode="lines+markers",
        name="Povprečje NO2",
        line=dict(color="#e05c00", width=2),
        marker=dict(size=7),
    ))
    fig.update_layout(
        title=f"NO2 trend — {name}",
        xaxis_title="Mesec",
        yaxis_title=f"NO2 ({NO2_UNIT})",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


if __name__ == "__main__":
    app.run(
        host=os.getenv("DASH_HOST", "127.0.0.1"),
        port=int(os.getenv("DASH_PORT", "8050")),
    )
