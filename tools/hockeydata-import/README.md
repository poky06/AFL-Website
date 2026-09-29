# Hockeydata-Import (AFL 2014–2025)

Erzeugt `data/archive` aus dem AFBÖ-Datenexport von Hockeydata (Stand 31.12.2025).

```bash
python3 build_archive.py <DataPackage-Ordner> <Zielordner data/archive> <data/afl.json> <Berichtsordner>
```

- `egrep.py` liest die EGREP-AF-Spielprotokolle (XML) und bildet die Hockeydata-Rechenregeln nach
  (Raumgewinn = Endpunkt des Spielzugs − Line of Scrimmage; Pässe inkl. Strafen, Läufe/Sacks ohne Strafen,
  Kickoff-Returns inkl., Punt-Returns ohne Strafen; 3rd Downs ohne Kneel-downs und Sacks).
- `dedupe.py` findet doppelte Spieler-IDs (Schreibweisen, vertauschte Namen, Geburtsdatum-Tippfehler); zwei IDs,
  die im selben Spiel im Kader stehen, gelten nie als dieselbe Person. Bestätigte/abgelehnte Paare stehen in
  `CONFIRMED_DUPES` / `REJECTED_DUPES` in `build_archive.py`.
- `build_archive.py` übernimmt die offiziellen Hockeydata-Werte, ergänzt fehlende Clubee-Spalten aus den
  Protokollen und verknüpft Archiv-Spieler mit Clubee-Spielern (Name + Geburtsdatum).
- Der Berichtsordner enthält `Pruefliste-Spielerzuordnung.csv`, `Doppelte-IDs-zusammengefuehrt.csv` und
  `Pruefliste-Doppelte-IDs.csv` (mit Geburtsdaten – **nicht** ins Repository laden).
