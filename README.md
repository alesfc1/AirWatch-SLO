# AirWatch SLO

**Satelitski opazovalnik kakovosti zraka nad Slovenijo — dogodkovno usmerjena interaktivna analiza onesnaževal Sentinel-5P z umestitvijo v slovenski prostor.**

AirWatch SLO je raziskovalna nadzorna plošča, ki združuje (1) dnevne satelitske meritve onesnaževal misije ESA Sentinel-5P, (2) prostorske sloje slovenskih javnih registrov (eProstor) in (3) vremenske podatke Open-Meteo v eno samo, časovno-prostorsko orodje za analizo konkretnih okoljskih dogodkov v Sloveniji.

Aplikacija je zasnovana za hiter pregled: izberi dogodek, sproži časovno animacijo skozi mesec, primerjaj povprečja regij pred in med dogodkom ter preveri, kateri prostorski elementi (občine, prometna infrastruktura, industrijska območja) ležijo okoli prizorišča.

---

## 1. Glavne zmožnosti

| Področje | Funkcionalnost |
|---|---|
| **Dogodkovna analiza** | Trije izbrani primeri (SPAR/BTC požar, Goriški Kras, Cinkarna Celje) z metapodatki, lokacijo in dnevno raznolikostjo onesnaževal. |
| **Časovna animacija** | Drsnik po dnevih meseca, samodejna predvajava in označen "Dan dogodka" oziroma "Obdobje dogodka" natanko nad ustrezno celico drsnika. |
| **Prostorska perspektiva — regije** | Choropleth na ravni NUTS3 (12 regij) z dnevno z-vrednostjo, prilagojenimi mejami in oznako kakovosti meritve (partial / missing). |
| **Prostorska perspektiva — občine** | Občinski pogled (212 občin) za onesnaževala iz Open-Meteo arhiva kakovosti zraka (PM10, PM2.5, NO₂, SO₂, O₃, CO). |
| **Onesnaževala** | NO₂ (privzeto), CO, HCHO, SO₂, AAI — vsako z lastnimi enotami, opisom in pomenom za interpretacijo. |
| **Trend skozi mesec** | Plotly-graf dnevnih povprečij z razponom min–max, robustnimi barvami za projektor in označenim obdobjem dogodka. |
| **Vpliv dogodka** | Tabelarni izračun povprečja **pred** in **med** dogodkom z izrazito rdečo vizualno poudarjeno spremembo (`Δ %`). |
| **GeoSlovenija konteksti** | Vklopni sloji eProstor občin, prometne infrastrukture (avtoceste, železnice) in industrijskih območij iz geo-peskovnika. |
| **Lokacija dogodka** | Klicajna ikona z natančno geografsko koordinato iz metapodatkov. |

---

## 2. Predstavljeni dogodki

| ID | Dogodek | Tip | Obdobje | Lokacija |
|---|---|---|---|---|
| `spar_fire_2025` | Požar v skladišču SPAR (BTC) | Industrijski požar | **14. 12. 2025** (1 dan) | Letališka c., BTC, Ljubljana |
| `kras_fire_2022` | Goriški Kras — gozdni požar | Naravni požar | **15. – 31. 7. 2022** | Goriški Kras |
| `cinkarna_celje_2019` | Cinkarna Celje | Industrijska študija | **december 2019** | Kidričeva 26, Celje |

Vsak dogodek nosi tudi `interpretation_note` in `confidence_note`, ki ju aplikacija prikaže razumljivo, brez nepoštene trditve vzročnosti.

---

## 3. Viri podatkov

| Vir | Vsebina | Format |
|---|---|---|
| **ESA Sentinel-5P** preko Sentinel Hub Statistical API | Dnevne stolpčne koncentracije NO₂, CO, HCHO, SO₂ in aerosolnega indeksa (AAI) po NUTS3 regiji | CSV (dolg format) + JSON metapodatki |
| **eProstor (RPE OGC API Features)** | Občine Slovenije, prometna infrastruktura | GeoJSON, EPSG:4326 |
| **GeoSlovenija geo-peskovnik** | Industrijska in poslovna območja | GeoJSON, EPSG:4326 |
| **Eurostat NUTS 2024** | 12 statističnih regij Slovenije (NUTS3) | Shapefile → GeoJSON |
| **Open-Meteo Historical Weather API** | Temperatura, padavine, veter, vlažnost (jul. 2022) | CSV po občini |
| **Open-Meteo Air Quality Archive** | Občinske vrednosti PM10/PM2.5/NO₂/SO₂/O₃/CO (jul. 2022) | CSV po občini |

Vsi viri so javno dostopni; reprodukcijski skripti so v `data_pipeline/` in `scripts/`.

---

## 4. Tehnološka osnova

- **Python 3.12**
- **Shiny for Python** (`shiny>=0.10`) — reaktiven okvir za UI in server logiko
- **Plotly** (`plotly>=5.20,<6`) — Mapbox choropleth in trendni grafi
- **pandas 2.x** — obdelava časovnih vrst in agregacij
- **shinywidgets** — vključitev Plotly v Shiny
- **Vanilla JavaScript + CSS** — tipkovniška navigacija drsnika, animacijska zanka, natančna poravnava markerja "Dan dogodka", prilagojen barvni sistem.

Brez baz podatkov, brez backend servisov — vse teče lokalno iz statičnih datotek v `outputs/` in `reference_data/`. To zagotovi popolno reproduktibilnost.

---

## 5. Arhitektura

```
+-------------------------------------------------------------+
|  Viri (offline pipeline)                                    |
|  ───────────────────────                                    |
|  Sentinel Hub Stat API ─┐                                   |
|  eProstor / geo-peskov. ─┼─► data_pipeline/ → outputs/*.csv |
|  Open-Meteo (weather/AQ) ┘                       *.geojson  |
+-----------------------------┬-------------------------------+
                              │
                              ▼
+-------------------------------------------------------------+
|  dashboard_shiny/app.py                                     |
|  ───────────────────────                                    |
|  • build_event_cache()    — predračun po (event × poll.)    |
|  • _build_trend_figure()  — Plotly trend (kešan)            |
|  • map_figure / map_restyle — choropleth (Plotly Mapbox)    |
|  • event_window_overlay() — pin "Dan dogodka" na drsnik     |
|  • _compute_event_impact()— statistika pred/med + Δ %       |
+-----------------------------┬-------------------------------+
                              │  Shiny reactive WebSocket
                              ▼
+-------------------------------------------------------------+
|  Brskalnik (Plotly + vanilla JS)                            |
|  ──────────────────────────────                             |
|  www/app.js  — animacija, tipkovnica, scope mirror,         |
|                 natančna poravnava markerja, day-marker     |
|                 v trend grafu preko Plotly.relayout         |
|  www/styles.css — vizualni sistem, responsive, projektor    |
+-------------------------------------------------------------+
```

Ključna performančna odločitev: trend grafi so kešani po (`event`, `pollutant`, `region`, `mode`); ob premiku drsnika *ne* pošljemo cele Plotly slike, le drobno sporočilo `trend_day_marker` z datumom — klient izvede `Plotly.relayout`. Choropleth se osvežuje preko `map_restyle` (samo `z` / `locations` / `customdata` za dva sledilca), tako da osnovna karta, sloji konteksta in pogled (zoom/pan) ostanejo netaknjeni med animacijo.

---

## 6. Namestitev

```bash
# 1. Kloniraj repozitorij
git clone https://github.com/alesfc1/AirWatch-SLO
cd airwatch-geoslovenija

# 2. Virtualno okolje (Python 3.12)
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Odvisnosti dashboarda
pip install -r dashboard_shiny/requirements.txt
```

Statične podatkovne datoteke (`outputs/timeseries/event_pollutants_nuts3_daily.csv`, `reference_data/regions/processed/slovenia_nuts3_regions_2024_4326.geojson` ipd.) so že v repozitoriju, zato aplikacija deluje takoj brez dodatnega prenosa.

---

## 7. Zagon

```bash
python dashboard_shiny/app.py
```

Aplikacija se zažene na `http://127.0.0.1:8000`. Privzeti dogodek (SPAR/BTC) se naloži samodejno, animacija drsnika se sproži po ~1 s — uporabnik vidi takojšen časovni pregled brez kliklanja.

**Bližnjice**

- `←` / `→` — premik po drsniku za en dan
- Klik na **Predvajaj** / **Pavza** — krmiljenje samodejne animacije
- Preklop **Regije / Občine** — prehod med dvema prostorskima okviroma
- Preklop **Dejanske / Odstopanje** — surove vrednosti vs. anomalija od mesečnega povprečja

---

## 8. Struktura projekta

```
airwatch-geoslovenija/
├── README.md                      ← ta dokument
├── dashboard_shiny/               ← interaktivna Shiny aplikacija
│   ├── app.py                     ← celovita logika UI + server
│   ├── requirements.txt
│   └── www/
│       ├── styles.css             ← oblikovni sistem
│       └── app.js                 ← klientska animacija, markerji, day-marker
├── data_pipeline/                 ← skripti za pridobivanje podatkov
│   ├── air_quality/               ← Open-Meteo AQ archive (občine)
│   └── weather/                   ← Open-Meteo Historical Weather (občine)
├── outputs/                       ← procesirane CSV/JSON datoteke
│   └── timeseries/
│       ├── event_pollutants_nuts3_daily.csv
│       └── event_pollutants_nuts3_daily_metadata.json
├── reference_data/
│   ├── regions/                   ← NUTS3 GeoJSON za choropleth
│   └── context_layers/            ← eProstor + geo-peskovnik GeoJSON
├── shapefiles/                    ← izvorni NUTS shapefile
├── docs/
│   └── open_meteo_weather_context.md
└── scripts/                       ← raziskovalni Jupyter notebooki
```

---

## 9. Metodološke opombe

- **Časovno-prostorska povezava ≠ vzročnost.** Aplikacija prikazuje povezave med satelitskim signalom in dogodkom, **ne dokazuje** vzročne zveze. 
- **Stolpčne koncentracije.** Sentinel-5P meri koncentracije v celotnem stolpcu zraka, ne pri tleh. Visoke vrednosti so kazalec, ne dokaz koncentracije na površini.
- **Manjkajoči podatki.** Pri pogosti oblačnosti satelit ne zajame zanesljivega odčitka. Karta in trend zato ločeno označita `partial` in `missing` celice.
- **Mesec analize.** Za vsak dogodek je določeno fiksno analizno okno (običajno cel koledarski mesec), `event_start` / `event_end` pa označuje samo razmerje dogodka znotraj njega.
- **Δ % statistika.** "Sprememba med vs. pred" je razlika v povprečju onesnaževala med dogodkovnimi in pred-dogodkovnimi dnevi znotraj istega meseca; rdeča barva poudari poslabšanje **ali** izboljšanje (smer je razvidna iz predznaka).

---

## 10. Odločitve oblikovanja

- **Dva paralelna prostorska okvirja.** NUTS3 (regije) zagotavlja stabilnost in homogeno površino za satelitsko signal; občinski pogled (212 enot) doda lokalno granularnost in povezavo z znanim slovenskim upravnim sistemom.
- **Konsistenten dogodkovni urn-tok.** Vsako vmesniško okno (karta, trend, vpliv) izhaja iz iste `event_id` reaktivne vrednosti — uporabnik ima na vsakem mestu enako interpretacijo.
- **Vizualni jezik za projektor.** Trend graf uporablja zasičeno mornarsko modro (`#0a4f8a`) in nasprotno saturirano rdečo (`#c8261a`) z izrazitimi črnimi tipografskimi elementi, da je razumljiv tudi z zadnje vrste predavalnice.
- **Tiha postranska kolona.** Kontrole (`Način prikaza`, povprečje SLO) so zožane, GeoSlovenija konteksti pa so postavljeni v ospredje stranske kolone, ker so analitično najbolj informativni.

---

## 11. Reproduciranje podatkovnega pipeline-a (opcijsko)

Za prenovo CSV-jev iz prvih izvirov:

```bash
# Sentinel-5P (zahteva veljavni Sentinel Hub OAuth žeton; glej skripte v scripts/)
python scripts/<notebook-export>.py

# Open-Meteo zgodovinsko vreme — julij 2022, po občinah
python "data_pipeline/weather/fetch_open_meteo_municipalities_july_2022.py"

# Open-Meteo arhiv kakovosti zraka — julij 2022, po občinah
python "data_pipeline/air_quality/fetch_open_meteo_air_quality_municipalities_july_2022.py"
```

Vsak skript zapiše CSV in pripadajoč `*_metadata.json` v `outputs/`.

---

## 12. Atribucije

Podatki:

- **Sentinel-5P** — Copernicus Sentinel data, ESA, dostopano preko Sentinel Hub.
- **eProstor / geo-peskovnik** — Geodetska uprava RS in pripadajoče javne službe.
- **NUTS 2024** — Eurostat (GISCO).
- **Open-Meteo** — Open-Meteo.com, CC BY 4.0.

---
## 14. Ekipa

- Maida Ćivić 
- Matija Čoh
- Aleš Fon Cafnik
- Diana Kiuri
- Bryoona Tirop

Projekt je nastal v okviru hackathon-izziva *GeoSlovenija*. Glavni cilji so bili:

1. **Demokratizirati dostop** do satelitskih okoljskih podatkov v slovenskem jeziku in s slovenskim prostorskim kontekstom.
2. **Pokazati pripoved, ne le številke** — vsak dogodek je opremljen z razumljivo razlago, opozorilom o omejitvah in prikazom prostorskih dejavnikov, ki bi lahko vplivali na signal.
3. **Ostati pošten** glede meja podatkov: tudi negotovost je rezultat.

