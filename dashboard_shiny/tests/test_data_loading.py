"""Tests for the Shiny dashboard data loading helpers.

These tests load the data helpers from dashboard_shiny/app.py without
actually starting the Shiny app. The helpers themselves are pure
functions that read from disk.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DASHBOARD_DIR.parent

sys.path.insert(0, str(DASHBOARD_DIR))


def _load_app_module():
    pytest.importorskip("pandas")
    pytest.importorskip("shiny")
    pytest.importorskip("shinywidgets")
    pytest.importorskip("plotly")

    spec = importlib.util.spec_from_file_location("dashboard_shiny_app", DASHBOARD_DIR / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_load_event_csv_missing(tmp_path):
    module = _load_app_module()
    df = module.load_event_csv(tmp_path / "missing.csv")
    assert df.empty


def test_load_metadata_missing(tmp_path):
    module = _load_app_module()
    metadata = module.load_metadata(tmp_path / "missing.json")
    assert metadata == {}


def test_load_regions_geojson_assigns_id():
    module = _load_app_module()
    geojson = module.load_regions_geojson()
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 12
    for feature in geojson["features"]:
        assert feature.get("id") is not None


def test_build_event_choices_from_metadata():
    module = _load_app_module()
    metadata = {
        "events": [
            {
                "event_id": "spar_fire_2025",
                "event_name": "SPAR/BTC fire",
                "month_label": "December 2025",
            }
        ]
    }
    import pandas as pd

    choices = module.build_event_choices(metadata, pd.DataFrame())
    assert "spar_fire_2025" in choices
    assert "SPAR/BTC fire" in choices["spar_fire_2025"]
    assert "December 2025" in choices["spar_fire_2025"]
