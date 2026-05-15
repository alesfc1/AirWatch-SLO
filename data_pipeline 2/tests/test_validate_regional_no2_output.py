import json
from pathlib import Path
import sys


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate_regional_no2_output as validator  # noqa: E402


def make_valid_output():
    pixel_counts = [3, 5, 1, 8, 10, 3, 1, 15]
    rows = []

    for index, pixel_count in enumerate(pixel_counts, start=1):
        rows.append(
            {
                "region_code": f"SI{index:03d}",
                "region_name": f"Region {index}",
                "value_mean": 2.0,
                "value_min": 1.0,
                "value_max": 3.0,
                "pixel_count_valid": pixel_count,
                "qa_threshold": 0.75,
                "quality_status": "valid",
                "unit": "mol/m²",
                "measurement_start_time": "2025-03-11T12:19:40Z",
                "measurement_end_time": "2025-03-11T13:18:05Z",
                "source_product_id": "b898f30a-1d6e-4c6c-bdc2-9933a06e316e",
                "source_product_name": "product.nc",
            }
        )

    for index in range(9, 13):
        rows.append(
            {
                "region_code": f"SI{index:03d}",
                "region_name": f"Region {index}",
                "value_mean": None,
                "value_min": None,
                "value_max": None,
                "pixel_count_valid": 0,
                "qa_threshold": 0.75,
                "quality_status": "no_valid_pixels",
                "unit": "mol/m²",
                "measurement_start_time": "2025-03-11T12:19:40Z",
                "measurement_end_time": "2025-03-11T13:18:05Z",
                "source_product_id": "b898f30a-1d6e-4c6c-bdc2-9933a06e316e",
                "source_product_name": "product.nc",
            }
        )

    return rows


def validate_rows(rows):
    errors, warnings, summary = validator.validate_output(rows)
    return errors, warnings, summary


def assert_has_error(errors, text):
    assert any(text in error for error in errors), errors


def test_valid_regional_output_passes_validation(tmp_path):
    output_path = tmp_path / "regional_no2_results.json"
    output_path.write_text(
        json.dumps(make_valid_output(), ensure_ascii=False),
        encoding="utf-8",
    )

    data = validator.load_json(output_path)
    errors, warnings, summary = validate_rows(data)

    assert errors == []
    assert warnings == []
    assert summary["total_regions"] == 12
    assert summary["valid_regions"] == 8
    assert summary["no_data_regions"] == 4
    assert summary["assigned_valid_pixels"] == 46


def test_explicit_expected_counts_are_enforced():
    rows = make_valid_output()

    errors, _warnings, _summary = validator.validate_output(
        rows,
        expected_valid_regions=9,
        expected_no_data_regions=3,
        expected_assigned_valid_pixels=47,
    )

    assert_has_error(errors, "Expected 9 valid regions")
    assert_has_error(errors, "Expected 3 no_valid_pixels regions")
    assert_has_error(errors, "Expected 47 assigned valid pixels")


def test_missing_required_field_fails_validation():
    rows = make_valid_output()
    del rows[0]["unit"]

    errors, _warnings, _summary = validate_rows(rows)

    assert_has_error(errors, "missing required fields: unit")


def test_invalid_quality_status_fails_validation():
    rows = make_valid_output()
    rows[0]["quality_status"] = "unknown"

    errors, _warnings, _summary = validate_rows(rows)

    assert_has_error(errors, "quality_status must be one of")


def test_invalid_min_mean_max_relationship_fails_validation():
    rows = make_valid_output()
    rows[0]["value_min"] = 5.0
    rows[0]["value_mean"] = 4.0
    rows[0]["value_max"] = 6.0

    errors, _warnings, _summary = validate_rows(rows)

    assert_has_error(errors, "expected value_min <= value_mean <= value_max")


def test_no_valid_pixels_with_positive_pixel_count_fails_validation():
    rows = make_valid_output()
    rows[8]["pixel_count_valid"] = 1

    errors, _warnings, _summary = validate_rows(rows)

    assert_has_error(errors, "no_valid_pixels row must have pixel_count_valid == 0")
