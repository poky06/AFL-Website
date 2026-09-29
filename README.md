# AFL Kader & Statistiken

Öffentliche Website der Austrian Football League mit Daten aus Clubee.

## Aufbau

| Datei | Zweck |
|---|---|
| `index.html` | Die Website. Liest `data/afl.json`; solange die Datei fehlt, zeigt sie Demo-Daten. |
| `scripts/sync.mjs` | Holt die Daten aus Clubee und schreibt nur freigegebene Felder in `data/afl.json`. |
| `.github/workflows/sync.yml` | Startet den Sync jeden **Mittwoch um 12:00 Uhr (Wien)** oder manuell. |
| `data/afl.json` | Wird vom Sync erzeugt. Nicht von Hand bearbeiten. |

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

## Lokal testen

```bash
export CLUBEE_TOKEN='...'
SEASON_ID=217 node scripts/sync.mjs
python3 -m http.server 8000   # dann http://localhost:8000 öffnen
```
