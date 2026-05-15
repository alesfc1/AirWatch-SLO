from pathlib import Path
import sys


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import aggregate_no2_by_region as aggregate  # noqa: E402


def polygon(min_lon, min_lat, max_lon, max_lat):
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]
        ],
    }


def make_regions():
    return [
        {
            "region_code": "R1",
            "region_name": "Region one",
            "geometry": polygon(0.0, 0.0, 1.0, 1.0),
            "values": [],
        },
        {
            "region_code": "R2",
            "region_name": "Region two",
            "geometry": polygon(1.0, 0.0, 2.0, 1.0),
            "values": [],
        },
        {
            "region_code": "R3",
            "region_name": "Region three",
            "geometry": polygon(2.0, 0.0, 3.0, 1.0),
            "values": [],
        },
    ]


def test_assign_pixels_to_regions_and_build_region_statistics():
    regions = make_regions()
    pixels = [
        (0.25, 0.25, 1.0),
        (0.75, 0.75, 3.0),
        (1.50, 0.50, 10.0),
        (9.00, 9.00, 99.0),
    ]

    unassigned_count = aggregate.assign_pixels_to_regions(pixels, regions)
    results = aggregate.build_results(
        regions=regions,
        qa_threshold=0.75,
        source_product_id="product-id",
        source_product_name="product.nc",
    )
    result_by_code = {result["region_code"]: result for result in results}

    assert unassigned_count == 1

    assert result_by_code["R1"]["quality_status"] == "valid"
    assert result_by_code["R1"]["pixel_count_valid"] == 2
    assert result_by_code["R1"]["value_mean"] == 2.0
    assert result_by_code["R1"]["value_min"] == 1.0
    assert result_by_code["R1"]["value_max"] == 3.0

    assert result_by_code["R2"]["quality_status"] == "valid"
    assert result_by_code["R2"]["pixel_count_valid"] == 1
    assert result_by_code["R2"]["value_mean"] == 10.0

    assert result_by_code["R3"]["quality_status"] == "no_valid_pixels"
    assert result_by_code["R3"]["pixel_count_valid"] == 0
    assert result_by_code["R3"]["value_mean"] is None
    assert result_by_code["R3"]["value_min"] is None
    assert result_by_code["R3"]["value_max"] is None
