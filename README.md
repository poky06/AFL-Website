# AFL Kader & Statistiken

Öffentliche Website der Austrian Football League mit Daten aus Clubee.

## Aufbau

| Datei | Zweck |
|---|---|
| `index.html` | Die Website. Liest `data/afl.json`; solange die Datei fehlt, zeigt sie Demo-Daten. |
| `scripts/sync.mjs` | Holt die Daten aus Clubee und schreibt nur freigegebene Felder in `data/afl.json`. |
| `.github/workflows/sync.yml` | Startet den Sync jeden **Mittwoch um 12:00 Uhr (Wien)** oder manuell. |
| `data/afl.json` | Wird vom Sync erzeugt. Nicht von Hand bearbeiten. |
| `data/career.json`, `data/history/` | Vom Sync erzeugt: Karrierewerte und die Statistiken früherer Clubee-Saisons (für die Saisonauswahl). |
| `data/archive/` | Statistik-Archiv 2014–2025 aus Hockeydata (fester Datenstand, siehe unten). |
| `tools/hockeydata-import/` | Skript, mit dem `data/archive` aus dem Hockeydata-Export erzeugt wurde. |

Auf die Website gelangen ausschließlich: Vor- und Nachname, Trikotnummer, Position, Geburtsdatum,
Nationalität (Kürzel), Foto, Lizenzklasse und Team – und nur für Mitglieder mit
„auf Website anzeigen“ in Clubee. Adressen, Telefonnummern, E-Mails und Dokumente werden
im Sync verworfen und nie gespeichert.

## Inhalte pflegen (in `index.html`)

Ganz oben im Skriptteil von `index.html` steht ein Block **„Konfiguration – hier pflegen“**:

| Eintrag | Wofür |
|---|---|
| `TEAM_WEBSITES` | Offizielle Vereins-Websites (Clubee-Team-ID → Adresse). Fehlt ein Team, erscheint kein Website-Knopf. |
| `LAST_BOWL` | Banner auf der Startseite (letzte Austrian Bowl mit Ergebnis, Datum, Ort). |
| `AUSTRIAN_BOWL` | Nächste Austrian Bowl: Datum, Venue, Adresse, Ticket-Link, Programm. |
| `SOCIAL` | Links zu Instagram, Facebook, YouTube. |
| `INSTAGRAM_POSTS` | Optional: Links zu einzelnen Instagram-Beiträgen, die in der Fußzeile eingebettet werden. |
| `TEAM_STYLE` | Vereinsfarben und Kurznamen. |
| `TEAM_LOGOS` | Optional: eigene hochauflösende Logos je Team (Datei im Ordner `logos` ablegen, z. B. `"354986": "logos/graz-giants.png"`). |
| `MVPS`, `CHAMPIONS` | MVP- und Meisterliste. |

Spielplan, Playoff-Baum, Tabelle inkl. Strength of Schedule, Teamseiten und League Leaders
kommen automatisch aus den Clubee-Daten.

**Strength of Schedule (SOS):** kombinierte Siegquote aller Gegner eines Teams im Grunddurchgang
(gespielte und noch offene Spiele, jede Begegnung zählt einzeln) auf Basis der aktuellen Tabelle.
Die Berechnung läuft im Browser und ändert sich mit jedem Sync automatisch mit.

## Sprachen (Deutsch / Englisch)

Die Seite erscheint auf **Deutsch**, wenn die bevorzugte Sprache des Browsers Deutsch ist, sonst auf **Englisch**.
Über den Umschalter **DE | EN** oben rechts kann man wechseln; die Wahl merkt sich der Browser.

Alle Übersetzungen stehen ganz oben im Skriptteil von `index.html`:
- `EN` – feste Texte (Deutsch → Englisch)
- `EN_RULES` – Texte mit Zahlen oder Namen (z. B. „12 von 50 Spielern“)

Kommt ein neuer deutscher Text auf die Seite, dort die englische Fassung ergänzen – sonst erscheint er in der
englischen Version auf Deutsch. Spieler- und Teamnamen sowie die Statistik-Kategorien aus Clubee werden nicht übersetzt.

## Einrichtung (einmalig)

1. **Repository anlegen** auf github.com (z. B. `afboe/afl-website`) und alle Dateien dieses
   Ordners hochladen – inklusive des versteckten Ordners `.github`.
2. **API-Key hinterlegen:** Settings → Secrets and variables → Actions → *New repository secret*
   - Name: `CLUBEE_TOKEN`
   - Wert: der Clubee-Key (bitte einen **neuen** Key von Clubee verwenden, nicht den Test-Key)
3. **Saison einstellen:** Settings → Secrets and variables → Actions → Reiter *Variables* →
   *New repository variable*
   - `SEASON_ID` = `217` (Saison 2026) bzw. `219` (Saison 2027)
   - optional `COMPETITION_ID` (Standard `13931` = AFL) und `CLUBEE_WEBSITE` (Standard `afbo`)
4. **Ersten Sync starten:** Reiter *Actions* → *Clubee-Sync* → *Run workflow*.
   Nach ca. 2–5 Minuten liegt `data/afl.json` im Repository.
5. **Website veröffentlichen**, eine der beiden Varianten:
   - **GitHub Pages:** Settings → Pages → Source: *Deploy from a branch* → Branch `main`, Ordner `/ (root)`.
   - **Netlify oder Vercel:** Repository verbinden, kein Build-Befehl, Ausgabeordner = Wurzelverzeichnis.
   Beide veröffentlichen nach jedem Sync automatisch neu.
6. **Eigene Domain** (z. B. `spieler.afboe.at`) in den Einstellungen des Hosters eintragen.

## Manueller Sync durch einen Admin

Reiter *Actions* → *Clubee-Sync* → *Run workflow* → *Run workflow*.
Optional: andere Saison-ID eintragen oder „Plausibilitätsprüfung überspringen“ aktivieren.

Admins brauchen einen GitHub-Account mit Schreibrechten auf das Repository
(Settings → Collaborators).

## Hinweise

- **Zeitpunkt:** GitHub startet geplante Läufe manchmal einige Minuten verspätet.
- **Schutz vor leeren Seiten:** Liefert Clubee keine Spieler oder fällt die Spielerzahl um mehr als
  die Hälfte, bricht der Sync ab und die alte Datei bleibt online. Bei gewollten großen Änderungen
  (z. B. Saisonwechsel) den manuellen Sync mit „Plausibilitätsprüfung überspringen“ starten.
- **Fehlgeschlagene Läufe** meldet GitHub per E-Mail an die Repository-Admins.
- **Protokolle** enthalten nur Zählungen, keine Personendaten. Bei einem öffentlichen Repository
  sind sie trotzdem für alle sichtbar – das ist so gewollt unbedenklich.
- **Trainerrollen:** Clubee liefert Staff-Rollen teils nur als interne Kürzel (`position_1` …).
  Unbekannte Rollen erscheinen als „Trainerstab“. Die Zuordnung steht in `STAFF_ROLE` in
  `scripts/sync.mjs` und kann ergänzt werden.
- **Tabelle:** Die Spaltennamen kommen aus Clubee. Nach dem ersten echten Sync prüfen, ob sie passen.
- **Mehr als 200 Spieler je Kategorie:** Der Sync lädt die Statistik-Kategorien jetzt seitenweise vollständig
  (vorher brach er nach 200 Spielern ab).

## Statistik-Archiv 2004–2025 (AFBÖ/StatCrew und Hockeydata)

Bis 2013 wurden die AFL-Statistiken mit StatCrew auf der AFBÖ-Website veröffentlicht, 2014–2025 von Hockeydata geführt,
ab 2026 von Clubee. Das Archiv liegt in `data/archive` und wird vom Sync **nicht** verändert:

| Datei | Inhalt |
|---|---|
| `index.json` | Liste der Archiv-Saisons und der Teams (inkl. Zuordnung zu den heutigen Vereinen für Logo/Farbe) |
| `season-2004.json` … `season-2025.json` | Spieler- und Teamstatistiken je Saison, im selben Aufbau wie die Clubee-Statistiken |
| `career.json` | Karrierewerte je Archiv-Spieler (für die Detailansicht) |
| `player-map.json` | Verknüpfung Archiv-Spieler → Clubee-Spieler |

**Bezeichnungen:** Kategorien, Spaltennamen und Spaltenreihenfolge sind exakt die aus Clubee.
**Werte:** Wo Hockeydata einen offiziellen Wert hat, wird er unverändert übernommen. Spalten, die es bei
Hockeydata nicht gibt (z. B. Tgt, Ctch%, FUM, Sk beim Passing, DEF TD, Returns, Kicking, Punting sowie die
„Allowed“-Werte der Teamstatistiken), wurden aus den Spielprotokollen (EGREP-AF) berechnet. Auf der Website
sind diese Spalten gepunktet unterstrichen; der Tooltip sagt „berechnet aus den Spielprotokollen“.
Wie bei Clubee gilt in der Kategorie Defense: Tot = Solo + Ast (Ast = halbe Tackles).
Die Hockeydata-Ranglisten 2014–2018 sind unvollständig (z. B. fehlt Thomas Schnurrer 2014–2017). Spieler ohne
Ranglisten-Eintrag wurden ebenfalls aus den Spielprotokollen berechnet; ihr Name ist gepunktet unterstrichen.
Doppelte Spieler-IDs aus dem alten System (andere Schreibweise, vertauschte Vor-/Nachnamen, fehlendes oder falsches
Geburtsdatum – z. B. „Junjie Gao“ / „Jun Jie Gao“, „Curis Sven“ / „Sven Curis“) sind zu einer Person zusammengeführt
(`tools/hockeydata-import/dedupe.py`, bestätigte Fälle in `CONFIRMED_DUPES` in `build_archive.py`).

**Saisons 2004–2013:** Quelle sind die StatCrew-Seiten der AFBÖ-Website (Kopien aus der Wayback Machine):
Teamseiten mit den Saisonsummen und Boxscores der Spiele, die darin fehlen. Wie in den übrigen Archiv-Saisons zählen
die Play-offs mit, soweit es dafür eine Statistik gibt (2010–2013).
- 2013: Teamseiten (Grunddurchgang) + Boxscores von Halbfinale und Austrian Bowl XXIX – 33 Spiele.
- 2012: Teamseiten (Grunddurchgang) + Boxscores der Halbfinals – 32 Spiele. Der Boxscore der Austrian Bowl XXVIII
  fehlt.
- 2011: Teamseiten (Grunddurchgang, 6 Spiele je Team) + Boxscores der Halbfinals und der Austrian Bowl XXVII –
  24 Spiele. Die Teamseiten 2011 enthalten nur Saisonsummen (keine Spiel-für-Spiel-Seiten): Sacks je Quarterback
  (Sk) und Fumbles je Spieler (FUM) fehlen deshalb, ebenso die Spiele mit Kick/Punt (SP).
- 2010: nur Boxscores – 24 Conference-Spiele, 2 Halbfinale, Austrian Bowl XXVI (27 Spiele). Nicht gezählt werden
  Europacup-Spiele und zwei Spiele, die nicht in der AFBÖ-Conference-Statistik stehen (Liste in `STATCREW_SEASONS`).
- 2004–2009: nur Teamseiten, also nur der Grunddurchgang (2004: 21, 2005: 18, 2006: 19, 2007: 23, 2008: 18,
  2009: 28 Spiele). Für die Play-offs gibt es keine Statistik-Seiten (2004 sind sie in den Saisonsummen ausdrücklich
  nicht enthalten). 2007 und 2008 haben keine Spiel-für-Spiel-Seiten (Sk, FUM je Spieler und SP fehlen).
  2009 zählen die Spiele von Blue Devils und Lions gegen Teams der Division I mit (wie in der AFBÖ-Statistik).
  Fehler der Quelle: Die Lions-Seite 2007 zählt das Spiel Raiders – Lions (19.05., 28:0) als Lions-Sieg mit den
  Werten der Raiders – für die Lions 2007 gibt es deshalb keine Teamwerte (Spielerwerte sind nicht betroffen).
  Punkte werden wie in der AFBÖ-Rangliste aus TD, XP, FG, 2-Pt, Safety und DXP berechnet (strafverifizierte Spiele
  und Spiele ohne Statistik zählen nicht). Kontrolle: alle 956 Teamwerte der offiziellen Leaders-Seiten 2004–2009
  stimmen überein.
Nicht erfasst wurden damals Targets (Tgt, Ctch%) sowie Punts ins Aus bzw. mit Return; bei Teams mit mehreren
Kickern/Puntern ohne Boxscores fehlen die Spiele je Kicker (SP). Die Spieler sind über Name und Team mit den
Archiv-Personen verknüpft (bestätigte Fälle in `LINKS_STATCREW` in `build_archive.py`). Teams, die es heute nicht
mehr gibt (Salzburg Bulls, St. Pölten Invaders, Carinthian Lions, Carinthian Cowboys, Carinthian Falcons), haben
eigene Archiv-Teams; die Blue Devils Hohenems sind das Hockeydata-Team „Cineplexx Blue Devils“. Teamnamen 2004–2009
wie auf den damaligen Seiten (z. B. „Vikings Vienna“, „Raiders Tirol“).

**Saisonauswahl:** Spieler- und Teamstatistiken haben eine Saisonauswahl. Die aktuelle Saison kommt aus
`data/afl.json`, frühere Clubee-Saisons aus `data/history/stats-<Saison-ID>.json` (legt der Sync nach jedem Lauf
automatisch an) und 2004–2025 aus dem Archiv.
Ganz unten im Dropdown steht **All Time**: alle Saisons zusammengezählt (Archiv und Clubee). Spieler werden über
`player-map.json` zusammengeführt, Teams über den Verein (`club` in `data/archive/index.json`, bei Clubee-Teams über
den Namen). Quoten und Schnitte werden aus den Summen neu berechnet (z. B. CMP%, Y/A, FG%, Passer Rating, KR Avg),
Werte pro Spiel über alle Spiele; Schnitte ohne Grundwerte (z. B. 3D%, P Avg) sind nach Spielen gewichtet. Mit
Teamauswahl zählen bei den Spielern nur die Saisons für dieses Team. Neue Saisons kommen automatisch dazu.

**Spieler-Detailansicht:** Zeigt alle Saisons eines Spielers – Archiv und Clubee zusammen. Ehemalige Spieler
ohne Clubee-Profil sind in den alten Ranglisten ebenfalls anklickbar und öffnen ein Archiv-Profil (nur Name,
Teams und Statistiken – keine weiteren Personendaten).

**Verknüpfung korrigieren (`data/archive/player-map.json`):** Jede Zeile verbindet einen Archiv-Spieler
(`"hd<LOS-ID>"`) mit einer Clubee-Spieler-ID, z. B. `"hd2545": 979941` (Franz Korger). Verknüpft wurde
automatisch über Name + Geburtsdatum. Fehlt eine Verknüpfung, Zeile ergänzen; ist eine falsch, Zeile löschen.
Ein Clubee-Spieler darf mehrere Archiv-Schlüssel haben (Doppel-Einträge im alten System). Die Clubee-ID steht in
`data/afl.json` bei `players[].id`, der Archiv-Schlüssel in `data/archive/career.json` unter `people`.
Änderungen wirken sofort, ein Sync ist nicht nötig.

**Neu erzeugen** (nur nötig, wenn sich die Rechenregeln ändern):
```bash
python3 tools/hockeydata-import/build_archive.py /pfad/zum/DataPackage data/archive data/afl.json /tmp/bericht /pfad/zu/Statistiken
```

## Lokal testen

```bash
export CLUBEE_TOKEN='...'
SEASON_ID=217 node scripts/sync.mjs
python3 -m http.server 8000   # dann http://localhost:8000 öffnen
```
