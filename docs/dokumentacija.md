# AirWatch SLO — dokumentacija za žirijo in širšo javnost

> Satelitski opazovalnik kakovosti zraka nad Slovenijo.
> Dogodkovno usmerjena analiza onesnaževal misije ESA Sentinel-5P, umeščena v slovenski prostor.

Ta dokument je namenjen **netehnični javnosti, žiriji in odločevalcem**. Razlaga, kaj aplikacija dela, zakaj je to pomembno, kako ji zaupati in kakšne so njene meje. Tehnične podrobnosti so v `README.md` v korenu repozitorija.

---

## 1. Povzetek v 60 sekundah

**Kaj?** AirWatch SLO je interaktivna spletna nadzorna plošča, ki združuje tri vire podatkov v eno orodje:

1. **Satelitske meritve** onesnaževal zraka iz misije ESA **Sentinel-5P** (dnevno, po vsej Sloveniji),
2. **Slovenske prostorske registre** (eProstor, NUTS3 regije, občine, prometna in industrijska infrastruktura),
3. **Vremenske in zemeljske meritve** iz arhivov Open-Meteo.

**Zakaj?** Satelitski podatki so javni, a v praksi nedostopni laiku — surovi CSV-ji brez slovenskega prostorskega okvira. Aplikacija jih spremeni v razumljivo zgodbo o **konkretnih okoljskih dogodkih v Sloveniji**.

**Za koga?** Novinarji, učitelji, lokalne skupnosti, raziskovalci, civilna družba — vsi, ki želijo razumeti, kaj se je dogajalo z zrakom nad Slovenijo med določenim dogodkom.

---

## 2. Kaj aplikacija prikazuje

### Tri dogodke, ki jih lahko raziskujemo

| Dogodek | Datum | Tip | Lokacija |
|---|---|---|---|
| **Požar v skladišču SPAR (BTC)** | 14. december 2025 | industrijski požar | Letališka cesta, Ljubljana |
| **Goriški Kras — gozdni požar** | 15.–31. julij 2022 | naravni požar | Goriški Kras |
| **Cinkarna Celje — industrijska študija** | december 2019 | industrija | Kidričeva 26, Celje |

Vsak dogodek ima razlago, lokacijo na karti in opozorilo o omejitvah interpretacije.

### Pet onesnaževal

| Onesnaževalo | Pomen |
|---|---|
| **NO₂** (dušikov dioksid) | Promet, izgorevanje, industrija. Klasični kazalec urbanega onesnaževanja. |
| **CO** (ogljikov monoksid) | Močan kazalec nepopolnega izgorevanja — značilno za požare. |
| **HCHO** (formaldehid) | Indikator biomasnih požarov in hlapnih organskih spojin. |
| **SO₂** (žveplov dioksid) | Tipičen za kemijsko in metalurško industrijo. |
| **AAI** (aerosolni indeks) | Zaznava dim, prah in pepel v ozračju. |

Za občinski pogled (212 občin) je na voljo tudi Open-Meteo arhiv kakovosti zraka pri tleh: **PM10, PM2.5, NO₂, SO₂, O₃, CO**.

### Štiri perspektive

1. **Karta regij Slovenije (NUTS3, 12 regij)** — dnevni satelitski signal, choropleth.
2. **Karta občin Slovenije (212 občin)** — granularni pogled iz Open-Meteo arhiva.
3. **Trend skozi mesec** — graf dnevnih povprečij z razponom min–max in označenim obdobjem dogodka.
4. **Tabela vpliva dogodka** — povprečje **pred** in **med** dogodkom z izračunano spremembo v odstotkih (Δ %).

---

## 3. Kako se uporablja (vodič za uporabnika)

### Osnovni tok

1. **Izberi dogodek** — privzeto se naloži požar SPAR (december 2025).
2. **Spremljaj animacijo** — drsnik se samodejno premika po dnevih meseca.
3. **Preklopi med onesnaževali** — vsako ima svojo zgodbo (npr. CO in HCHO za požare, NO₂ za promet).
4. **Vklopi prostorske sloje** — občine, ceste, železnice, industrijska območja.
5. **Preveri tabelo vpliva** — koliko se je signal spremenil med dogodkom v primerjavi z dnevi pred njim.

### Bližnjice

| Tipka / gumb | Učinek |
|---|---|
| `←` `→` | premik po drsniku za en dan |
| **Predvajaj / Pavza** | samodejna animacija meseca |
| **Regije / Občine** | preklop prostorskega okvira |
| **Dejanske / Odstopanje** | surove vrednosti vs. anomalija od mesečnega povprečja |

### Kako brati barve

- **Modra → rumena → rdeča** = nizke → srednje → visoke vrednosti onesnaževala.
- **Sive celice** = ni zanesljive meritve tisti dan (običajno zaradi oblačnosti).
- **Šrafirane celice** = delna pokritost (`partial`).

---

## 4. Od kod podatki

Vsi viri so **javni** in **brezplačni**.

| Vir | Kdo ga ureja | Kaj prispeva |
|---|---|---|
| **Sentinel-5P** | ESA (Evropska vesoljska agencija) preko Copernicus | dnevne stolpčne koncentracije NO₂, CO, HCHO, SO₂, AAI |
| **eProstor (RPE)** | Geodetska uprava RS | občine, prometna infrastruktura |
| **GeoSlovenija geo-peskovnik** | javni geo-portal | industrijska in poslovna območja |
| **NUTS 2024** | Eurostat | 12 statističnih regij Slovenije |
| **Open-Meteo Historical Weather** | Open-Meteo.com (CC BY 4.0) | temperatura, padavine, veter, vlažnost |
| **Open-Meteo Air Quality Archive** | Open-Meteo.com (CC BY 4.0) | občinske vrednosti PM, NO₂, SO₂, O₃, CO |

**Reproducibilnost.** Vsi skripti za pridobivanje podatkov so v repozitoriju (`data_pipeline/`, `scripts/`). Kdor želi, lahko podatke prenese sam in preveri.

---
## 6. Zakaj smo to naredili (motivacija)

Trije razlogi:

1. **Demokratizacija dostopa.** Satelitski podatki so v lasti vseh evropskih državljanov — a praktično skriti za tehničnimi ovirami. Naša naloga je narediti jih dostopne v slovenskem jeziku in s slovenskim prostorskim kontekstom.

2. **Pripoved, ne le številke.** Vsak dogodek je opremljen z razumljivo razlago in opozorilom o omejitvah. Cilj je razumevanje, ne impresioniranje s tehnologijo.

3. **Poštenost glede negotovosti.** V okoljskem komuniciranju je preveč pretiranih trditev. Mi pokažemo tudi tisto, česar ne vemo — manjkajoče celice, opozorila, omejitve metode. Tudi negotovost je rezultat.

---

## 7. Konteksti uporabe

| Uporabnik | Kako uporabi |
|---|---|
| **Novinar** | Hitra vizualna podlaga za zgodbo o okoljskem dogodku, z navedbo vira ESA in metodoloških meja. |
| **Učitelj geografije / kemije** | Konkreten primer satelitskih podatkov v razredu, z domačim slovenskim kontekstom. |
| **Lokalna skupnost** | Pogled na to, kaj se je dogajalo nad njihovo občino v določenem mesecu. |
| **Raziskovalec / študent** | Vstopna točka pred globlimi raziskavami; reproducibilni pipeline za nadaljnje delo. |
| **Odločevalec** | Vizualna utemeljitev, zakaj je vredno odpreti satelitske podatke širšemu krogu. |

---

## 8. Tehnologija (na kratko)

- **Python 3.12** + **Shiny for Python** (interaktivni okvir)
- **Plotly Mapbox** (karte) in **Plotly** (grafi trendov)
- **pandas** (obdelava časovnih vrst)
- **Vanilla JavaScript + CSS** (animacija drsnika, tipkovniška navigacija)

Aplikacija teče **lokalno**, brez baze podatkov in brez backend servisov. Vsi podatki so statične datoteke v repozitoriju. To zagotavlja popolno reproducibilnost in nizko ceno vzdrževanja.

Podrobnosti arhitekture: glej `README.md`, razdelek 5.

---

## 9. Ekipa

Projekt je nastal v okviru hackathon-izziva **GeoSlovenija**.

- Maida Ćivić
- Matija Čoh
- Aleš Fon Cafnik
- Diana Kiuri
- Bryoona Tirop

---

## 10. Atribucije in licenca podatkov

- **Sentinel-5P** — Copernicus Sentinel data, ESA (dostopano preko Sentinel Hub).
- **eProstor / geo-peskovnik** — Geodetska uprava RS in pripadajoče javne službe.
- **NUTS 2024** — Eurostat (GISCO).
- **Open-Meteo** — Open-Meteo.com, CC BY 4.0.

Vsi izvirni viri so javni. Ob uporabi vizualizacij iz aplikacije v drugih medijih prosimo, da navedete tudi izvor podatkov.

---

*Različica dokumenta: maj 2026. Pripravljeno za predstavitev GeoSlovenija.*
