# Katere podatke dobimo iz novega pipeline-a

Glavni pipeline je zdaj Sentinel Hub Statistical API pipeline:

```text
data_pipeline/sentinel_hub_stats/
```

Ne temelji vec na rocni obdelavi velikih Sentinel-5P `.nc` datotek.

## 1. Regije

Iz raw Eurostat NUTS3 GeoJSON dobimo slovenske regije:

```text
reference_data/regions/raw/NUTS_RG_20M_2024_4326_LEVL_3.geojson
```

Processed output:

```text
reference_data/regions/processed/slovenia_nuts3_regions_2024_4326.geojson
reference_data/regions/processed/slovenia_nuts3_regions_2024_3794.gpkg
```

Dobimo 12 slovenskih NUTS3 regij z:

- `region_code`
- `region_name`
- geometrijo
- originalnimi NUTS atributi

## 2. Sentinel Hub request manifest

Skripta:

```text
data_pipeline/sentinel_hub_stats/02_build_statistical_requests.py
```

Output:

```text
outputs/sentinel_hub_stats/request_manifest.json
```

Manifest vsebuje en request na regijo za izbran casovni razpon.

Za vsak request imamo:

- `region_code`
- `region_name`
- `geometry`
- `start_date`
- `end_date`
- `aggregation_interval`
- `pollutant`
- `request_payload`

Privzeto:

- pollutant: `NO2`
- aggregation interval: `P1M`
- vir: Sentinel-5P prek Sentinel Hub

## 3. Raw Statistical API odgovori

Skripta:

```text
data_pipeline/sentinel_hub_stats/03_run_statistical_api.py
```

Output:

```text
outputs/sentinel_hub_stats/raw/
```

Dobimo en JSON na regijo, npr.:

```text
SI031_NO2_2024-01-01_2024-12-31.json
```

V teh odgovorih so statistike po intervalih:

- `mean`
- `min`
- `max`
- `stDev`
- `sampleCount`
- `noDataCount`

## 4. Cist NO2 time-series CSV

Skripta:

```text
data_pipeline/sentinel_hub_stats/04_parse_statistical_results.py
```

Glavni output:

```text
outputs/timeseries/no2_nuts3_timeseries.csv
```

Stolpci:

- `date_from`
- `date_to`
- `region_code`
- `region_name`
- `pollutant`
- `value_mean`
- `value_min`
- `value_max`
- `value_stdev`
- `sample_count`
- `no_data_count`
- `data_mask_valid_count`
- `unit`
- `source`
- `aggregation_interval`
- `quality_status`

To je najpomembnejsi dataset za PostGIS in dashboard.

## 5. PostGIS tabele

Skripta:

```text
data_pipeline/sentinel_hub_stats/05_import_postgis.py
```

Pripravi oziroma napolni:

```text
nuts3_regions
no2_measurements
```

`no2_measurements` hrani NO2 casovno serijo po regijah.

## 6. Kaj lahko dashboard bere

Dashboard lahko direktno uporablja:

```text
outputs/timeseries/no2_nuts3_timeseries.csv
```

ali pa isto stvar iz PostGIS tabele:

```text
no2_measurements
```

Za mapo potrebuje se:

```text
nuts3_regions
```

Dashboard lahko prikaze:

- NO2 povprecje po regiji,
- min/max/stdev,
- casovni interval,
- stevilo validnih pikslov,
- quality status,
- primerjave med regijami,
- trende skozi cas.

## Kratek povzetek

Iz novega pipeline-a dobimo:

1. slovenske NUTS3 regije v EPSG:4326 in EPSG:3794,
2. Sentinel Hub Statistical API request manifest,
3. raw API JSON odgovore,
4. cist NO2 time-series CSV po regijah,
5. podatke pripravljene za PostGIS in Shiny dashboard.

Velikih `.nc` Sentinel datotek ne commitamo in jih ne uporabljamo kot glavno
arhitekturo pipeline-a.
