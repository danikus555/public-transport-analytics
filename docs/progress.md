# Progress

## Sprint 1 — planeerimine ja arhitektuur
**Periood:** 18.05–24.05.2026 | **Staatus:** ✅ Esitatud

### Tehtud
- [x] Äriküsimus ja mõõdikud defineeritud
- [x] Andmeallikad kaardistatud (GPS, kütus)
- [x] Ligipääsud kontrollitud praktikas (GPS feed vastab, teadmiseks.ee avalikult ligipääsetav)
- [x] Arhitektuuriskeem joonistatud (Mermaid, docs/arhitektuur.md)
- [x] Andmebaasi kihid (bronze/silver/gold) kirjeldatud
- [x] Riskid tuvastatud (2 riski koos maandamisega)
- [x] Privaatsus ja turve kirjeldatud (.env + .gitignore)
- [x] GitHub repo loodud: https://github.com/danikus555/public-transport-analytics

---

## Sprint 2 — andmevoog ja transformatsioonid
**Periood:** 25.05–07.06.2026 | **Staatus:** 🔄 Alustamata

### Plaan
- [ ] Docker Compose üles (postgres + pipeline konteiner)
- [ ] DAG: gps — GPS sissevõtt iga 60s, bronze + IN/gps/
- [ ] DAG: fuel — kütusehindade scraper, bronze + IN/fuel/
- [ ] dbt silver mudelid (vehicle_positions, fuel_prices)
- [ ] dbt gold mudelid (route_activity, fuel_prices_daily)
- [ ] Dashboard tööriist valitud ja ühendatud gold skeemiga
- [ ] 3 kasutajarolli dashboardis (Public, Analyst, Operator)

---

## Sprint 3 — testimine ja viimistlemine
**Periood:** 08.06–21.06.2026 | **Staatus:** ⏳ Planeerimata

### Plaan
- [ ] pytest testid DAG skriptidele
- [ ] dbt schema testid (not_null, unique, accepted_values)
- [ ] Dashboard auto-refresh
- [ ] README käivitusjuhend kontrollitud
- [ ] Git ajalugu korras (sisukad commit-sõnumid kõigis sprintides)