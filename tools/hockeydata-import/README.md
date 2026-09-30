# Archiv-Import (AFL 2004–2025)

Erzeugt `data/archive` aus dem AFBÖ-Datenexport von Hockeydata (2014–2025, Stand 31.12.2025) und den
StatCrew-Seiten der AFBÖ-Website (2004–2013).

```bash
python3 build_archive.py <DataPackage-Ordner> <Zielordner data/archive> <data/afl.json> <Berichtsordner> [Ordner Statistiken mit Unterordnern 2004 … 2013]
```

- `egrep.py` liest die EGREP-AF-Spielprotokolle (XML) und bildet die Hockeydata-Rechenregeln nach
  (Raumgewinn = Endpunkt des Spielzugs − Line of Scrimmage; Pässe inkl. Strafen, Läufe/Sacks ohne Strafen,
  Kickoff-Returns inkl., Punt-Returns ohne Strafen; 3rd Downs ohne Kneel-downs und Sacks).
- `dedupe.py` findet doppelte Spieler-IDs (Schreibweisen, vertauschte Namen, Geburtsdatum-Tippfehler); zwei IDs,
  die im selben Spiel im Kader stehen, gelten nie als dieselbe Person. Bestätigte/abgelehnte Paare stehen in
  `CONFIRMED_DUPES` / `REJECTED_DUPES` in `build_archive.py`.
- `statcrew.py` liest StatCrew-Seiten: Teamseiten (Saisonsummen inkl. Einsätze, Fumbles und Sacks je Spiel) und
  Boxscores. Boxscores von Spielen, die schon in den Teamseiten stecken, dienen nur zur Kontrolle; Seiten mit dem
  Hinweis „Statistics do not include N post-season game(s)“ werden um die Play-off-Boxscores ergänzt. Unterschiedlich
  erfasste Kurzformen desselben Spielers im selben Team (z. B. „M.Wenzel“ / „WENZEL M.“) werden zusammengeführt,
  Einträge nur mit Trikotnummer bleiben unberücksichtigt (zählen aber in den Teamwerten). Teamseiten ohne
  Spiel-für-Spiel-Teil (2011) haben nur volle Namen: die Kurzformen der Boxscores werden dann über den vollen Namen
  zugeordnet („C.Gross“ → Christoph Gross, auch bei Tippfehlern), Sk/FUM je Spieler und SP bleiben leer.
- Ältere Seiten (2004–2007) schreiben beim Passing „Att-Cmp-Int“ (statt „Cmp-Att-Int“) und Sacks in zwei Spalten; beides
  wird erkannt. Spiel-für-Spiel-Werte von Play-off-Spielen, die in den Saisonsummen fehlen (2004), werden bei Sacks und
  Fumbles abgezogen. Punkte = TD × 6 + XP + 3 × FG + 2 × (2-Pt + Safety + DXP) wie in der AFBÖ-Rangliste.
  Saisonweise Korrekturen der Quelle stehen in `STATCREW_SEASONS[…]['fixes']` (z. B. Lions 2007).
- `build_archive.py`: `ID_FIX` schreibt Hockeydata-IDs um, unter denen die Werte einer anderen Person stehen
  (ID 28 „Felix Tomenendal“ = Dylan Potts, QB Dragons 2017 / Black Panthers 2019).
- `build_archive.py` übernimmt die offiziellen Hockeydata-Werte, ergänzt fehlende Clubee-Spalten aus den
  Protokollen und verknüpft Archiv-Spieler mit Clubee-Spielern (Name + Geburtsdatum).
- Der Berichtsordner enthält `Pruefliste-Spielerzuordnung.csv`, `Doppelte-IDs-zusammengefuehrt.csv` und
  `Pruefliste-Doppelte-IDs.csv` (mit Geburtsdaten – **nicht** ins Repository laden) sowie `Pruefliste-StatCrew-Saisons.csv`
  (Zuordnung der Spieler 2004–2013 zu den Archiv-Personen; bestätigte Fälle in `LINKS_STATCREW`).
