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

**Dashboard (Superset 6.0):**
- [x] Tallinn transport kaart (deck.gl, OpenStreetMap) käsitsi.
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

### Mis takistab
GTFSi link oli muutunud ja alguses ei töötanud, nüüd asub teisel addressil.
Praegu ei ole blokeerivaid probleeme.

---

## Sprint 3 — täiustused ja deploy
**Periood:** 01.06–7.06.2026 | **Staatus:** ⏳ Planeeritud

### Järgmised sammud
- [ ] GTFS shapes.txt — täpne marsruudi pikkus km
- [ ] Ummik tuvastus (<500m, kiirus=0, >7min) bonuseks
- [ ] Elektri tegelik tarbijahind lepinguline arvutamine
- [ ] dbt testid (not_null, unique, accepted_values)
- [ ] pytest testid pipeline skriptidele