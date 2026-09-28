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
