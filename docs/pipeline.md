# Data Pipeline

Glavni NO2 pipeline zdaj uporablja Sentinel Hub Statistical API.

To pomeni: ne gradimo vec glavnega procesa okrog rocnega downloadanja velikih
Sentinel-5P `.nc` datotek. Namesto tega v API posljemo slovenske NUTS3
poligone, casovni interval in evalscript, Sentinel Hub pa vrne agregirane
statistike za vsak interval.

## Zakaj Sentinel Hub Statistical API

Prejsnji `.nc` pristop je bil dober za raziskovanje, ampak za projekt je prevec
tezak:

- `.nc` datoteke so velike,
- ne smejo biti commitane,
- lokalna obdelava je pocasnejsa,
- tezje je ponovljivo delati casovne serije.

Statistical API je bolj primeren, ker:

- dela agregacijo na strani Sentinel Hub,
- vrne majhne JSON odgovore,
- lahko direktno racuna po NUTS3 poligonih,
- lepo podpira mesecne ali dnevne intervale,
- output se enostavno spremeni v CSV za PostGIS in dashboard.

## Glavna mapa

```text
data_pipeline/sentinel_hub_stats/
```

Glavni koraki:

```text
01_prepare_regions.py
02_build_statistical_requests.py
03_run_statistical_api.py
04_parse_statistical_results.py
05_import_postgis.py
evalscripts/sentinel5p_no2.js
```

## Regije

Input iz `data_pipeline_nas` uporabljamo samo za NUTS3 GeoJSON:

```text
reference_data/regions/raw/NUTS_RG_20M_2024_4326_LEVL_3.geojson
```

`01_prepare_regions.py` iz njega naredi:

```text
reference_data/regions/processed/slovenia_nuts3_regions_2024_4326.geojson
reference_data/regions/processed/slovenia_nuts3_regions_2024_3794.gpkg
```

Uporabimo samo:

- `CNTR_CODE = SI`
- `LEVL_CODE = 3`

Pricakujemo 12 slovenskih NUTS3 regij.

## CRS pravila

EPSG:4326 uporabljamo za:

- Sentinel Hub Statistical API request geometries,
- Leaflet/OpenStreetMap,
- web map display,
- PostGIS display geometrije.

EPSG:3794 / D96-TM uporabljamo za:

- slovensko prostorsko analizo,
- validacijo geometrij,
- lokalne GIS izracune, kjer rabimo slovenski koordinatni sistem.

## Sentinel Hub API

Credentials se berejo samo iz environment variables:

```text
SH_CLIENT_ID
SH_CLIENT_SECRET
```

Ne hardcodamo credentialov in ne commitamo `.env`.

Evalscript:

```text
data_pipeline/sentinel_hub_stats/evalscripts/sentinel5p_no2.js
```

Vrne:

- `no2`
- `dataMask`

`dataMask` je pomemben, ker Statistical API z njim ve, katere piksle naj izkljuci
iz statistike.

## Outputi

Manifest requestov:

```text
outputs/sentinel_hub_stats/request_manifest.json
```

Raw API odgovori:

```text
outputs/sentinel_hub_stats/raw/
```

Cist time-series CSV:

```text
outputs/timeseries/no2_nuts3_timeseries.csv
```

Ta CSV ima stolpce:

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

## PostGIS

`05_import_postgis.py` uvozi time-series CSV v tabelo:

```text
no2_measurements
```

Regije lahko pripravi v:

```text
nuts3_regions
```

Dashboard potem lahko bere:

- NO2 povprecje po regiji,
- min/max/stdev,
- casovni interval,
- quality status,
- stevilo validnih pikslov,
- geometrijo regije.

## Povezave z ostalim projektom

Ta output mora ostati uporaben za:

- PostGIS,
- Python Shiny dashboard,
- Leaflet/OpenStreetMap map,
- event impact analysis,
- ARSO primerjavo.

## Kaj ne gre v git

Ne commitamo:

- `.env`
- `*.nc`
- `*.zip`
- `*.part`
- velikih Sentinel download datotek,
- full `sample_data` vsebin,
- lokalnih temporary datotek.
