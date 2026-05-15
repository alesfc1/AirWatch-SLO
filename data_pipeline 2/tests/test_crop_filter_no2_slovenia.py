from pathlib import Path
import sys

import numpy as np


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import crop_filter_no2_slovenia as crop_filter  # noqa: E402


def test_calculate_summary_filters_by_qa_and_ignores_nan_values():
    latitude = np.array(
        [
            [45.5, 45.6, 45.7],
            [46.0, 47.5, 45.8],
        ]
    )
    longitude = np.array(
        [
            [13.5, 14.0, 16.0],
            [16.5, 14.0, 17.0],
        ]
    )
    no2 = np.array(
        [
            [1.0, np.nan, 3.0],
            [5.0, 7.0, 9.0],
        ]
    )
    qa_value = np.array(
        [
            [0.80, 0.90, 0.70],
            [0.75, 0.90, 0.90],
        ]
    )

    summary = crop_filter.calculate_summary_from_arrays(
        input_file="synthetic.nc",
        latitude=latitude,
        longitude=longitude,
        no2=no2,
        qa_value=qa_value,
        lat_min=45.4,
        lat_max=46.9,
        lon_min=13.4,
        lon_max=16.6,
        qa_threshold=0.75,
    )

    assert summary["total_pixels_in_bbox_before_qa"] == 4
    assert summary["valid_pixels_after_qa"] == 2
    assert summary["value_mean"] == 3.0
    assert summary["value_min"] == 1.0
    assert summary["value_max"] == 5.0
    assert summary["unit"] == "mol/m²"


def test_calculate_summary_handles_no_valid_pixels():
    latitude = np.array([[45.5, 45.6]])
    longitude = np.array([[13.5, 14.0]])
    no2 = np.array([[np.nan, 2.0]])
    qa_value = np.array([[0.90, 0.40]])

    summary = crop_filter.calculate_summary_from_arrays(
        input_file="synthetic.nc",
        latitude=latitude,
        longitude=longitude,
        no2=no2,
        qa_value=qa_value,
        lat_min=45.4,
        lat_max=46.9,
        lon_min=13.4,
        lon_max=16.6,
        qa_threshold=0.75,
    )

    assert summary["total_pixels_in_bbox_before_qa"] == 2
    assert summary["valid_pixels_after_qa"] == 0
    assert summary["value_mean"] is None
    assert summary["value_min"] is None
    assert summary["value_max"] is None
