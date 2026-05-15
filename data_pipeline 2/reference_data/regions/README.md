# Slovenian Statistical Region Boundaries

This folder is reserved for region boundary reference data used by the AirWatch SLO data pipeline.

## Selected Source

Use Eurostat GISCO NUTS 2024 region geometries as the Sprint 2 development source for Slovenian statistical regions.

- Source name: Eurostat GISCO NUTS 2024
- Dataset family: Territorial units for statistics (NUTS)
- Region level: NUTS 3, Slovenian statistical regions
- Expected country filter: `CNTR_CODE = SI`
- Expected level filter: `LEVL_CODE = 3`
- Expected number of Slovenian regions: 12
- Preferred format: GeoJSON
- Preferred CRS: EPSG:4326
- Geometry type: MultiPolygon / Polygon region geometries

Recommended source URL:

```text
https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_20M_2024_4326_LEVL_3.geojson
```

The full NUTS level 3 GeoJSON contains all European NUTS3 regions. Keep that file in `raw/` locally and do not commit it unless the team deliberately decides it is small enough and useful enough for version control.

## Local File Layout

```text
data_pipeline/reference_data/regions/
├── raw/
│   └── NUTS_RG_20M_2024_4326_LEVL_3.geojson
└── processed/
    └── slovenia_nuts3_regions_2024.geojson
```

`raw/` is for downloaded source files. `processed/` is for a future filtered Slovenian-only file.

## Fields To Use Later

- `region_name`: use `NUTS_NAME`; fallback to `NAME_LATN` if needed.
- `region_code`: use `NUTS_ID`, for example `SI041`.
- `region_type`: use `nuts3` or `statistical_region`.
- `geometry`: use the GeoJSON geometry after confirming CRS is EPSG:4326.

## Inspection

After downloading a file locally, inspect it with:

```bash
python data_pipeline/scripts/inspect_region_boundaries.py \
  --file data_pipeline/reference_data/regions/raw/NUTS_RG_20M_2024_4326_LEVL_3.geojson \
  --country-code SI \
  --level 3
```

This script does not require a database connection.
