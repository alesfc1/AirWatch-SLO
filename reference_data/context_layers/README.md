# Context layers (eProstor / GeoSlovenija geo-peskovnik)

Drop EPSG:4326 GeoJSON files here. The dashboard auto-detects them and
enables the matching layer toggle; missing files leave the toggle in
disabled state with the label "Sloj ni naložen".

Expected filenames:

- `eprostor_municipalities.geojson`
  Občine iz eProstor. Polygon/MultiPolygon. Lastnosti: ime občine.

- `eprostor_transport_infrastructure.geojson`
  Glavna prometna infrastruktura iz eProstor (avtoceste, glavne ceste,
  železnice). LineString/MultiLineString.

- `geopeskovnik_industrial_business_areas.geojson`
  Industrijska in poslovna območja iz GeoSlovenija geo-peskovnika.
  Polygon ali Point. Lastnosti: ime cone, tip dejavnosti.

## CRS

eProstor pogosto streže podatke v EPSG:3794 (D96/TM, slovenski državni
koordinatni sistem). Spletni Plotly/Mapbox zemljevid uporablja EPSG:4326.
Datoteke v tej mapi morajo biti v **EPSG:4326**.

Pretvorbo lahko opraviš z `ogr2ogr`:

```
ogr2ogr -t_srs EPSG:4326 \
  eprostor_municipalities.geojson \
  obcine_3794.geojson
```

Glej `docs/geoslovenija_context_layers.md` za pojasnilo, zakaj te sloje
uporabljamo in kako podpirajo izbrane dogodke (SPAR/BTC, Kras, Cinkarna
Celje).
