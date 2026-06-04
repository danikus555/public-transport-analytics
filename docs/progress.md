# Progress

## Sprint 1 — planeerimine ja arhitektuur
**Periood:** 18.05–24.05.2026 | **Staatus:** ✅ Esitatud

### Tehtud
- [x] Äriküsimus ja mõõdikud defineeritud
- [x] Andmeallikad kaardistatud (GPS, kütus, GTFS)
- [x] Ligipääsud kontrollitud praktikas
- [x] Arhitektuuriskeem joonistatud (Mermaid)
- [x] Andmebaasi kihid (bronze/silver/gold) kirjeldatud
- [x] Riskid tuvastatud koos maandamisega
- [x] GitHub repo loodud: https://github.com/danikus555/public-transport-analytics

---

## Sprint 2 — andmevoog ja transformatsioonid
**Periood:** 25.05–31.05.2026 | **Staatus:** ✅ Valmis

### Äriküsimuse muutus
Sprint 1 äriküsimus oli liiga üldine. Andmetega töötades selgus et GPS + GTFS +
kütusehindade + sõidukimudelite kombineerimine võimaldab vastata konkreetsematele
küsimustele:

- Mitu bussi, trammi ja rongi on praegu liikvel?
- Millistel marsruutidel?
- Kas Elroni rongid sõidavad graafiku järgi?
- Lisaavastus: teoreetiline päevane kütusekulu transpordiliigi järgi (±25%)

### Mis on valmis

**Infrastruktuur:**
- [x] Docker Compose — 4 konteinerit (pgduckdb, pipeline, dbt, Superset)
- [x] APScheduler — kõik jobid konfigureeritavad `.env` kaudu
- [x] Öörežiim — GPS ja Elron peatuvad 00:00–06:00
- [x] Bonuseks Loguru 3-kanalilne logimine → `logs/YYYY/mmmYYYY/DDMMYYYY/`

**Andmete sissevõtt:**
- [x] `ingest_gps.py` — TLT GPS iga 60s → `bronze.vehicle_positions`
- [x] `ingest_elron.py` — Elroni rongid iga 30s → `bronze.elron_positions`
- [x] `ingest_fuel.py` — 95/98/Diesel + elekter (Elering) + CNG (Alexela)
- [x] `load_gtfs.py` — TLT 81 + Elron 28 marsruuti, versioonikontroll
- [x] `load_reference.py` — 20 sõidukimudelit tarbimise ja arvuga

**dbt transformatsioonid (7 mudelit):**
- [x] `silver.vehicle_positions` — GPS + GTFS join
- [x] `silver.elron_positions` — Elron + kütuse tüüp
- [x] `gold.latest_positions` — viimane positsioon iga sõiduki kohta
- [x] `gold.fleet_summary` — laevastiku kokkuvõte
- [x] `gold.fuel_cost_daily` — päevane kütusekulu + kasutusaste
- [x] `gold.fuel_daily` — kütusehinna muutus eelmise päevaga
- [x] `gold.route_activity` — aktiivsed sõidukid liini ja tunni järgi

**dbt andmekvaliteedi testid (16 testi):**
- [x] `not_null` — vehicle_id, lat, lon, ingested_at, operator (bronze.vehicle_positions)
- [x] `not_null` — liin, lat, lon (bronze.elron_positions)
- [x] `not_null` — fuel_type, price_eur (bronze.fuel_prices)
- [x] `not_null` + `unique` — id, model, consumption (reference.vehicle_models)
- [x] `accepted_values` — operator IN ('TLT') (bronze.vehicle_positions)
- [x] `accepted_values` — fuel_type IN ('95','98','Diesel','electric','CNG') (bronze.fuel_prices)
- Tulemused: PASS=16 WARN=0 ERROR=0

**Dashboard (Superset 6.0):**
- [x] Tallinn transport kaart (deck.gl, OpenStreetMap)
- [x] Elroni rongid tabel (reis, liin, kiirus, hilinemine)
- [x] Laevastiku kokkuvõte tabel
- [x] Päevane kütusekulu tabel
- [x] Kütusehinna muutus tabel
- [x] Aktiivsed sõidukid (bus, tram)
- [x] Auto-setup skript (`setup_superset.py`)

### Tulemused
- 500+ TLT sõidukit reaalajas kaardil
- 23 Elroni rongi reaalajas
- ~184,000€/päev hinnanguline kütusekulu (diesel+CNG+hybrid)
- 109 marsruuti (81 TLT + 28 Elron)

### Kontrollpunkt
```
docker compose up -d --build
docker exec transport-pipeline python scripts/setup_superset.py
# → http://localhost:8088 (admin / .env parool)
```

### Teadaolevad piirangud
- GTFS esialgne laadimine ~5 min (1.17M stop_times rida)
- Elektri hind = Nord Pool börsihind, mitte tegelik tarbijahind
- Kütusekulu täpsus ±25% (nominaalne tarbimine, hinnanguline km)

---

## Sprint 3 — projekti lõpetamine
**Periood:** 01.06–07.06.2026 | **Staatus:** ✅ Valmis

### Mis muutus võrreldes Sprint 2-ga

Sprint 2 kütusekulu mudel kasutas hinnangulisi kilomeetreid (225 km/päev buss, 800 km/päev rong).
Sprint 3-s asendati need täpsete GTFS shapes geomeetriaga — iga marsruudi tegelik pikkus km-des.
Lisaks selgus andmetega töötades, et TLT GPS feed ei suuda tuvastada kütuse tüüpi sõiduki
tasandil, mistõttu busside kütusekulu arvutatakse laevastiku proportsioonide põhjal.

### Andmevoogude täiustused

**GTFS shapes integratsioon:**
- [x] `reference.gtfs_shapes` — TLT 32,272 + Elron 23,905 kujupunkti
- [x] `gold.route_distances` — tegelik marsruudi pikkus GTFS shapes põhjal (92 marsruuti)
- [x] `gold.route_daily_km` — planeeritud päevased km nädalapäeva teenuse järgi (95 marsruuti)
- [x] Hinnangulised km asendatud tegelikega: Tallinn–Narva ~418 km RT, Tallinn–Tartu ~380 km RT

**Kütusekulu mudeli parandused:**
- [x] Elroni `line_type_code` parandatud: 2→4 (rong), varem näidati bussina
- [x] TLT busside kütusekulu arvutatakse kütuse tüübi kaupa eraldi (CNG/diesel/elekter/hübriid)
- [x] `gold.fuel_with_discount` — lepingulised hinnad operaatori järgi; elektri override (Elron 0.10, TLT 0.12, eraisik 0.17 €/kWh)
- [x] CNG hinna viga parandatud: scraper tagastas 1.996 €/kg → korrigeeritud 1.199 €/kg (Alexela mai 2026)
- [x] Aktiivsed sõidukid loetakse viimase hetktõmmise järgi, mitte päeva kumulatiivselt

**Andmekvaliteedi parandused:**
- [x] TLT GPS latin-1 enkodeering parandatud (`r.encoding = 'latin-1'`) — eesti tähed õiged
- [x] Elroni duplikaatread eemaldatud: API tagastas iga rongi 2x hetktõmmise kohta
- [x] `normalise_liin` makro: "Tartu-Tallinn" → "Tartu - Tallinn" (ühtne vorming)
- [x] `gold.route_distances` grupeeritud `route_long_name` järgi — duplikaatmarsruudid eemaldatud

### Uued gold mudelid

| Mudel | Äriküsimus |
|---|---|
| `gold.route_distances` | Kui pikk on iga marsruut tegelikult km-des? |
| `gold.route_daily_km` | Kui palju km planeeritakse iga päev sõita? |
| `gold.fuel_with_discount` | Mis on operaatorite tegelik kütuse hind lepinguga? |
| `gold.elron_delays` | Millised Elroni rongid hilinenevad ja kui palju? |
| `gold.vehicle_delays` | Kui lähedal on TLT sõidukid peatustele praegu? |
| `gold.vehicle_speed` | Kui kiiresti sõidavad sõidukid ja kus on ummikud? |

### dbt — lõplik seis

- **13 mudelit** (7 Sprint 2 + 6 Sprint 3)
- **PASS=18 WARN=0 ERROR=0** (kõik testid läbitud)
- `tests:` → `data_tests:` uuendatud (dbt 1.8 nõue)
- `silver.vehicle_positions` inkrementaalne (unique_key: id)

### Jõudluse optimeerimine

| Toiming | Enne | Pärast | Meetod |
|---|---|---|---|
| `silver.vehicle_positions` | 245s | **1s** | Inkrementaalne materjaliseerimine |
| `gold.vehicle_speed` | 333s | **0.5s** | Tasapinnaline kaugusvalem + 2h eelfilter |
| dbt run kokku | **578s** | **4.42s** | Kõik optimeerimised koos |
| Bronze puhastus | puudus | **iga päev 03:30** | Scheduler cleanup (7 päeva säilitamine) |
| Konteineri ajatsoon | UTC | **EEST** | `TZ=Europe/Tallinn` |
| dbt loop | katkes | **töötab** | `sleep` sekundites, mitte minutites |

### Dashboard (Superset 6.0.0)

**4 rolliõigustega näidikulauda, automaatselt seadistatav:**

| Näidikulaud | Kasutaja | Sisu |
|---|---|---|
| Public Transport - Estonia | `public_user` | TLT + Elron kaardid, kütuse hinnad |
| TLT - Operatiivanalüüs | `tlt_analyst` | Kiirus, ummikud, kütusekulu, marsruudid |
| Elron - Analüüs | `elron_analyst` | Hilinemised, marsruudid, kütusekulu |
| Admin - Pipeline Monitooring | `data_engineer` | Kõik mudelid, lepingulised hinnad |

- **35 graafikut** (tabelid, sektordiagrammid, tulpdiagrammid, kaardid)
- **deck.gl kaardid** — TLT sõidukid Tallinnas + Elroni rongid üle Eesti
- `setup_superset.py` — loob kõik automaatselt (andmebaas, datasette, graafikud, näidikulauad, rollid, kasutajad)

### Tulemused (Sprint 3 lõpp)

| Mõõdik | Väärtus |
|---|---|
| dbt mudelid | 13 |
| dbt testid | PASS=18 WARN=0 ERROR=0 |
| dbt run aeg | **4.42s** (oli 578s) |
| TLT aktiivsed sõidukid | ~460–580 päeval |
| Elroni aktiivsed rongid | 11–20 päeval |
| TLT busside kütusekulu | ~47,000–50,000 €/päev |
| Elroni kütusekulu | ~700–1,100 €/päev |
| Näidikulaudu | 4 |
| Graafikuid | 35 |
| Kasutajaid | 5 (admin + 4 rolli) |

### Kontrollpunkt (täielik taaskäivitamine)

```bash
git clone https://github.com/danikus555/public-transport-analytics.git
cd public-transport-analytics
cp .env.example .env
# Muuda .env paroolid
docker compose up -d
# Oota ~90s kuni Superset initsialiseerub
docker exec transport-pipeline python scripts/setup_superset.py
# Dashboard: http://localhost:8088
```

### Teadaolevad piirangud

| Piirang | Selgitus |
|---|---|
| TLT GPS-il puudub hilinemise väli | Busside/trammide täpset graafikust kõrvalekallet ei saa arvutada — ainult peatuse lähedus 500m |
| TLT GPS ei tuvasta sõiduki mudelit | Busside kütusekulu arvutatakse laevastiku proportsioonidena, mitte sõiduki täpselt |
| CNG hind — API puudub | Alexela ei paku masinloetavat hinda; uuendatakse käsitsi DB-s |
| Elektri hind volatiilne | Nord Pool börsihind muutub tunnis; tegelik hind on `fuel_with_discount` tabelis |
| Superset CE rollipõhine ligipääs | Gamma roll näeb kõiki avaldatud näidikulaudu — per-näidikulaud isolatsioon nõuab Enterprise't |
| Ühe sõlme andmebaas | pgduckdb töötab ühe konteinerina — ei sobi kõrge käideldavuse tootmiskeskkonnale |
| GTFS-RT puudub TLT jaoks | TLT reaalajas graafikuandmeid pole — ainult GPS positsioonid |