# AirWatch SLO Data Pipeline

Sprint 1 data discovery scripts for Sentinel-5P NO2 products from the Copernicus Data Space Ecosystem.

These scripts do not download anything automatically. They give you local commands to authenticate, search products over Slovenia, download one selected product, inspect the NetCDF structure, and calculate initial NO2 statistics for the Slovenia bounding box.

## Setup

Create `.env` in the repository root:

```env
COPERNICUS_USERNAME=your_email_here
COPERNICUS_PASSWORD=your_password_here
```

Install Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests python-dotenv xarray numpy netCDF4
```

`netCDF4` is needed by xarray to open Sentinel-5P NetCDF groups with `group="PRODUCT"`.

## Slovenia Discovery Constants

- Latitude: `45.4` to `46.9`
- Longitude: `13.4` to `16.6`
- Initial quality filter: `qa_value >= 0.75`
- Required NetCDF variables: `latitude`, `longitude`, `nitrogendioxide_tropospheric_column`, `qa_value`

## Run Commands

Check that credentials work without printing the full token:

```bash
python data_pipeline/scripts/get_copernicus_token.py
```

Search products over Slovenia:

```bash
python data_pipeline/scripts/search_s5p_no2_products.py --start-date 2024-01-01 --end-date 2024-01-31
```

Download one selected product:

```bash
python data_pipeline/scripts/download_s5p_no2_product.py --product-id PRODUCT_UUID_FROM_SEARCH
```

Inspect the downloaded NetCDF PRODUCT group:

```bash
python data_pipeline/scripts/inspect_s5p_no2_structure.py --file data_pipeline/sample_data/YOUR_PRODUCT.nc
```

Calculate NO2 statistics for the Slovenia bounding box:

```bash
python data_pipeline/scripts/process_no2_slovenia_bbox.py --file data_pipeline/sample_data/YOUR_PRODUCT.nc
```

Crop/filter the selected Sprint 2 product to the Slovenia bounding box and apply the NO2 QA filter:

```bash
python data_pipeline/scripts/crop_filter_no2_slovenia.py \
  --file data_pipeline/sample_data/S5P_OFFL_L2__NO2____20250311T115807_20250311T133937_38393_03_020800_20250313T042301.nc
```

Optionally save a small JSON summary:

```bash
python data_pipeline/scripts/crop_filter_no2_slovenia.py \
  --file data_pipeline/sample_data/S5P_OFFL_L2__NO2____20250311T115807_20250311T133937_38393_03_020800_20250313T042301.nc \
  --output data_pipeline/outputs/no2_crop_filter/slovenia_no2_crop_filter_summary.json
```

Aggregate valid NO2 pixels by Slovenian NUTS3/statistical region:

```bash
python data_pipeline/scripts/aggregate_no2_by_region.py \
  --no2-file data_pipeline/sample_data/S5P_OFFL_L2__NO2____20250311T115807_20250311T133937_38393_03_020800_20250313T042301.nc \
  --regions-file data_pipeline/reference_data/regions/raw/NUTS_RG_20M_2024_4326_LEVL_3.geojson \
  --output data_pipeline/outputs/no2_by_region/regional_no2_results.json \
  --source-product-id b898f30a-1d6e-4c6c-bdc2-9933a06e316e \
  --measurement-start-time 2025-03-11T12:19:40Z \
  --measurement-end-time 2025-03-11T13:18:05Z
```

Validate the generated regional NO2 output:

```bash
python data_pipeline/scripts/validate_regional_no2_output.py \
  --file data_pipeline/outputs/no2_by_region/regional_no2_results.json \
  --expected-valid-regions 8 \
  --expected-no-data-regions 4 \
  --expected-assigned-valid-pixels 46
```

Run lightweight pipeline tests:

```bash
python -m pip install -r data_pipeline/requirements-dev.txt
python -m pytest data_pipeline/tests
```

The tests use synthetic arrays, polygons and temporary JSON files. They do not require Copernicus credentials, network access, a real `.nc` product or a database connection. More detail is in [`docs/pipeline_tests.md`](../docs/pipeline_tests.md).

## Data Safety

Do not commit `.env`, `.nc`, `.zip`, or downloaded Copernicus products. The `sample_data/` directory is ignored except for `.gitkeep`.
