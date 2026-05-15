# GeoSlovenija / eProstor prostorski konteksti

Ta dokument pojasnjuje, zakaj v nadzorni plošči AirWatch GeoSlovenija
uporabljamo dva slovenska prostorska vira – **eProstor** in **GeoSlovenija
geo-peskovnik** – in kako se njuni sloji pojavijo na zemljevidu.

## Zakaj prostorski kontekst

Sentinel-5P pove **kako močan je signal** (vrednosti onesnaževal v stolpcu
zraka), ne pa, **kaj se v prostoru dogaja**. Brez prostorskega konteksta
satelitski signal težko razložimo:

- Visoke vrednosti NO₂ nad mestom pričakujemo zaradi prometa.
- Visoke vrednosti CO ali HCHO blizu naselja in gozda namigujejo na požar.
- Ponavljajoč signal SO₂ ob industrijski coni nakazuje stalen vir.

eProstor in GeoSlovenija geo-peskovnik sta odprta slovenska vira, ki
ponujata ravno take referenčne sloje – **brez** kemičnih ali okoljskih
podatkov, samo prostorsko strukturo.

> Prostorski sloji ne dokazujejo vzročnosti. Pomagajo interpretirati
> satelitski signal.

## Pričakovane datoteke

Vse datoteke so opcijske. Če manjkajo, dashboard ne pade – stikalo za
ustrezen sloj samo dobi stanje `Sloj ni naložen` in se onemogoči.

Datoteke ležijo v:

```
reference_data/context_layers/
  ├── eprostor_municipalities.geojson
  ├── eprostor_transport_infrastructure.geojson
  └── geopeskovnik_industrial_business_areas.geojson
```

| Datoteka | Vir | Geometrija | Vsebina |
|---|---|---|---|
| `eprostor_municipalities.geojson` | eProstor | Polygon / MultiPolygon | Občinske meje |
| `eprostor_transport_infrastructure.geojson` | eProstor | LineString / MultiLineString | Avtoceste, glavne ceste, železnice |
| `geopeskovnik_industrial_business_areas.geojson` | GeoSlovenija geo-peskovnik | Polygon ali Point | Industrijska in poslovna območja |

Vse datoteke morajo biti v **EPSG:4326**. Plotly Mapbox renderer (kakor
spletni zemljevidi nasploh) pričakuje WGS84 v stopinjah.

### Trenutno priložene datoteke

Repozitorij vsebuje vnaprej naložene datoteke, ki ustrezajo gornji shemi:

| Datoteka | Dejanski vir | Opomba |
|---|---|---|
| `eprostor_municipalities.geojson` | **eProstor RPE** | OGC API Features `SI.GURS.RPE:OBCINE` — vseh 212 občin neposredno iz uradnega registra |
| `eprostor_transport_infrastructure.geojson` | **OpenStreetMap (zrcalo eProstor GJI)** | Avtoceste, hitre ceste in železnica, izvlečeno iz OSM-ja, ker uradni eProstor Zbirni kataster GJI zahteva interaktivno prijavo v aplikacijo JGP |
| `geopeskovnik_industrial_business_areas.geojson` | **OpenStreetMap (zrcalo geo-peskovnik)** | Industrijska in poslovna območja po OSM klasifikaciji (`landuse=industrial` / `landuse=commercial`). Geo-peskovnik nima javnega OGC API-ja za prenos. |

Vsaka datoteka ima v koreniski lastnosti `properties.source` zapisan
**dejanski vir**. Dashboard prikaže ta zapis v sloju kot "pill" (značko)
ob imenu sloja – tako uporabnik vedno vidi, ali gleda izvirne eProstor
podatke ali OSM zrcalo. Če datoteko ročno zamenjaš s pravo izvorno
različico (npr. po prenosu iz JGP), spremeni `properties.source` in
oznaka v UI se samodejno posodobi.

### Zakaj OSM kot zrcalo za GJI in geo-peskovnik

eProstor JGP (Javno geodetska informacijska platforma) je uradni
distribucijski kanal za prosti prenos infrastrukturnih in topografskih
podatkov, vendar nima javnega OGC API endpoint-a za neavtenticiran
prenos. Vsak prenos zahteva interaktiven login + ZIP prenos. Za potrebe
hackathon prototipa smo uporabili OSM Overpass kot **začasno zrcalo**,
ker so podatki za našo namembnost (vizualni kontekst, ne uradna meritev)
funkcionalno enakovredni in javno dostopni. Ko se podatki iz JGP-ja
prenesejo ročno, datoteko v `reference_data/context_layers/` preprosto
zamenjamo z eProstor različico in dashboard prikaže izvirno oznako
vira.

## CRS – pretvorba iz EPSG:3794

eProstor podatke pogosto streže v **EPSG:3794 (D96/TM)**, slovenskem
državnem koordinatnem sistemu (transverzalni Mercator). Za prikaz v
spletnem zemljevidu jih je treba pretvoriti v EPSG:4326.

Pretvorba z `ogr2ogr`:

```bash
ogr2ogr \
  -t_srs EPSG:4326 \
  reference_data/context_layers/eprostor_municipalities.geojson \
  vir/obcine_3794.geojson
```

ali z Python `geopandas`:

```python
import geopandas as gpd
g = gpd.read_file("vir/obcine_3794.geojson")
g = g.to_crs("EPSG:4326")
g.to_file("reference_data/context_layers/eprostor_municipalities.geojson",
          driver="GeoJSON")
```

GeoSlovenija geo-peskovnik praviloma že streže podatke v EPSG:4326, a je
vredno preveriti polje `crs` v datoteki.

## Kako sloji podpirajo posamezne dogodke

Dashboard prikazuje tri primere – vsak ima drugačno prostorsko zgodbo.

### SPAR / BTC (Ljubljana, december 2025)

**Tipologija**: industrijski / logistični požar v urbanem območju.

- **Občine** pokažejo, kje konča Mestna občina Ljubljana in se začnejo
  sosednje občine (Domžale, Trzin, Vrhnika). Tako se vidi, kdaj NO₂
  oblak preide čez občinsko mejo.
- **Prometna infrastruktura** pokaže ljubljansko obvoznico in
  primorsko/štajersko avtocesto, ki sta primarna prometna vira NO₂.
  Brez tega bi visoke vrednosti NO₂ v vzhodni Sloveniji pripisali samo
  požaru.
- **Industrijska in poslovna območja** označijo BTC logistični center
  in industrijske cone okoli Ljubljane – torej kraj samega dogodka in
  podobne potencialne vire.

### Kras / Goriška (julij 2022)

**Tipologija**: obsežen gozdni požar v slabo poseljenem območju.

- **Občine** pokažejo Renče-Vogrsko, Miren-Kostanjevico, Komen in
  Sežano – majhne občine s peščico naselij okrog območja požara.
- **Prometna infrastruktura** pomaga oceniti, ali se signal poklapa
  z avtocesto A1 ali pa je res zamejen na gozdno območje (kar je
  značilen vzorec za biomasni požar).
- **Industrijska območja** so v tem primeru bolj kontrolni sloj – če
  signal CO ali HCHO sovpada z industrijsko cono in ne z gozdom, je
  treba interpretacijo popraviti.

### Cinkarna Celje (2019)

**Tipologija**: dolgoletna industrijska študija v urbanem območju.

- **Občine** zarisujejo Mestno občino Celje in okoliške občine
  (Štore, Vojnik), kjer se signal industrije pogosto prelije.
- **Industrijska in poslovna območja** so glavni sloj: lokacija
  Cinkarne, soseščina drugih industrijskih obratov ter razdalja do
  stanovanjskih območij omogočijo razlago, kateri obrat verjetno
  prispeva največ k SO₂ in NO₂ signalu.
- **Prometna infrastruktura** pokaže obvoznico Celja in
  južnoslovensko železnico – pogost dodaten NO₂ vir, ki ga je treba
  ločiti od industrijske emisije.

## Stilizacija na zemljevidu

Sloji so izrisani namerno **suptilno**, tako da glavna informacija
ostane NUTS3 choropleth onesnaženosti (Sentinel-5P):

- Občine – tanka obroba (širina ~0.8 px), brez polnila.
- Prometna infrastruktura – tanke modre linije (širina ~1.2 px).
- Industrijska/poslovna območja – polprozorno polnilo z oranžno
  obrobo + manjša točka na centroidu cone za prepoznavnost pri nizki
  povečavi.

## Razmerje do podatkovnega cevovoda

Pomembno: te plasti **niso** del Sentinel Hub cevovoda. Ne vnašajo se
v `outputs/timeseries/` in ne vplivajo na izračun vrednosti
onesnaževal. So zgolj prostorska referenca, ki jo dashboard naloži
ob zagonu in pošlje brskalniku skupaj s Plotly figuro.

To pomeni, da lahko datoteke v `reference_data/context_layers/`
posodabljaš neodvisno od pipeline-a (kadar koli pride nova različica
občin ali ko vstaviš dodatne industrijske cone).
