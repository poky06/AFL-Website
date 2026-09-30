#!/usr/bin/env python3
"""
Hockeydata-Archiv (AFL 2014–2025) -> Website-Dateien im Clubee-Format.

Aufruf:  python3 build_archive.py <DataPackage-Ordner> <Zielordner data/archive> <data/afl.json> [Berichtsordner]
                                  [Ordner Statistiken mit Unterordnern 2004–2013]

Quellen (alle aus dem AFBÖ-Datenexport von Hockeydata):
  PlayerStats/*, TeamStats/*          offizielle Saisonwerte (werden 1:1 übernommen)
  AFL-EGREP-Gamereports/*.xml         Spielprotokolle – daraus werden fehlende Clubee-Spalten berechnet
  GameReportsJSON/*.json              offizielle Team-Boxscores je Spiel (2023–2025)
  AlleSpieleMitErgebnis.json          Ergebnisse (Punkte, Spielstatus)
  Spieler.json, Team-Bewerb-Zuordnung.json

Saisons vor 2014 (optional, 5. Argument): StatCrew-Statistiken der AFBÖ-Website (siehe statcrew.py) – Teamseiten
und Boxscores, je Saison ein Unterordner (2004–2013). Die Spieler werden über Name und Team mit den
Archiv-Personen verknüpft; bestätigte bzw. abgelehnte Fälle stehen in LINKS_STATCREW.

Spaltennamen und -reihenfolge kommen aus der aktuellen Clubee-Datei (afl.json), damit das Archiv
exakt die Clubee-Bezeichnungen verwendet.
"""
import csv
import difflib
import glob
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import egrep  # noqa: E402
import dedupe  # noqa: E402

if len(sys.argv) < 4:
    sys.exit('Aufruf: python3 build_archive.py <DataPackage-Ordner> <Zielordner data/archive> <data/afl.json> [Berichtsordner]')
RAW, OUT, AFL_JSON = sys.argv[1], sys.argv[2], sys.argv[3]
REPORT_DIR = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.getcwd(), 'hockeydata-bericht')
STATCREW_DIR = sys.argv[5] if len(sys.argv) > 5 else None   # Ordner mit Unterordnern 2004–2013 …
os.makedirs(OUT, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

SEASONS = [str(y) for y in range(2014, 2026)]
# Vereine, die es in Clubee (2026) noch gibt -> Logo/Farbe/Teamseite der Website verwenden
CLUB_KEY = {1: 'dragons', 2: 'giants', 3: 'panthers', 4: 'vikings', 5: 'raiders', 40: 'ducks'}
SHORT = {1: 'Dragons', 2: 'Giants', 3: 'Black Panthers', 4: 'Vikings', 5: 'Raiders', 16: 'Blue Devils',
         17: 'Silverhawks', 18: 'Rangers', 24: 'Steelsharks', 27: 'Monarchs', 29: 'Thunder', 32: 'Bears',
         40: 'Ducks', 42: 'Patriots', 54: 'Knights'}
CALC_NOTE = ' – berechnet aus den Spielprotokollen (Hockeydata-Archiv)'


def rnd(v, n=1):
    if v is None:
        return None
    v = round(float(v), n)
    return int(v) if v == int(v) else v


def div(a, b, f=1.0, n=1):
    return rnd(a / b * f, n) if b else None


def norm(s):
    s = str(s or '').replace('ß', 'ss')
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def clean_name(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


# ---------------------------------------------------------------- Stammdaten
afl = json.load(open(AFL_JSON))
CLUBEE_COLS = {}
for kind in ('players', 'teams'):
    for b in afl['stats'][kind]:
        CLUBEE_COLS[(kind, b['name'])] = b['columns']

all_games = {g['GameGuid']: g for g in json.load(open(f'{RAW}/AlleSpieleMitErgebnis.json')) if g['LeagueId'] == 1}
spieler = {p['PlayerId']: p for p in json.load(open(f'{RAW}/Spieler.json'))}

team_name = {}          # (season, hd_team_id) -> Name
for d in json.load(open(f'{RAW}/Team-Bewerb-Zuordnung.json')):
    if d['LeagueId'] != 1:
        continue
    yr = d['SeasonName'][-4:]
    for t in d['Teams']:
        if t['TeamId'] in SHORT:
            team_name[(yr, t['TeamId'])] = clean_name(t['SeasonalTeamName'] or t['GlobalTeamName'])


def tname(yr, tid):
    return team_name.get((yr, tid)) or team_name.get(('2025', tid)) or f'Team {tid}'


_official_cache = {}
SUM_FIELDS = ('games', 'attempts', 'complete', 'intercepted', 'netYards', 'touchdowns', 'number', 'yards',
              'yardsGained', 'yardsLost', 'soloTackles', 'assistTackles', 'totalTackles', 'tackleForLoss',
              'tackleForLossYards', 'interceptions', 'fumblesForced', 'passBreakups', 'sacks')


def official(yr, kind, cat):
    key = (yr, kind, cat)
    if key in _official_cache:
        return _official_cache[key]
    base = 'PlayerStats' if kind == 'players' else 'TeamStats'
    path = f'{RAW}/{base}/Saison {yr}/{cat}.json'
    rows = json.load(open(path))['data']['rows'] if os.path.exists(path) else []
    if kind == 'players':
        rows = [dict(r, id=fix_id(r['id'])) if r['id'] in ID_FIX else r for r in rows]
    if kind == 'players' and 'canon_map' in globals():
        merged = {}
        for r in rows:
            r = dict(r)
            r['id'] = canon(r['id'])
            k = (r['id'], r['teamId'])
            if k not in merged:
                merged[k] = r
                continue
            m = merged[k]   # dieselbe Person unter zwei IDs im selben Team: Werte addieren
            for f in SUM_FIELDS:
                if f in m:
                    m[f] = (m.get(f) or 0) + (r.get(f) or 0)
            if 'longest' in m:
                m['longest'] = max(m.get('longest') or 0, r.get('longest') or 0)
            if cat == 'LeaderPassing' and m['attempts']:
                m['quarterbackRatingNcaa'] = (8.4 * m['netYards'] + 330 * m['touchdowns'] + 100 * m['complete']
                                              - 200 * m['intercepted']) / m['attempts']
            report['official_merged'].append((yr, cat, r['id']))
        rows = list(merged.values())
    _official_cache[key] = rows
    return rows


gamereports = {}
for f in glob.glob(f'{RAW}/GameReportsJSON/*/*.json'):
    gamereports[os.path.basename(f)[:-5]] = f

# ---------------------------------------------------------------- Spielprotokolle
# Hockeydata-IDs, unter denen die Werte einer anderen Person erfasst sind (vom Ligamanagement bestätigt):
# alle Einträge der ID werden der richtigen Person zugeschrieben
ID_FIX = {   # bestätigt am 29.09.2026
    28: 374,     # "Felix Tomenendal" (QB Dragons 2017, Black Panthers 2019) = Dylan Potts (Rangers 2018)
}


def fix_id(pid):
    return ID_FIX.get(pid, pid)


def fix_game_ids(g, P, PS):
    if not any(i in ID_FIX for i in list(g.names) + list(P) + list(PS)):
        return P, PS
    P2 = defaultdict(egrep._dd)
    for pid, st in P.items():
        for k, v in st.items():
            if k.endswith('_long'):
                P2[fix_id(pid)][k] = max(P2[fix_id(pid)].get(k, -999), v)
            else:
                P2[fix_id(pid)][k] += v
    g.on_roster = {sd: {fix_id(p) for p in ids} for sd, ids in g.on_roster.items()}
    g.roster = {sd: {j: fix_id(p) for j, p in r.items()} for sd, r in g.roster.items()}
    g.names = {fix_id(p): v for p, v in g.names.items()}
    g.pos = {fix_id(p): v for p, v in g.pos.items()}
    return P2, {fix_id(p): sd for p, sd in PS.items()}


print('Spielprotokolle einlesen …')
parsed = defaultdict(list)
seen = set()
for f in sorted(glob.glob(f'{RAW}/AFL-EGREP-Gamereports/*/*.xml')):
    g, P, PS, T = egrep.parse(f)
    if g.guid in seen or g.guid not in all_games:
        continue
    seen.add(g.guid)
    P, PS = fix_game_ids(g, P, PS)
    parsed[all_games[g.guid]['SeasonName'][-4:]].append((g, P, PS, T))
print({k: len(v) for k, v in sorted(parsed.items())})


# ---------------------------------------------------------------- Doppelte Spieler-IDs (siehe dedupe.py)
# Vom Ligamanagement bestätigte bzw. abgelehnte Paare (LOS-IDs); ergänzen, wenn die Prüfliste bearbeitet wurde
CONFIRMED_DUPES = [   # bestätigt am 29.09.2026
    (743, 749),     # Alexander Didlin = Alexander Dildin (Black Panthers 2016)
    (1177, 1178),   # Petr Vitorec = Petr Vitovec (Black Panthers)
    (1342, 1344),   # Pavlo Hornik = Pavol Hornik (Monarchs 2018)
    (990, 996),     # Florian Mathes = Florian Methes (Dragons)
    (559, 1263),    # Jan Beran = Jan Beranek (Black Panthers)
    (413, 7898),    # Valentin Mayer = Valentin Mayr (Rangers/Steelsharks)
    (467, 842),     # Michael Hinterwirth-Haider = Michael Haider (Vikings)
    (423, 6224),    # Adrian Soto = Adrian Soto Espinosa (Steelsharks)
    (1314, 8080),   # Patrick Kenney (Silverhawks 2018 / Ducks 2023)
    (49, 2219),     # Michael Hantich (Dragons 2017 / Ducks 2022–2025)
    (748, 1956),    # Charles = Charleus Dieuseul (Vikings / Rangers)
    (14, 6151),     # Daniel Brandmayer = Daniel Brandmayr (Dragons / Rangers, Vikings)
    (345, 658),     # Amr Ali = Ali Amr (Vikings / Rangers)
    (296, 630),     # Lemay Marqueira = Lemay Maqueira Palau (Raiders 2018 / 2019, 2022)
]
REJECTED_DUPES = []
dup_records = {}
for yr_, lst_ in parsed.items():
    for g, P, PS, T in lst_:
        for side in ('Home', 'Away'):
            tid = g.team[side][0]
            for pid in g.on_roster[side]:
                if pid not in spieler:
                    continue
                sp_ = spieler[pid]
                r = dup_records.setdefault(pid, {'first': (sp_.get('Firstname') or '').strip(),
                                                 'last': (sp_.get('Lastname') or '').strip(),
                                                 'birth': (sp_.get('Birthdate') or '')[:10], 'games': set(),
                                                 'seasons': set(), 'team_by_season': defaultdict(set), 'jerseys': set()})
                r['games'].add(g.guid)
                r['seasons'].add(yr_)
                r['team_by_season'][yr_].add(tname(yr_, tid))
                r['jerseys'].add(g.names.get(pid, ('', '', ''))[2])
dup_groups, dup_merged, dup_review, canon_map = dedupe.find_duplicates(dup_records, CONFIRMED_DUPES, REJECTED_DUPES)
print('Doppelte IDs:', sum(len(v) - 1 for v in dup_groups.values()), 'zusammengeführt,', len(dup_review), 'zur Prüfung')


def canon(pid):
    return canon_map.get(pid, pid)


# Spielprotokolle auf die kanonische ID umschreiben
for yr_, lst_ in parsed.items():
    for idx, (g, P, PS, T) in enumerate(lst_):
        P2 = defaultdict(egrep._dd)
        for pid, st in P.items():
            c = canon(pid)
            for k, v in st.items():
                if k.endswith('_long'):
                    P2[c][k] = max(P2[c].get(k, -999), v)
                else:
                    P2[c][k] += v
        g.on_roster = {s: {canon(p) for p in ids} for s, ids in g.on_roster.items()}
        lst_[idx] = (g, P2, {canon(p): s for p, s in PS.items()}, T)


def in_team_set(guid):
    """Hockeydata-Teamwerte zählen strafverifizierte/umgewertete Spiele (Status 10/31) nicht mit."""
    return all_games[guid]['GameExtendedStatus'] in (None, 0)


# ---------------------------------------------------------------- Spieler je Saison
def player_season(yr):
    agg = defaultdict(Counter)
    longs = defaultdict(dict)
    games = defaultdict(set)
    kick_games = defaultdict(set)
    punt_games = defaultdict(set)
    team_cnt = defaultdict(Counter)
    for g, P, PS, T in parsed[yr]:
        for side in ('Home', 'Away'):
            for pid in g.on_roster[side]:
                games[pid].add(g.guid)
                team_cnt[pid][g.team[side][0]] += 1
        for pid, st in P.items():
            for k, v in st.items():
                if k.endswith('_long'):
                    longs[pid][k] = max(longs[pid].get(k, -999), v)
                else:
                    agg[pid][k] += v
            if st.get('fga', 0) + st.get('xpa', 0) > 0:
                kick_games[pid].add(g.guid)
            if st.get('punt', 0) > 0:
                punt_games[pid].add(g.guid)
            side = PS.get(pid)
            if side and pid not in g.on_roster[side]:
                games[pid].add(g.guid)
                team_cnt[pid][g.team[side][0]] += 1
    return agg, longs, games, kick_games, punt_games, team_cnt


def cols(kind, name):
    return CLUBEE_COLS[(kind, name)]


def block(kind, name, rows, calc_titles, sort_title, extra_cols=None):
    columns = [dict(c) for c in (extra_cols or cols(kind, name))]
    titles = [c.get('title') or c['label'] for c in columns]
    calc_idx = []
    for i, c in enumerate(columns):
        if c.get('title') in calc_titles or c['label'] in calc_titles:
            calc_idx.append(i)
    out_rows = []
    for r in rows:
        vals = [r['v'].get(t) for t in titles]
        out_rows.append({k: v for k, v in r.items() if k != 'v'} | {'values': vals})
    si = titles.index(sort_title)
    out_rows.sort(key=lambda r: (r['values'][si] is None, -(r['values'][si] or 0)))
    return {'name': name, 'columns': columns, 'calc': calc_idx, 'rows': out_rows}


KICK_COLS = cols('players', 'Kicking')
PUNT_COLS = cols('players', 'Punting')

people = {}             # hd-Schlüssel -> {name, ids, teams{yr:[...]}}
calc_rows = defaultdict(list)   # hd-Schlüssel -> ["2016|Defense", …] (ganz berechnete Saisonzeilen)
career = defaultdict(lambda: defaultdict(dict))   # key -> yr -> cat -> values
seasons_out = {}
report = defaultdict(list)


def person_key(pid):
    return f'hd{pid}'


def display_name(ids):
    """Schreibweise mit den meisten Saisons (bei Gleichstand die jüngere) + alle Varianten."""
    def nm(i):
        sp = spieler.get(i, {})
        return clean_name(f"{sp.get('Firstname', '')} {sp.get('Lastname', '')}") or f'Spieler {i}'
    ranked = sorted(ids, key=lambda i: (len(dup_records.get(i, {}).get('seasons', ())),
                                        max(dup_records.get(i, {}).get('seasons', {'0'}))), reverse=True)
    aliases = []
    for i in ranked:
        if nm(i) not in aliases:
            aliases.append(nm(i))
    return aliases[0], aliases


def note_person(pid, yr, team_label):
    k = person_key(pid)
    if k not in people:
        ids = dup_groups.get(pid, [pid])
        nm, aliases = display_name(ids)
        people[k] = {'name': nm, 'ids': list(ids), 'teams': {}}
        if len(aliases) > 1:
            people[k]['aliases'] = aliases
    p = people[k]
    lst = p['teams'].setdefault(yr, [])
    if team_label and team_label not in lst:
        lst.append(team_label)
    return k


def build_players(yr):
    agg, longs, games, kick_games, punt_games, team_cnt = player_season(yr)

    def team_of(pid, official_tid=None):
        tid = official_tid or (team_cnt[pid].most_common(1)[0][0] if team_cnt[pid] else None)
        return tid

    def base_row(pid, tid, jersey=None):
        k = note_person(pid, yr, tname(yr, tid) if tid else None)
        return {'pid': k, 'name': people[k]['name'], 'team_id': f'hd-{tid}' if tid else None}

    blocks = []
    # --- Passing
    rows = []
    for r in official(yr, 'players', 'LeaderPassing'):
        pid = r['id']
        a = agg[pid]
        row = base_row(pid, r['teamId'])
        row['v'] = {'Games': r['games'], 'Pass Attempts': r['attempts'], 'Completions': r['complete'],
                    'Passing Yards': r['netYards'], 'Pass Touchdowns': r['touchdowns'],
                    'Interceptions Thrown': r['intercepted'],
                    'Completion Percentage': div(r['complete'], r['attempts'], 100),
                    'Sacks Taken': int(a.get('sacked', 0)),
                    'Passer Rating': rnd(r['quarterbackRatingNcaa'], 1)}
        rows.append(row)
    blocks.append(block('players', 'Passing', rows, {'Sacks Taken'}, 'Pass Attempts'))
    # --- Receiving
    rows = []
    for r in official(yr, 'players', 'LeaderReceiving'):
        pid = r['id']
        a = agg[pid]
        # Targets = offizielle Receptions + berechnete unvollständige/abgefangene Zuspiele
        tgt = r['number'] + max(0, int(a.get('tgt', 0) - a.get('rec', 0)))
        row = base_row(pid, r['teamId'])
        row['v'] = {'Games': r['games'], 'Receptions': r['number'], 'Targets': tgt,
                    'Catch Percentage': div(r['number'], tgt, 100),
                    'Receiving Yards': r['yards'], 'Yards per Reception': div(r['yards'], r['number']),
                    'Receiving Touchdowns': r['touchdowns']}
        rows.append(row)
    blocks.append(block('players', 'Receiving', rows, {'Targets', 'Catch Percentage'}, 'Receptions'))
    # --- Rushing
    rows = []
    for r in official(yr, 'players', 'LeaderRushing'):
        pid = r['id']
        row = base_row(pid, r['teamId'])
        row['v'] = {'Games': r['games'], 'Rush Attempts': r['number'], 'Rushing Yards': r['netYards'],
                    'Yards per Attempt': div(r['netYards'], r['number']), 'Rush Touchdown': r['touchdowns'],
                    'Fumbles': int(agg[pid].get('fum', 0))}
        rows.append(row)
    blocks.append(block('players', 'Rushing', rows, {'Fumbles'}, 'Rush Attempts'))
    # --- Defense (Clubee: Tot = Solo + Ast, Ast = halbe Tackles)
    rows = []
    for r in official(yr, 'players', 'LeaderDefense'):
        pid = r['id']
        row = base_row(pid, r['teamId'])
        row['v'] = {'Games': r['games'], 'Total Tackles': rnd(r['totalTackles'], 1),
                    'Solo Tackles': r['soloTackles'], 'Assisted Tackles': rnd(r['assistTackles'] * 0.5, 1),
                    'Tackles for Loss': rnd(r['tackleForLoss'], 1), 'Sacks': rnd(r['sacks'], 1),
                    'Interceptions For': r['interceptions'], 'Pass Breakups': r['passBreakups'],
                    'Defensive Touchdowns': int(agg[pid].get('def_td', 0))}
        rows.append(row)
    blocks.append(block('players', 'Defense', rows, {'Defensive Touchdowns'}, 'Total Tackles'))
    # Spieler ohne Eintrag in den Hockeydata-Ranglisten (vor allem 2014–2018 unvollständig):
    # Werte aus den Spielprotokollen berechnen und die Zeile als berechnet kennzeichnen
    off_ids = {cat: {r['id'] for r in official(yr, 'players', cat)}
               for cat in ('LeaderPassing', 'LeaderReceiving', 'LeaderRushing', 'LeaderDefense')}
    team_hint = {}
    for cat in off_ids:
        for r in official(yr, 'players', cat):
            team_hint.setdefault(r['id'], r['teamId'])

    def calc_row(pid):
        tid = team_hint.get(pid) or (team_cnt[pid].most_common(1)[0][0] if team_cnt[pid] else None)
        row = base_row(pid, tid)
        row['calc_row'] = True
        return row

    extra = defaultdict(list)
    for pid, a in agg.items():
        if pid not in spieler:
            continue
        G_ = len(games[pid]) or None
        if a.get('pass_att', 0) > 0 and pid not in off_ids['LeaderPassing']:
            att, cmp_, yds_, td, ic = a['pass_att'], a.get('pass_cmp', 0), a.get('pass_yds', 0), a.get('pass_td', 0), a.get('pass_int', 0)
            row = calc_row(pid)
            row['v'] = {'Games': G_, 'Pass Attempts': int(att), 'Completions': int(cmp_), 'Passing Yards': int(yds_),
                        'Pass Touchdowns': int(td), 'Interceptions Thrown': int(ic),
                        'Completion Percentage': div(cmp_, att, 100), 'Sacks Taken': int(a.get('sacked', 0)),
                        'Passer Rating': rnd((8.4 * yds_ + 330 * td + 100 * cmp_ - 200 * ic) / att, 1)}
            extra['Passing'].append(row)
        if a.get('rec', 0) > 0 and pid not in off_ids['LeaderReceiving']:
            rec, tgt, yds_ = a.get('rec', 0), a.get('tgt', 0), a.get('rec_yds', 0)
            row = calc_row(pid)
            row['v'] = {'Games': G_, 'Receptions': int(rec), 'Targets': int(max(tgt, rec)),
                        'Catch Percentage': div(rec, max(tgt, rec), 100), 'Receiving Yards': int(yds_),
                        'Yards per Reception': div(yds_, rec), 'Receiving Touchdowns': int(a.get('rec_td', 0))}
            extra['Receiving'].append(row)
        if a.get('rush_att', 0) > 0 and pid not in off_ids['LeaderRushing']:
            att = a['rush_att']
            net = a.get('rush_yds', 0) - a.get('sack_yds', 0)   # wie Hockeydata: Sack-Yards zählen beim Laufen
            row = calc_row(pid)
            row['v'] = {'Games': G_, 'Rush Attempts': int(att), 'Rushing Yards': int(net),
                        'Yards per Attempt': div(net, att), 'Rush Touchdown': int(a.get('rush_td', 0)),
                        'Fumbles': int(a.get('fum', 0))}
            extra['Rushing'].append(row)
        dsum = a.get('solo', 0) + a.get('ast', 0) + a.get('int', 0) + a.get('pbu', 0) + a.get('sacks', 0)
        if dsum > 0 and pid not in off_ids['LeaderDefense']:
            row = calc_row(pid)
            row['v'] = {'Games': G_, 'Total Tackles': rnd(a.get('solo', 0) + a.get('ast', 0) * 0.5, 1),
                        'Solo Tackles': int(a.get('solo', 0)), 'Assisted Tackles': rnd(a.get('ast', 0) * 0.5, 1),
                        'Tackles for Loss': rnd(a.get('tfl_run', 0) + a.get('tfl_sack', 0), 1),
                        'Sacks': rnd(a.get('sacks', 0), 1), 'Interceptions For': int(a.get('int', 0)),
                        'Pass Breakups': int(a.get('pbu', 0)), 'Defensive Touchdowns': int(a.get('def_td', 0))}
            extra['Defense'].append(row)
    for b in blocks:
        if extra.get(b['name']):
            titles = [c.get('title') or c['label'] for c in b['columns']]
            for r in extra[b['name']]:
                b['rows'].append({k: v for k, v in r.items() if k != 'v'} | {'values': [r['v'].get(t) for t in titles]})
            si = {'Passing': 'Pass Attempts', 'Receiving': 'Receptions', 'Rushing': 'Rush Attempts', 'Defense': 'Total Tackles'}[b['name']]
            i = titles.index(si)
            b['rows'].sort(key=lambda r: (r['values'][i] is None, -(r['values'][i] or 0)))
            report['calc_rows'].append((yr, b['name'], len(extra[b['name']])))

    # offizielles Team je Spieler (für berechnete Kategorien)
    off_team = {}
    for cat in ('LeaderPassing', 'LeaderReceiving', 'LeaderRushing', 'LeaderDefense'):
        for r in official(yr, 'players', cat):
            off_team.setdefault(r['id'], r['teamId'])
    # --- Returns (berechnet)
    rows = []
    for pid, a in agg.items():
        if a.get('kr', 0) + a.get('pr', 0) <= 0 or pid not in spieler:
            continue
        row = base_row(pid, team_of(pid, off_team.get(pid)))
        row['v'] = {'Games': len(games[pid]), 'Kickoff Return Yards': int(a.get('kr_yds_wp', a.get('kr_yds', 0))),
                    'Kickoff Return Average': div(a.get('kr_yds_wp', 0), a.get('kr', 0)),
                    'Kickoff Return Touchdowns': int(a.get('kr_td', 0)),
                    'Punt Return Yards': int(a.get('pr_yds', 0)),
                    'Punt Return Average': div(a.get('pr_yds', 0), a.get('pr', 0)),
                    'Punt Return Touchdowns': int(a.get('pr_td', 0))}
        rows.append(row)
    blocks.append(block('players', 'Returns', rows, {c['title'] for c in cols('players', 'Returns') if c['title'] != 'Games'}, 'Kickoff Return Yards'))
    # --- Kicking (berechnet, wie die Website für Clubee-Saisons)
    rows = []
    for pid, a in agg.items():
        fga, fgm, xpa, xpm = a.get('fga', 0), a.get('fgm', 0), a.get('xpa', 0), a.get('xpm', 0)
        if fga + xpa <= 0 or pid not in spieler:
            continue
        row = base_row(pid, team_of(pid, off_team.get(pid)))
        row['v'] = {'Spiele mit Kick': len(kick_games[pid]), 'Field Goals verwandelt': int(fgm),
                    'Field-Goal-Versuche': int(fga), 'Field-Goal-Quote': div(fgm, fga, 100),
                    'Längstes Field Goal (Yards, berechnet)': longs[pid].get('fg_long') if fgm else None,
                    'Extra Points verwandelt': int(xpm), 'Extra Points verschossen': int(xpa - xpm),
                    'Extra-Point-Quote': div(xpm, xpa, 100), 'Punkte durch Kicks (FG × 3 + XP)': int(fgm * 3 + xpm)}
        rows.append(row)
    blocks.append(block('players', 'Kicking', rows, set(), 'Punkte durch Kicks (FG × 3 + XP)', KICK_COLS))
    # --- Punting (berechnet)
    rows = []
    for pid, a in agg.items():
        if a.get('punt', 0) <= 0 or pid not in spieler:
            continue
        row = base_row(pid, team_of(pid, off_team.get(pid)))
        row['v'] = {'Spiele mit Punt': len(punt_games[pid]), 'Punts': int(a['punt']),
                    'Geblockt': int(a.get('punt_blk', 0)), 'Ins Aus': int(a.get('punt_oob', 0)),
                    'Mit Return': int(a.get('punt_ret', 0)), 'Fair Catch': int(a.get('punt_fc', 0)),
                    'Touchback': int(a.get('punt_tb', 0))}
        rows.append(row)
    blocks.append(block('players', 'Punting', rows, set(), 'Punts', PUNT_COLS))
    for b in blocks:
        b['rows'] = [r for r in b['rows'] if r['pid']]
        if b['name'] in ('Kicking', 'Punting'):
            b['computed'] = True
            b['calc'] = list(range(len(b['columns'])))  # ganze Kategorie aus den Spielprotokollen
    # Validierung: berechnete vs. offizielle Werte
    for cat, pairs in (('LeaderRushing', [('number', 'rush_att'), ('touchdowns', 'rush_td')]),
                       ('LeaderReceiving', [('number', 'rec'), ('touchdowns', 'rec_td')]),
                       ('LeaderPassing', [('attempts', 'pass_att'), ('intercepted', 'pass_int'), ('touchdowns', 'pass_td')]),
                       ('LeaderDefense', [('interceptions', 'int'), ('passBreakups', 'pbu')])):
        rows_ = official(yr, 'players', cat)
        for o, m in pairs:
            ok = sum(1 for r in rows_ if abs((r[o] or 0) - agg[r['id']].get(m, 0)) < 0.01)
            report['player_check'].append((yr, cat, o, ok, len(rows_)))
        gok = sum(1 for r in rows_ if r['games'] == len(games[r['id']]))
        report['player_games'].append((yr, cat, gok, len(rows_)))
    return blocks


# ---------------------------------------------------------------- Teams je Saison
GR_MAP = {  # GameReportsJSON-Feld -> Schlüssel im Box-Score
    'rushingAttempts': 'rush_att', 'netYardsRushing': 'rush_net', 'rushingTouchdowns': 'td_rush',
    'passingAttempts': 'pass_att', 'passingCompletions': 'pass_cmp', 'netYardsPassing': 'pass_yds',
    'passingTouchdowns': 'td_pass', 'passingInterceptions': 'pass_int', 'sacksNumber': 'sacks_made',
    'thirdDownAttempts': 'd3_att', 'thirdDownSuccesses': 'd3_conv', 'fumblesNumber': 'fum', 'fumblesLost': 'fum_lost',
    'patSuccesses': 'xpm', 'fieldGoalSuccesses': 'fgm', 'kickoffReturnTouchdowns': 'td_kr',
}


def game_box(g, T, side):
    t = T[side]
    b = {k: v for k, v in t.items()}
    b['rush_net'] = t.get('rush_yds', 0) - t.get('sack_yds', 0) - t.get('kneel', 0)
    b['sacks_made'] = t.get('sacks_for', 0)
    b['src'] = 'xml'
    gr = gamereports.get(g.guid)
    if gr:
        d = json.load(open(gr))['data']
        o = d['homeTeamStats' if side == 'Home' else 'awayTeamStats']
        for k, m in GR_MAP.items():
            if o.get(k) is not None:
                b[m] = o[k]
        b['src'] = 'official'
    return b


def build_teams(yr):
    games_ = [x for x in parsed[yr] if in_team_set(x[0].guid)]
    own = defaultdict(Counter)
    opp = defaultdict(Counter)
    longs = defaultdict(dict)
    gp = Counter()
    pts_for, pts_against = Counter(), Counter()
    for g, P, PS, T in games_:
        gm = all_games[g.guid]
        for side, other in (('Home', 'Away'), ('Away', 'Home')):
            tid = g.team[side][0]
            ob, bb = game_box(g, T, side), game_box(g, T, other)
            gp[tid] += 1
            for k, v in ob.items():
                if isinstance(v, (int, float)) and not k.endswith('_long'):
                    own[tid][k] += v
            for k, v in bb.items():
                if isinstance(v, (int, float)) and not k.endswith('_long'):
                    opp[tid][k] += v
            if 'rush_long' in T[side]:
                longs[tid]['rush_long'] = max(longs[tid].get('rush_long', -99), T[side]['rush_long'])
            if 'pass_long' in T[other]:
                longs[tid]['opp_pass_long'] = max(longs[tid].get('opp_pass_long', -99), T[other]['pass_long'])
            mine_pts = gm['ScoreHome'] if gm['HomeTeamId'] == tid else gm['ScoreAway']
            their_pts = gm['ScoreAway'] if gm['HomeTeamId'] == tid else gm['ScoreHome']
            pts_for[tid] += mine_pts or 0
            pts_against[tid] += their_pts or 0

    O = {cat: {r['id']: r for r in official(yr, 'teams', cat)} for cat in (
        'TeamScoring', 'TeamRushing', 'TeamPassing', 'TeamTotalOffense', 'TeamKickoffReturns', 'TeamPuntReturns',
        'TeamPunts', 'TeamFieldGoals', 'TeamPATKicks', 'TeamPenalties', 'TeamDownConversions')}
    tids = sorted(O['TeamScoring'].keys())

    def base(tid):
        return {'team_id': f'hd-{tid}', 'name': tname(yr, tid)}

    def G(tid):
        return O['TeamScoring'][tid]['gamesPlayed'] or gp[tid]

    def o(cat, tid, f, default=0):
        return (O[cat].get(tid) or {}).get(f, default) or 0

    rows = defaultdict(list)
    for tid in tids:
        g_ = G(tid)
        sc = O['TeamScoring'][tid]
        own_, opp_ = own[tid], opp[tid]
        rsh_td, pss_td = o('TeamRushing', tid, 'touchdowns'), o('TeamPassing', tid, 'touchdowns')
        kr_td, pr_td = o('TeamKickoffReturns', tid, 'touchdowns'), o('TeamPuntReturns', tid, 'touchdowns')
        tot_td = sc['touchdowns']
        rsh_yds, pss_yds = o('TeamRushing', tid, 'yards'), o('TeamPassing', tid, 'yards')
        int_minus = o('TeamPassing', tid, 'interceptions')
        int_plus = int(own_['int_for'])
        fmb_plus, fmb_minus = int(own_['fum_rec_for']), int(own_['fum_lost'])
        punts = o('TeamPunts', tid, 'number')
        dc_att, dc_conv = o('TeamDownConversions', tid, 'attempts'), o('TeamDownConversions', tid, 'conversions')
        opp_td = {k: int(opp_[k]) for k in ('td_rush', 'td_pass', 'td_kr', 'td_pr')}
        opp_def_td = int(opp_['td_def'] + opp_['td_other'])
        opp_tot_td = sum(opp_td.values()) + opp_def_td
        opp_pass_yds, opp_rush_yds = opp_['pass_yds'], opp_['rush_net']

        def add(cat, v):
            rows[cat].append(base(tid) | {'v': v})

        add('Penalties', {'Games': g_, 'Penalties Against': o('TeamPenalties', tid, 'number'),
                          'Penalty Against Yards': o('TeamPenalties', tid, 'yards'),
                          'Penalty Against Yds/Game': div(o('TeamPenalties', tid, 'yards'), g_, 1, 2),
                          'Penalties For': int(opp_['pen']), 'Penalty For Yards': int(opp_['pen_yds_los']),
                          'Penalty For Yds/Game': div(opp_['pen_yds_los'], g_, 1, 2)})
        add('Scoring Offense', {'Games': g_, 'Rush Touchdown': rsh_td, 'Pass Touchdowns': pss_td,
                                'Defensive Touchdowns': max(0, tot_td - rsh_td - pss_td - kr_td - pr_td),
                                'Punt Return Touchdowns': pr_td, 'Kickoff Return Touchdowns': kr_td,
                                'Total Touchdowns': tot_td, 'Field Goal': sc['fieldGoals'],
                                '2-Point Conversion': sc['twoPointConversions'], 'Safeties': sc['safeties'],
                                'Extra Point Kick': sc['extraPoints'],
                                'Defensive Extra Points': sc['twoPointConversionsByDefense'],
                                'Points': sc['points'], 'Average Points per Game': div(sc['points'], g_, 1, 2)})
        add('Scoring Defense', {'Games': g_, 'Rush TDs Allowed': opp_td['td_rush'], 'Pass TDs Allowed': opp_td['td_pass'],
                                'Defensive TDs Allowed': opp_def_td, 'Punt Return TDs Allowed': opp_td['td_pr'],
                                'Kickoff Return TDs Allowed': opp_td['td_kr'], 'Total TDs Allowed': opp_tot_td,
                                'Field Goals Allowed': int(opp_['fgm']), '2-Point Conversions Allowed': int(opp_['two_made']),
                                'Safeties Conceded': int(opp_['safety']), 'Extra Points Allowed': int(opp_['xpm']),
                                'Def. Extra Points Allowed': int(opp_['dxp']), 'Points Allowed': pts_against[tid],
                                'Avg Points Allowed per Game': div(pts_against[tid], g_, 1, 2)})
        add('Special Teams', {'Games': g_, 'Field Goals Made': o('TeamFieldGoals', tid, 'conversions'),
                              'Field Goal Attempts': o('TeamFieldGoals', tid, 'attempts'),
                              'Field Goal Percentage': div(o('TeamFieldGoals', tid, 'conversions'), o('TeamFieldGoals', tid, 'attempts'), 100),
                              'Extra Points Made': o('TeamPATKicks', tid, 'successes'),
                              'Extra Point Attempts': o('TeamPATKicks', tid, 'number'),
                              'Extra Point Percentage': div(o('TeamPATKicks', tid, 'successes'), o('TeamPATKicks', tid, 'number'), 100),
                              'Punt Average': div(o('TeamPunts', tid, 'yards'), punts),
                              'Net Punt Average': rnd(o('TeamPunts', tid, 'netAverage'), 1) if punts else None,
                              'Kickoff Return Average': div(o('TeamKickoffReturns', tid, 'yards'), o('TeamKickoffReturns', tid, 'returns')),
                              'Punt Return Average': div(own_['pr_yds'], own_['pr']),
                              'Blocked Kicks': int(own_['blk_for']), 'Punt Return Touchdowns': pr_td,
                              'Kickoff Return Touchdowns': kr_td})
        mar = int_plus + fmb_plus - int_minus - fmb_minus
        add('Turnover Margin', {'Games': g_, 'Interceptions For': int_plus, 'Fumbles Recovered': fmb_plus,
                                'Interceptions Against': int_minus, 'Fumbles Lost': fmb_minus,
                                'Turnover Margin': mar, 'Turnover Margin/Game': div(mar, g_, 1, 2)})
        add('Total Offense', {'Games': g_, 'Points per Game': div(sc['points'], g_, 1, 2),
                              'Yards per Game': div(o('TeamTotalOffense', tid, 'yards'), g_),
                              'Rush Yards per Game': div(rsh_yds, g_), 'Pass Yards per Game': div(pss_yds, g_),
                              'Rush Touchdown': rsh_td, 'Pass Touchdowns': pss_td, 'Interceptions Against': int_minus,
                              'Sacks Allowed': o('TeamPassing', tid, 'sacks'),
                              '3rd Down Percentage': div(dc_conv, dc_att, 100)})
        add('Passing Offense', {'Games': g_, 'Pass Attempts': o('TeamPassing', tid, 'attempts'),
                                'Completions': o('TeamPassing', tid, 'completions'),
                                'Completion Percentage': div(o('TeamPassing', tid, 'completions'), o('TeamPassing', tid, 'attempts'), 100),
                                'Passing Yards': pss_yds, 'Pass Yards per Game': div(pss_yds, g_),
                                'Pass Touchdowns': pss_td, 'Interceptions Against': int_minus,
                                'Yards per Completion': div(pss_yds, o('TeamPassing', tid, 'completions'))})
        add('Rushing Offense', {'Games': g_, 'Rush Attempts': o('TeamRushing', tid, 'attempts'), 'Rushing Yards': rsh_yds,
                                'Rush Yards per Game': div(rsh_yds, g_), 'Rush Touchdown': rsh_td,
                                'Yards per Attempt': div(rsh_yds, o('TeamRushing', tid, 'attempts')),
                                'Longest Play': longs[tid].get('rush_long'), 'Fumbles': int(own_['fum'])})
        add('Total Defense', {'Games': g_, 'Points against': pts_against[tid],
                              'Points Against per Game': div(pts_against[tid], g_, 1, 2),
                              'Rush Yards Allowed': int(opp_rush_yds), 'Rush Yards Allowed per Game': div(opp_rush_yds, g_),
                              'Total Yards Allowed': int(opp_rush_yds + opp_pass_yds),
                              'Pass Yards Allowed per Game': div(opp_pass_yds, g_),
                              'Sacks': rnd(own_['sacks_made'], 1), 'Interceptions For': int_plus,
                              '3rd Down Stop %': rnd(100 - opp_['d3_conv'] / opp_['d3_att'] * 100, 1) if opp_['d3_att'] else None})
        add('Passing Defense', {'Games': g_, 'Completions Against': int(opp_['pass_cmp']),
                                'Pass Attempts Against': int(opp_['pass_att']),
                                'Completion Yards Against': int(opp_pass_yds),
                                'Opponent Completion %': div(opp_['pass_cmp'], opp_['pass_att'], 100),
                                'Pass Yards Allowed per Game': div(opp_pass_yds, g_),
                                'Pass TDs Allowed': int(opp_['td_pass']),
                                'Longest Completion Allowed': longs[tid].get('opp_pass_long'),
                                'Interceptions For': int_plus, 'Sacks': rnd(own_['sacks_made'], 1)})
        add('Rushing Defense', {'Games': g_, 'Rush Attempts Against': int(opp_['rush_att']),
                                'Rush Yards Allowed': int(opp_rush_yds), 'Rush Yards Allowed per Game': div(opp_rush_yds, g_),
                                'Rush Yards per Attempt Allowed': div(opp_rush_yds, opp_['rush_att']),
                                'Rush TDs Allowed': int(opp_['td_rush'])})
        # Kontrolle: berechnete eigene Werte vs. offizielle
        report['team_check'].append((yr, tname(yr, tid), g_, gp[tid], int(own_['pass_att']), o('TeamPassing', tid, 'attempts'),
                                     int(own_['rush_net']), rsh_yds, int(own_['pass_yds']), pss_yds,
                                     int(own_['pen']), o('TeamPenalties', tid, 'number')))

    CALC = {
        'Penalties': {'Penalties For', 'Penalty For Yards', 'Penalty For Yds/Game'},
        'Scoring Offense': set(),
        'Scoring Defense': {'Rush TDs Allowed', 'Pass TDs Allowed', 'Defensive TDs Allowed', 'Punt Return TDs Allowed',
                            'Kickoff Return TDs Allowed', 'Total TDs Allowed', 'Field Goals Allowed',
                            '2-Point Conversions Allowed', 'Safeties Conceded', 'Extra Points Allowed',
                            'Def. Extra Points Allowed'},
        'Special Teams': {'Punt Return Average', 'Blocked Kicks'},
        'Turnover Margin': {'Interceptions For', 'Fumbles Recovered', 'Fumbles Lost', 'Turnover Margin', 'Turnover Margin/Game'},
        'Total Offense': set(),
        'Passing Offense': set(),
        'Rushing Offense': {'Longest Play', 'Fumbles'},
        'Total Defense': {'Rush Yards Allowed', 'Rush Yards Allowed per Game', 'Total Yards Allowed',
                          'Pass Yards Allowed per Game', 'Sacks', 'Interceptions For', '3rd Down Stop %'},
        'Passing Defense': {'Completions Against', 'Pass Attempts Against', 'Completion Yards Against', 'Opponent Completion %',
                            'Pass Yards Allowed per Game', 'Pass TDs Allowed', 'Longest Completion Allowed',
                            'Interceptions For', 'Sacks'},
        'Rushing Defense': {'Rush Attempts Against', 'Rush Yards Allowed', 'Rush Yards Allowed per Game',
                            'Rush Yards per Attempt Allowed', 'Rush TDs Allowed'},
    }
    SORT = TEAM_SORT
    order = [b['name'] for b in afl['stats']['teams']]
    out = []
    for cat in order:
        if cat not in rows:
            continue
        b = block('teams', cat, rows[cat], CALC.get(cat, set()), SORT[cat])
        if cat in TEAM_ASC:
            # "weniger ist besser": aufsteigend
            si = [c['title'] for c in b['columns']].index(SORT[cat])
            b['rows'].sort(key=lambda r: (r['values'][si] is None, r['values'][si] or 0))
        out.append(b)
    return out, sorted(tids)


TEAM_SORT = {'Penalties': 'Penalty Against Yards', 'Scoring Offense': 'Points', 'Scoring Defense': 'Points Allowed',
             'Special Teams': 'Field Goals Made', 'Turnover Margin': 'Turnover Margin', 'Total Offense': 'Yards per Game',
             'Passing Offense': 'Passing Yards', 'Rushing Offense': 'Rushing Yards', 'Total Defense': 'Points against',
             'Passing Defense': 'Completion Yards Against', 'Rushing Defense': 'Rush Yards Allowed'}
TEAM_ASC = ('Scoring Defense', 'Total Defense', 'Passing Defense', 'Rushing Defense', 'Penalties')   # weniger ist besser


# ---------------------------------------------------------------- Aufbau
index = {'source': 'Hockeydata (AFBÖ-Datenexport, Stand 31.12.2025)', 'seasons': [], 'teams': {}}
for yr in SEASONS:
    if yr not in parsed:
        continue
    pblocks = build_players(yr)
    tblocks, tids = build_teams(yr)
    used_tids = set(tids)
    for b in pblocks:
        for r in b['rows']:
            if r.get('team_id'):
                used_tids.add(int(r['team_id'][3:]))
    teams = [{'id': f'hd-{t}', 'name': tname(yr, t), 'short': SHORT.get(t, ''), 'club': CLUB_KEY.get(t)}
             for t in sorted(used_tids) if t in SHORT]
    for t in teams:
        index['teams'][t['id']] = {'name': t['name'], 'club': t['club'], 'short': t['short']}
    data = {'season': {'id': f'hd-{yr}', 'name': yr}, 'source': 'hockeydata', 'teams': teams,
            'games': len(parsed[yr]), 'stats': {'players': pblocks, 'teams': tblocks}}
    with open(f'{OUT}/season-{yr}.json', 'w') as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    index['seasons'].append({'name': yr, 'file': f'data/archive/season-{yr}.json', 'games': len(parsed[yr])})
    # Karriere
    for b in pblocks:
        for r in b['rows']:
            career[r['pid']][yr][b['name']] = r['values']
            if r.get('calc_row'):
                calc_rows[r['pid']].append(f"{yr}|{b['name']}")
    seasons_out[yr] = pblocks
    # Kader: alle Spieler mit Einsatz – auch ohne Statistikwerte (z. B. Offensive Line), damit ihre
    # Saisons, Teams und Spiele in der Karriere erscheinen
    for g, P, PS, T in parsed[yr]:
        for side in ('Home', 'Away'):
            tid = g.team[side][0]
            if tid not in SHORT:
                continue
            for pid in g.on_roster[side]:
                if pid not in spieler:
                    continue
                k = note_person(pid, yr, tname(yr, tid))
                gm = people[k].setdefault('games', {})
                gm[yr] = gm.get(yr, 0) + 1
    print(yr, 'Spieler-Kategorien:', [(b['name'], len(b['rows'])) for b in pblocks], '| Teams:', len(tids))


# ---------------------------------------------------------------- Saisons vor 2014 (StatCrew, AFBÖ-Website)
# Unterordner des 5. Arguments (…/Statistiken/<Jahr>). Neueste zuerst, damit ältere Saisons auch mit Personen
# verknüpft werden können, die es nur in einer späteren StatCrew-Saison gibt.
STATCREW_SEASONS = {
    '2013': {'exclude': (), 'note': 'Grunddurchgang und Play-offs.',
             'note_en': 'Regular season and playoffs.'},
    '2012': {'exclude': (), 'note': 'Grunddurchgang und Halbfinals – der Boxscore der Austrian Bowl XXVIII fehlt.',
             'note_en': 'Regular season and semi-finals – the box score of Austrian Bowl XXVIII is missing.'},
    '2011': {'exclude': (),
             'note': 'Grunddurchgang (6 Spiele je Team), Halbfinals und Austrian Bowl XXVII. Für den Grunddurchgang '
                     'gibt es nur Saisonsummen: Sacks (QB) und Fumbles je Spieler sowie die Spiele mit Kick/Punt '
                     'fehlen deshalb.',
             'note_en': 'Regular season (6 games per team), semi-finals and Austrian Bowl XXVII. Only season totals '
                        'exist for the regular season, so sacks taken, fumbles per player and games with a kick/punt '
                        'are missing.'},
    '2010': {'exclude': ('VIK_DRA_02_05_10.htm', 'DRA_PAN_17_04_10.htm',      # Europacup (Badalona Dracs, Thonon)
                         'GIA_DRA_15_05_10.htm', 'VIK_GIA_06_06_10.htm'),     # nicht in der AFBÖ-Conference-Statistik
             'note': 'Grunddurchgang (24 Conference-Spiele) und Play-offs.',
             'note_en': 'Regular season (24 conference games) and playoffs.'},
    # 2004–2009: nur Teamseiten (Grunddurchgang); für die Play-offs gibt es keine Statistik-Seiten
    '2009': {'exclude': (), 'page_names': True,
             'note': 'Nur Grunddurchgang (28 Spiele): Play-offs und Austrian Bowl XXV sind in der AFBÖ-Statistik nicht '
                     'enthalten. Blue Devils und Lions spielten auch je viermal gegen Teams der Division I (St. Pölten '
                     'Invaders, ASKOE Steelsharks, CNC Gladiators, Salzburg Bulls); diese Spiele zählen mit. Für das '
                     'Spiel der Lions in St. Pölten (27:36) gibt es keine Statistik.',
             'note_en': 'Regular season only (28 games): the playoffs and Austrian Bowl XXV are not part of the AFBÖ '
                        'statistics. Blue Devils and Lions also played four games each against Division I teams (St. '
                        'Pölten Invaders, ASKOE Steelsharks, CNC Gladiators, Salzburg Bulls); these games are included. '
                        'There are no statistics for the Lions\' game in St. Pölten (27:36).'},
    '2008': {'exclude': (), 'page_names': True,
             'note': 'Nur Grunddurchgang (18 Spiele): Play-offs und Austrian Bowl XXIV sind in der AFBÖ-Statistik nicht '
                     'enthalten. Sacks (QB) und Fumbles je Spieler sowie die Spiele mit Kick/Punt wurden nicht '
                     'veröffentlicht.',
             'note_en': 'Regular season only (18 games): the playoffs and Austrian Bowl XXIV are not part of the AFBÖ '
                        'statistics. Sacks taken, fumbles per player and games with a kick/punt were not published.'},
    '2007': {'exclude': (), 'page_names': True,
             'fixes': {'drop_games': [('Lions', 'May 19, 2007')], 'no_team_stats': ['Lions']},
             'note': 'Nur Grunddurchgang (23 Spiele; Blue Devils – Lions wurde nicht gespielt): die Austrian Bowl XXIII ist '
                     'in der AFBÖ-Statistik nicht enthalten. Keine Teamwerte der Carinthian Lions: die AFBÖ-Statistik '
                     'zählt das Spiel Raiders – Lions (19.05., 28:0) bei den Lions als Sieg mit den Werten der Raiders. '
                     'Die Spielerwerte der Lions sind davon nicht betroffen (ohne dieses Spiel). Sacks (QB) und Fumbles '
                     'je Spieler sowie die Spiele mit Kick/Punt wurden nicht veröffentlicht.',
             'note_en': 'Regular season only (23 games; Blue Devils vs Lions was not played): Austrian Bowl XXIII is not '
                        'part of the AFBÖ statistics. No team figures for the Carinthian Lions: the AFBÖ statistics count '
                        'Raiders vs Lions (19 May, 28:0) as a Lions win with the Raiders\' figures. The Lions\' player '
                        'figures are not affected (without that game). Sacks taken, fumbles per player and games with a '
                        'kick/punt were not published.'},
    '2006': {'exclude': (), 'page_names': True,
             'note': 'Nur Grunddurchgang (19 Spiele, 5 Teams): die Austrian Bowl XXII ist in der AFBÖ-Statistik nicht '
                     'enthalten.',
             'note_en': 'Regular season only (19 games, 5 teams): Austrian Bowl XXII is not part of the AFBÖ statistics.'},
    '2005': {'exclude': (), 'page_names': True,
             'note': 'Nur Grunddurchgang (18 Spiele): die Austrian Bowl XXI ist in der AFBÖ-Statistik nicht enthalten.',
             'note_en': 'Regular season only (18 games): Austrian Bowl XXI is not part of the AFBÖ statistics.'},
    '2004': {'exclude': (), 'page_names': True,
             'note': 'Nur Grunddurchgang (21 Spiele): Halbfinals und Austrian Bowl XX sind in den AFBÖ-Saisonwerten '
                     'nicht enthalten. Zwei Spiele der Cowboys wurden mit 0:35 strafverifiziert und haben keine '
                     'Statistik (die 35 Punkte fehlen deshalb bei Blue Devils und Vikings).',
             'note_en': 'Regular season only (21 games): the semi-finals and Austrian Bowl XX are not part of the AFBÖ '
                        'season totals. Two Cowboys games were forfeited 0:35 and have no statistics (so these 35 points '
                        'are missing for Blue Devils and Vikings).'},
}
# Teamnamen, wie sie in der jeweiligen Saison hießen (sonst: Name der ersten Hockeydata-Saison)
SEASON_TEAM_NAMES = {'2010': {3: 'Prague Panthers', 5: 'Tyrolean Raiders', 901: 'Salzburg Bulls',
                              902: 'St. Pölten Invaders', 903: 'Carinthian Lions'},
                     '2011': {3: 'Prague Panthers', 5: 'Tyrolean Raiders', 901: 'Salzburg Bulls',
                              903: 'Carinthian Lions'}}
SHORT.update({901: 'Bulls', 902: 'Invaders', 903: 'Lions', 904: 'Cowboys', 905: 'Falcons'})
# Vorgänger-Vereine, die für die Spielerzuordnung als "gleiches Team" gelten (Kärnten: Cowboys und Falcons -> Lions)
CLUB_GROUPS = {t: {903, 904, 905} for t in (903, 904, 905)}
# Vom Ligamanagement geprüfte Zuordnungen -> Archiv-Person (Schlüssel hd…); None = eigene Person (nicht verknüpfen).
# Schlüssel: "<Saison>|<Team>|<Name in dieser Saison>"
LINKS_STATCREW = {   # bestätigt am 29.09.2026
    '2013|Rangers|Lars Gabler': 'hd799', '2013|Rangers|Maximilian Zangl': 'hd199', '2013|Rangers|Roman Simmel': 'hd179',
    '2013|Rangers|Stefan Postel': 'hd1063', '2013|Rangers|Christoph Weber': 'hd350', '2013|Dragons|Johannes Kain': 'hd900',
    '2013|Vikings|Felix Tomenendal': None,      # nicht Hockeydata-ID 28 (deren Werte gehören Dylan Potts, s. ID_FIX)
    '2013|Giants|Alex Good': 'hd816',
    '2013|Dragons|Fabian Baumgartner': None,     # nicht Fabio Baumgartner
    '2012|Raiders|Florian Grein': 'hd6168', '2012|Raiders|Lemay Maqueira': 'hd630',
    '2012|Vikings|Andreas Dueringer': 'hd758', '2012|Giants|Clemens Safron': None,
    '2010|Dragons|Bastian Daum': 'hd738', '2010|Vikings|Christopher James': ('2012', 'Raiders', 'Chris James'),
    '2010|Bulls|Benedikt Brugnara': ('2012', 'Raiders', 'Bene Brugnara'), '2010|Bulls|Ralf Stefanisch': 'hd1133',
    '2010|Dragons|Franz Kolohsar': ('2012', 'Vikings', 'Franz Kohlosar'), '2010|Lions|Pico Rabitsch': 'hd1257',
    '2010|Dragons|Andreas Dueringer': 'hd758', '2010|Vikings|Josiah Alan Cravalho': 'hd229',
    '2010|Lions|Jure Bezica': 'hd685', '2010|Panthers|Gabor Sviatko': 'hd6190',
    # 2011: dieselben Personen wie 2010 (bestätigt) bzw. eindeutig (seltener Name, gleiches Team 2010–2018)
    '2011|Dragons|Andreas Dueringer': 'hd758', '2011|Lions|Pico Rabitsch': 'hd1257',
    '2011|Panthers|Gabor Sviatko': 'hd6190',
    '2010|Giants|Ponce de Leon': 'hd85', '2011|Giants|Armando Ponce deLeon': 'hd85',
    '2012|Giants|A. Ponce de Leon': 'hd85', '2013|Giants|A. Ponce de Leon': 'hd85',
    # bestätigt am 30.09.2026: dieselben Spieler wie später
    '2011|Bulls|Alen Jovic': 'hd2619', '2011|Bulls|Benjamin Ast': 'hd2201', '2011|Bulls|Michael Poschacher': 'hd2245',
    '2011|Dragons|James Canetti': 'hd6041', '2011|Giants|Raimund Winkler': 'hd2333', '2011|Lions|Rock Sedej': 'hd1113',
    '2011|Raiders|Max Pichler': 'hd246',
    # 2004–2009: Schreibvarianten derselben Person bzw. Fortsetzung bei einem anderen Verein
    '2009|Dragons|Andreas Dueringer': 'hd758', '2008|Dragons|Andreas Dueringer': 'hd758',
    '2007|Dragons|Andreas Dueringer': 'hd758', '2005|Dragons|Andreas Dueringer': 'hd758',
    '2004|Giants|A. Ponce de Leon': 'hd85', '2005|Giants|Armand.Ponce De Leon': 'hd85', '2007|Giants|A. Ponce de Leon': 'hd85',
    '2006|Blue Devils|Philipp Bickel': ('2010', 'Vikings', 'Phillip Bickel'),
    '2006|Raiders|Christopher Rosier': ('2007', 'Vikings', 'Chris Rosier'),
    '2006|Raiders|Mohammed Muheize': ('2009', 'Giants', 'Mohamed Muheize'),
    '2007|Dragons|Herbert Klack': 'hd912', '2007|Raiders|Michael Kruder': 'hd948',
    '2009|Blue Devils|Wilfried Dieufaite': 'hd744',
    '2005|Dragons|Matthew Crockett': ('2006', 'Lions', 'Matt Crockett'),
    '2005|Blue Devils|Steven Carter': ('2006', 'Giants', 'Steve Carter'),
    '2004|Falcons|Karlhein Buggelsheim': ('2009', 'Lions', 'Karl.H.Buggelsheim'),
    # Ramon Abdel Azim Mohamed (Falcons 2005, Lions 2006–2011) = Ramon Azim (Dragons 2012–2019), bestätigt 30.09.2026
    '2011|Lions|Azim Mohamed Abdel': 'hd7', '2010|Lions|Abdel Azim Mohammed': 'hd7',
    '2009|Lions|Ramon A.Azim Mohamed': 'hd7', '2008|Lions|R. Abdel Azim Mohamed': 'hd7',
    '2007|Lions|Abdel Azim Mohamed': 'hd7', '2006|Lions|R. Abdel Azim Mohamed': 'hd7',
    '2005|Falcons|R. Abdel Azim Mohamed': 'hd7',
    # bestätigt bzw. abgelehnt am 30.09.2026
    '2005|Dragons|Phillip Sommer': None, '2004|Dragons|Philipp Sommer': ('2005', 'Dragons', 'Phillip Sommer'),
    '2005|Dragons|Sascha Steurer': ('2011', 'Lions', 'Sascha Steurer'),
    '2004|Dragons|Sascha Steurer': ('2011', 'Lions', 'Sascha Steurer'),
    '2004|Vikings|Stefan Withalm': ('2012', 'Dragons', 'Stefan Withalm'),
    '2005|Blue Devils|Michael Steffani': 'hd1135', '2004|Blue Devils|Michael Steffani': 'hd1135',
    '2005|Raiders|Mark Falger': ('2008', 'Blue Devils', 'Marc Falger'),
    '2004|Raiders|Mark Falger': ('2008', 'Blue Devils', 'Marc Falger'),
    '2009|Blue Devils|Nic Haritonenko': 'hd849', '2008|Blue Devils|Nic Haritonenko': 'hd849',
    '2008|Blue Devils|A Haritonenko': None,          # nicht Alexander Haritonenko (2016)
    '2009|Blue Devils|Petr Vitrovec': None,           # nicht Petr Vitovec (Black Panthers 2015/16)
    '2008|Blue Devils|Petr Vitovec': ('2009', 'Blue Devils', 'Petr Vitrovec'),
    '2009|Vikings|Emil Cakic': 'hd717',
    '2009|Raiders|T Hunt': None,                      # nicht Tony Hunt (Vikings 2011)
    '2008|Raiders|Markus Pichler': None,              # nicht "M. Pichler" (Raiders 2012)
    '2006|Giants|Guido Peterson': ('2012', 'Giants', 'G. Peterson'),
    '2009|Giants|Manuel Sabathi': 'hd2328',
}
# Anzeigename für Personen, die nur in StatCrew-Saisons vorkommen (sonst Schreibweise der neuesten Saison)
STATCREW_PERSON_NAMES = {}
statcrew_keys = {}   # (Saison, Team, Name) -> Archiv-Schlüssel (für Verweise in LINKS_STATCREW)


def resolve_manual(target):
    """'hd630' -> kanonischer Schlüssel (nach Zusammenführen doppelter IDs); (Saison, Team, Name) -> Schlüssel dieses Eintrags"""
    if isinstance(target, tuple):
        return statcrew_keys.get(target)
    m = re.match(r'^hd(\d+)$', target or '')
    if m and int(m.group(1)) < 900000:
        return person_key(canon(int(m.group(1))))
    return target
PLAYER_SORT = {'Passing': 'Pass Attempts', 'Receiving': 'Receptions', 'Rushing': 'Rush Attempts',
               'Defense': 'Total Tackles', 'Returns': 'Kickoff Return Yards',
               'Kicking': 'Punkte durch Kicks (FG × 3 + XP)', 'Punting': 'Punts'}
links_statcrew = []
statcrew_files = {}
statcrew_team_names = defaultdict(set)   # hd-Team -> alle Namen aus den StatCrew-Saisons (für "gleiches Team")
statcrew_aliases = []   # (Schlüssel, Schreibweise in der StatCrew-Saison) – für die Suche nach Namen (MVP-Liste)
new_person_i = [0]


def fold(s):
    """Vergleichsform für Namen: ohne Akzente, ä/ae, ö/oe, ü/ue gleich"""
    s = norm(s)
    for a, b in (('ae', 'a'), ('oe', 'o'), ('ue', 'u')):
        s = s.replace(a, b)
    return s


def season_team_name(yr, tid):
    if tid in SEASON_TEAM_NAMES.get(yr, {}):
        return SEASON_TEAM_NAMES[yr][tid]
    for y in SEASONS:
        if (y, tid) in team_name:
            return team_name[(y, tid)]
    return tname('2025', tid)


def add_statcrew_season(YR, S, cfg):
    # Teamnamen: wie auf den Teamseiten der Saison (2004–2009) bzw. wie in SEASON_TEAM_NAMES / Hockeydata
    team_nm = {tid: (clean_name(nm) if cfg.get('page_names') else season_team_name(YR, tid))
               for tid, nm in S['team_names'].items()}
    for tid, nm in team_nm.items():
        statcrew_team_names[tid].add(nm)
    def names_of(tid):
        return ({tname(y, tid) for y in SEASONS if (y, tid) in team_name}
                | {season_team_name(y, tid) for y in list(STATCREW_SEASONS) if tid in SEASON_TEAM_NAMES.get(y, {})}
                | statcrew_team_names[tid])
    club_names = {tid: set().union(*(names_of(t) for t in CLUB_GROUPS.get(tid, {tid}))) for tid in team_nm}

    # Namensvarianten der Archiv-Personen (inkl. Personen, die nur in späteren StatCrew-Saisons vorkommen)
    variants = defaultdict(set)     # key -> {(first, last)}
    # 2004–2009: auch die Schreibweisen aus den späteren StatCrew-Saisons (z. B. "Andreas Dueringer" für "Düringer");
    # 2010–2013 bleiben dafür unverändert
    later = defaultdict(list)
    if cfg.get('page_names'):
        for k_, nm_ in statcrew_aliases:
            later[k_].append(nm_)
    for k, p in people.items():
        for pid in p['ids']:
            sp = spieler.get(pid, {})
            variants[k].add((clean_name(sp.get('Firstname')), clean_name(sp.get('Lastname'))))
        for nm in [p['name']] + p.get('aliases', []) + later.get(k, []):
            parts = re.sub(r'\.(?=[A-Za-zÄÖÜäöü])', '. ', nm).split()
            if len(parts) > 1:
                variants[k].add((parts[0], ' '.join(parts[1:])))
            elif parts:
                variants[k].add(('', parts[0]))
    by_full = defaultdict(set)
    by_last = defaultdict(set)
    for k, vs in variants.items():
        for f, l in vs:
            by_full[fold(f + ' ' + l)].add(k)
            for part in [l] + l.replace('-', ' ').split():
                by_last[fold(part)].add(k)

    def same_club(k, tid):
        return any(t in club_names[tid] for ts in people[k]['teams'].values() for t in ts)

    def gap(k):
        """Jahre bis zur nächsten Saison der Person"""
        ys = [int(y) for y in people[k]['teams'] if y != YR]
        return min(ys) - int(YR) if ys else 99

    def link(pl):
        """-> (key or None, status)"""
        tid = pl['tid']
        manual = LINKS_STATCREW.get(f"{YR}|{pl['team']}|{pl['name']}", 'offen')
        if manual != 'offen':
            k = resolve_manual(manual) if manual else None
            if manual and k not in people:
                return None, f'prüfen: bestätigte Zuordnung {manual} nicht gefunden'
            return k, ('sicher: manuell bestätigt' if k else 'eigene Person: manuell bestätigt')
        parts = re.sub(r'\.(?=[A-Za-zÄÖÜäöü])', '. ', pl['name']).split()
        if pl['full_name'] and len(parts) > 1:
            ks = set()
            for n in pl['names'] + [pl['name']]:
                if not statcrew.looks_abbrev(n):
                    ks |= by_full.get(fold(n), set())
            if len(ks) == 1:
                k = next(iter(ks))
                if same_club(k, tid):
                    return k, 'sicher: gleicher Name, gleiches Team'
                # gleicher (eindeutiger) Name bei einem anderen Verein wenige Jahre später: Vereinswechsel
                # (2013 vom Ligamanagement in allen solchen Fällen bestätigt)
                return k, ('wahrscheinlich: gleicher Name, Vereinswechsel' if gap(k) <= 5 else 'prüfen: gleicher Name, anderes Team')
            if len(ks) > 1:
                same = [k for k in ks if same_club(k, tid)]
                if len(same) == 1:
                    return same[0], 'sicher: gleicher Name, gleiches Team'
                return None, 'prüfen: mehrere Archiv-Personen mit diesem Namen: ' + ', '.join(sorted(ks))
            # ähnliche Schreibweise (Tippfehler, Kurzform, Spitzname, Umlaut, Doppelname, vertauscht)
            first, last = parts[0], ' '.join(parts[1:])
            found = []
            for k, vs in variants.items():
                best = None
                for f, l in vs:
                    if fold(first) == fold(l) and fold(last) == fold(f):
                        cand = (1.9, 'Vor- und Nachname vertauscht', True)
                    else:
                        ls, lkind = dedupe.last_sim(last, l)
                        if ls < 0.85:
                            continue
                        if not f:
                            fs, fkind = 0.75, 'im Archiv ohne Vorname'
                        else:
                            fs, fkind = dedupe.first_sim(first, f)
                        if fs < 0.7:
                            continue
                        # stark: Vorname gleich/Kurzform/Spitzname, offensichtlicher Tippfehler bei gleichem Nachnamen
                        # ("Stafean"/"Stefan") oder Vorname im Archiv nicht erfasst
                        cand = (fs + ls, f'Vorname {fkind or "Tippfehler"}, Nachname {lkind}',
                                fs >= 0.85 or (ls >= 0.99 and fs >= 0.75) or (not f and ls >= 0.99))
                    if best is None or cand[0] > best[0]:
                        best = cand
                if best:
                    found.append((k,) + best)
            if found:
                def rank(x):
                    return (same_club(x[0], pl['tid']), x[1])
                found.sort(key=rank, reverse=True)
                same = [x for x in found if same_club(x[0], pl['tid'])]
                pick = same if same else found
                k, _, why, strong = pick[0]
                if len(pick) > 1 and pick[1][1] >= pick[0][1] - 0.05:
                    return None, 'prüfen: mehrere ähnliche Namen: ' + ', '.join(f"{x[0]} {people[x[0]]['name']}" for x in pick[:3])
                if strong and same and gap(k) <= 3:
                    return k, f'wahrscheinlich: ähnlicher Name ({why}), gleiches Team'
                return k, f"prüfen: ähnlicher Name ({why}), {'gleiches' if same else 'anderes'} Team"
            return None, f'neu: nur {YR}'
        # nur Kurzname (Initiale + Nachname) oder nur Nachname: eindeutige Archiv-Person desselben Teams, die nicht
        # schon einem anderen Eintrag dieses Teams zugeordnet ist (z. B. "Da. Krejbich" neben Daniel Krejbich)
        if pl['full_name']:
            ini, last = None, norm(pl['name'])
        else:
            ini, last = statcrew.abbrev_parts(pl['abbrevs'][0] if pl['abbrevs'] else pl['name'])
        ks = [k for k in by_last.get(fold(last), set()) if same_club(k, tid)
              and not (set(pl['games']) & used.get(pl['team'], {}).get(k, set()))
              and any(fold(f).startswith(fold(ini or '')) for f, l in variants[k] if fold(l).split()[-1:] == fold(last).split()[-1:] or fold(l) == fold(last))]
        ks = [k for k in ks if gap(k) <= 2]
        if len(ks) == 1:
            return ks[0], ('wahrscheinlich: nur Nachname, gleiches Team' if pl['full_name'] else
                           'wahrscheinlich: Initiale + Nachname, gleiches Team')
        return None, (f'neu: nur {YR} (nur Kurzname)' if not ks else 'prüfen: mehrere Archiv-Personen: ' + ', '.join(ks))

    # Zuordnung je Eintrag; mehrere Einträge derselben Person: ohne gemeinsames Spiel zusammenfassen,
    # sonst bleibt nur der Eintrag mit dem vollen Namen verknüpft
    links = []
    assigned = []
    used = defaultdict(dict)     # Team -> Archiv-Schlüssel -> Spiele des schon zugeordneten Eintrags
    linked = {}
    for pl in sorted(S['players'], key=lambda p: not p['full_name']):   # volle Namen zuerst
        linked[id(pl)] = link(pl)
        k, status = linked[id(pl)]
        if k and status.startswith(('sicher', 'wahrscheinlich')):
            used[pl['team']].setdefault(k, set()).update(pl['games'])
    for pl in S['players']:
        k, status = linked[id(pl)]
        auto_ok = status.startswith(('sicher', 'wahrscheinlich', 'eigene Person'))
        links.append([pl, k, status])
        assigned.append([pl, k if auto_ok else None, status])
    by_key = defaultdict(list)
    for a in assigned:
        if a[1]:
            by_key[a[1]].append(a)
    for k, lst in by_key.items():
        if len(lst) < 2:
            continue
        overlap = any(set(x[0]['games']) & set(y[0]['games']) for i, x in enumerate(lst) for y in lst[i + 1:])
        if overlap:
            lst.sort(key=lambda a: (not a[0]['full_name'], -a[0]['gp']))
            for a in lst[1:]:
                a[1] = None
                for l in links:
                    if l[0] is a[0]:
                        l[1], l[2] = None, 'neu: gleiche Person wie ein anderer Eintrag ausgeschlossen (gemeinsame Spiele)'
        else:
            merged = statcrew.merge_players([a[0] for a in lst])
            lst[0][0] = merged
            for a in lst[1:]:
                a[1] = 'skip'
    rows = defaultdict(list)
    for pl, k, status in assigned:
        if k == 'skip':
            continue
        if k is None:
            if not pl['v']:
                continue      # nur Einsatz, kein Name/keine Werte: keine eigene Person
            new_person_i[0] += 1
            k = f'hd{900000 + new_person_i[0]}'
            people[k] = {'name': STATCREW_PERSON_NAMES.get(f"{YR}|{pl['team']}|{pl['name']}", pl['name']),
                         'ids': [], 'teams': {}}
        elif pl['full_name'] and statcrew.looks_abbrev(people[k]['name']) and not people[k]['ids']:
            people[k]['name'] = pl['name']    # "J. Geser" (nur Kurzname in einer späteren Saison) -> "Johannes Geser"
        if pl['full_name']:
            statcrew_aliases.append((k, pl['name']))
        statcrew_keys[(YR, pl['team'], pl['name'])] = k
        lst = people[k]['teams'].setdefault(YR, [])
        if team_nm[pl['tid']] not in lst:
            lst.append(team_nm[pl['tid']])
        gm = people[k].setdefault('games', {})
        gm[YR] = gm.get(YR, 0) + pl['gp']
        for cat, v in pl['v'].items():
            rows[cat].append({'pid': k, 'name': people[k]['name'], 'team_id': f"hd-{pl['tid']}", 'v': v})
    pblocks = []
    for cat in ['Passing', 'Receiving', 'Rushing', 'Defense', 'Returns', 'Kicking', 'Punting']:
        extra = KICK_COLS if cat == 'Kicking' else PUNT_COLS if cat == 'Punting' else None
        calc = {'Spiele mit Kick'} if cat == 'Kicking' else {'Spiele mit Punt'} if cat == 'Punting' else set()
        pblocks.append(block('players', cat, rows.get(cat, []), calc, PLAYER_SORT[cat], extra))
    tblocks = []
    trows = defaultdict(list)
    for t in S['teams']:
        for cat, v in t['v'].items():
            trows[cat].append({'team_id': f"hd-{t['tid']}", 'name': team_nm[t['tid']], 'v': v})
    for cat in [b['name'] for b in afl['stats']['teams']]:
        if cat not in trows:
            continue
        b = block('teams', cat, trows[cat], set(), TEAM_SORT[cat])
        if cat in TEAM_ASC:
            si = [c['title'] for c in b['columns']].index(TEAM_SORT[cat])
            b['rows'].sort(key=lambda r: (r['values'][si] is None, r['values'][si] or 0))
        tblocks.append(b)
    teams_out = [{'id': f'hd-{tid}', 'name': team_nm[tid], 'short': SHORT.get(tid, ''), 'club': CLUB_KEY.get(tid)}
                 for tid in sorted(team_nm)]
    for t in teams_out:
        e = index['teams'].setdefault(t['id'], {'name': t['name'], 'club': t['club'], 'short': t['short']})
        if t['name'] != e['name']:
            e.setdefault('names', [])
            if t['name'] not in e['names']:
                e['names'].append(t['name'])
    data = {'season': {'id': f'sc-{YR}', 'name': YR}, 'source': 'statcrew', 'note': cfg['note'],
            'note_en': cfg['note_en'], 'teams': teams_out, 'games': S['games'],
            'stats': {'players': pblocks, 'teams': tblocks}}
    statcrew_files[YR] = data      # geschrieben nach allen StatCrew-Saisons (Namen können sich noch ändern)
    index['seasons'].append({'name': YR, 'file': f'data/archive/season-{YR}.json', 'games': S['games'],
                             'source': 'statcrew', 'note': cfg['note'], 'note_en': cfg['note_en']})
    for b in pblocks:
        for r in b['rows']:
            career[r['pid']][YR][b['name']] = r['values']
    seasons_out[YR] = pblocks
    for l in links:
        links_statcrew.append([YR] + l)
    st = Counter(x[2].split(':')[0] for x in links)
    print(f'{YR}:', S['games'], 'Spiele |', [(b['name'], len(b['rows'])) for b in pblocks], '| Zuordnung:', dict(st),
          '| Boxscores:', len(S['files']['boxes']), 'zusätzlich,', len(S['files']['covered']), 'zur Kontrolle')


if STATCREW_DIR:
    import statcrew  # noqa: E402
    for YR in sorted(STATCREW_SEASONS, reverse=True):
        folder = os.path.join(STATCREW_DIR, YR)
        if not os.path.isdir(folder):
            continue
        add_statcrew_season(YR, statcrew.season_from_folder(folder, STATCREW_SEASONS[YR]['exclude'],
                                                            STATCREW_SEASONS[YR].get('fixes')), STATCREW_SEASONS[YR])
    for k, nm in statcrew_aliases:   # erst am Ende, damit die Zuordnung der Saisons unverändert bleibt
        p = people[k]
        names = [p['name']] + p.get('aliases', [])
        if fold(nm) not in {fold(x) for x in names}:
            p['aliases'] = (p.get('aliases') or [p['name']]) + [nm]
    # Hockeydata-Namen ohne Vorname ("Düringer") bzw. mit vertauschten Vor-/Nachnamen ("Grein Florian"): Schreibweise
    # aus den StatCrew-Saisons übernehmen ("Andreas Düringer", "Florian Grein")
    alias_cnt = defaultdict(Counter)
    for k, nm in statcrew_aliases:
        alias_cnt[k][nm] += 1
    renamed = {}
    for k, cnt in alias_cnt.items():
        p = people[k]
        if not p['ids']:
            continue
        toks = p['name'].split()
        for a, n in cnt.most_common():
            at = a.split()
            if len(toks) == 1 and len(at) >= 2 and fold(at[-1]) == fold(toks[0]):
                renamed[k] = ' '.join(at[:-1] + toks)
                break
            if len(toks) == 2 and n >= 2 and [fold(x) for x in at] == [fold(toks[1]), fold(toks[0])]:
                renamed[k] = f'{toks[1]} {toks[0]}'
                break
    for k, nm in renamed.items():
        p = people[k]
        p['aliases'] = [nm] + [a for a in (p.get('aliases') or [p['name']]) if a != nm]
        p['name'] = nm
    for yr in SEASONS:      # Hockeydata-Saisons sind schon geschrieben: Namen dort nachziehen
        f = f'{OUT}/season-{yr}.json'
        if not renamed or not os.path.exists(f):
            continue
        data = json.load(open(f))
        hit = False
        for b in data['stats']['players']:
            for r in b['rows']:
                if r.get('pid') in renamed:
                    r['name'] = renamed[r['pid']]
                    hit = True
        if hit:
            with open(f, 'w') as fh:
                json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    print('Namen aus StatCrew übernommen:', renamed)
    for YR, data in statcrew_files.items():
        for b in data['stats']['players']:
            for r in b['rows']:
                r['name'] = people[r['pid']]['name']
        with open(f'{OUT}/season-{YR}.json', 'w') as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    for YR in sorted(STATCREW_SEASONS):
        if YR in seasons_out and YR not in SEASONS:
            SEASONS.insert(sorted(SEASONS + [YR]).index(YR), YR)
    with open(f'{REPORT_DIR}/Pruefliste-StatCrew-Saisons.csv', 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh, delimiter=';')
        w.writerow(['Saison', 'Status', 'Team', 'Name', 'Schreibweisen', 'Spiele', 'Archiv-Schlüssel',
                    'Name im Archiv', 'Weitere Saisons', 'Teams in weiteren Saisons'])
        order = {'prüfen': 0, 'wahrscheinlich': 1, 'sicher': 2, 'neu': 3, 'eigene Person': 4}
        for yr, pl, k, status in sorted(links_statcrew, key=lambda x: (x[0], order.get(x[3].split(':')[0], 9), x[1]['team'], x[1]['name'])):
            p = people.get(k) if k else None
            w.writerow([yr, status, pl['team'], pl['name'], ', '.join(pl['names'] or pl['abbrevs']), pl['gp'], k or '',
                        p['name'] if p else '', ', '.join(sorted(y for y in p['teams'] if y != yr)) if p else '',
                        ', '.join(sorted({t for y, ts in p['teams'].items() if y != yr for t in ts})) if p else ''])

# ---------------------------------------------------------------- Zuordnung zu Clubee
clubee = {}
teams26 = {t['id']: t['name'] for t in afl['teams']}
for p in afl['players']:
    clubee[p['id']] = {'first': p['firstname'], 'last': p['lastname'], 'birth': p.get('birthday'),
                       'team': teams26.get(p['team_id']), 'web': True}
for b in afl['stats']['players']:
    for r in b['rows']:
        if r.get('user_id') and r['user_id'] not in clubee:
            clubee[r['user_id']] = {'first': None, 'last': None, 'full': r['name'], 'birth': None,
                                    'team': teams26.get(r['team_id']), 'web': False}
by_name, by_name_birth, by_birth = defaultdict(list), defaultdict(list), defaultdict(list)
for k, p in people.items():
    for pid in p['ids']:
        sp = spieler[pid]
        nk = norm(sp['Firstname']) + '|' + norm(sp['Lastname'])
        b = (sp.get('Birthdate') or '')[:10]
        if k not in by_name[nk]:
            by_name[nk].append(k)
        if b and k not in by_name_birth[(nk, b)]:
            by_name_birth[(nk, b)].append(k)
        if b and k not in by_birth[b]:
            by_birth[b].append(k)
CLUB_WORDS = set(CLUB_KEY.values())


def team_fits(k, cteam):
    if not cteam:
        return False
    ct = cteam.lower()
    return any(w in ct and w in t.lower() for ts in people[k]['teams'].values() for t in ts for w in CLUB_WORDS)


def first_names_compatible(a, b):
    a, b = set(norm(a).split()), set(norm(b).split())
    return bool(a & b)


links = []


def births_of(k):
    return {(spieler[i].get('Birthdate') or '')[:10] for i in people[k]['ids']} - {''}


def lastname_ok(a, b):
    a, b = norm(a), norm(b)
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() > 0.85


for u, c in clubee.items():
    if c['first'] is not None:
        cands_names = [norm(c['first']) + '|' + norm(c['last'])]
        full = f"{c['first']} {c['last']}"
    else:
        parts = c['full'].split()
        cands_names = [norm(' '.join(parts[:i])) + '|' + norm(' '.join(parts[i:])) for i in range(1, len(parts))]
        full = c['full']
    b = c['birth']
    hits = {}
    # 1) gleicher Name + gleiches Geburtsdatum
    if b:
        for nk in cands_names:
            for k in by_name_birth.get((nk, b), []):
                hits.setdefault(k, 'sicher: Name + Geburtsdatum')
    # 2) gleiches Geburtsdatum + Nachname, Vorname in Kurz-/Langform ("Chad" / "Chad Allen")
    if b and c['first'] is not None:
        for k in by_birth.get(b, []):
            if k in hits:
                continue
            for pid in people[k]['ids']:
                sp = spieler[pid]
                if (sp.get('Birthdate') or '')[:10] == b and lastname_ok(sp['Lastname'], c['last']) \
                        and first_names_compatible(sp['Firstname'], c['first']):
                    hits[k] = 'sicher: Geburtsdatum + Nachname, Vorname in Kurzform'
                    break
    # 3) nur Name – wenn eine Seite kein Geburtsdatum hat und der Name eindeutig ist
    for nk in cands_names:
        ks = [k for k in by_name.get(nk, []) if k not in hits]
        if not ks:
            continue
        undated = [k for k in ks if not births_of(k) or not b]
        conflicting = [k for k in ks if b and births_of(k) and b not in births_of(k)]
        if len(undated) == 1:
            k = undated[0]
            hits[k] = ('wahrscheinlich: Name eindeutig, Team passt' if team_fits(k, c['team'])
                       else 'prüfen: nur Name (Geburtsdatum fehlt)')
        elif len(undated) > 1:
            links.append({'user_id': u, 'key': None, 'conf': 'mehrdeutig: ' + ', '.join(undated), 'c': c, 'full': full})
        if not hits and conflicting:
            for k in conflicting:
                links.append({'user_id': u, 'key': k, 'conf': 'abgelehnt: gleicher Name, anderes Geburtsdatum', 'c': c, 'full': full})
        break
    for k, conf in hits.items():
        links.append({'user_id': u, 'key': k, 'conf': conf, 'c': c, 'full': full})

# Manuell bestätigt (Ligamanagement, 29.09.2026): gleiche Person trotz fehlendem Geburtsdatum im Archiv
CONFIRMED = {'hd58': 986648, 'hd259': 977710, 'hd205': 989524,    # Chad Jeffries, Julian Perfler, Yannick Mayr
             'hd365': 977542, 'hd261': 988253,                    # Roman Seybold, Aaron Schernig
             'hd6031': 988676}                                    # Javarian Smith (Black Panthers 2022 / Enthroners)
for l in links:
    if l['key'] in CONFIRMED and CONFIRMED[l['key']] == l['user_id']:
        l['conf'] = 'sicher: manuell bestätigt'
for k, u in CONFIRMED.items():
    if k in people and u in clubee and not any(l['key'] == k and l['user_id'] == u for l in links):
        links.append({'user_id': u, 'key': k, 'conf': 'sicher: manuell bestätigt', 'c': clubee[u], 'full': people[k]['name']})

# Konflikte: ein Archiv-Spieler -> mehrere Clubee-Profile. Ist genau eines davon sicher (z. B. gleiches
# Geburtsdatum) und die übrigen nur wahrscheinlich/zu prüfen (doppeltes Clubee-Profil ohne Geburtsdatum), wird das
# sichere verknüpft; sonst keines.
by_key_links = defaultdict(list)
for l in links:
    if l['key'] and not l['conf'].startswith(('abgelehnt', 'mehrdeutig')):
        by_key_links[l['key']].append(l)
player_map = {}
for k, ls in by_key_links.items():
    top = [l for l in ls if l['conf'].startswith('sicher')]
    if len(ls) == 1 or len(top) == 1:
        win = ls[0] if len(ls) == 1 else top[0]
        player_map[k] = win['user_id']
        for l in ls:
            if l is not win:
                l['conf'] = f"doppeltes Clubee-Profil – verknüpft ist {win['user_id']}"
        continue
    for l in ls:
        l['conf'] = 'KONFLIKT: mehrere Clubee-Profile – nicht verknüpft'

with open(f'{OUT}/player-map.json', 'w') as fh:
    json.dump(dict(sorted(player_map.items(), key=lambda x: int(x[0][2:]))), fh, ensure_ascii=False, indent=0)

with open(f'{REPORT_DIR}/Pruefliste-Spielerzuordnung.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh, delimiter=';')
    w.writerow(['Status', 'Clubee-ID', 'Name (Clubee)', 'Team 2026', 'Geburtsdatum (Clubee)', 'Archiv-Schlüssel',
                'Name (Hockeydata)', 'Geburtsdatum (Hockeydata)', 'Saisonen im Archiv', 'Teams im Archiv', 'Auf Website'])
    order = {'KONFLIKT': 0, 'mehrdeutig': 1, 'prüfen': 2, 'abgelehnt': 3, 'wahrscheinlich': 4, 'sicher': 5}
    for l in sorted(links, key=lambda l: (order.get(l['conf'].split(':')[0], 9), l['full'])):
        k = l['key']
        p = people.get(k) if k else None
        births = sorted({(spieler[i].get('Birthdate') or '')[:10] for i in p['ids']} - {''}) if p else []
        w.writerow([l['conf'], l['user_id'], l['full'], l['c']['team'] or '', l['c']['birth'] or '', k or '',
                    p['name'] if p else '', ', '.join(births), ', '.join(sorted(p['teams'])) if p else '',
                    ', '.join(sorted({t for ts in p['teams'].values() for t in ts})) if p else '',
                    'ja' if l['c']['web'] else 'nein'])

# ---------------------------------------------------------------- Karriere-Datei
cats = ['Passing', 'Receiving', 'Rushing', 'Defense', 'Returns', 'Kicking', 'Punting']
car = {'source': index['source'], 'seasons': [y for y in SEASONS if y in seasons_out], 'categories': cats,
       'columns': {}, 'titles': {}, 'calc': {}, 'people': {}, 'players': {}}
for yr, blocks in seasons_out.items():
    for b in blocks:
        car['columns'].setdefault(b['name'], {})[yr] = [c['label'] for c in b['columns']]
        t = car['titles'].setdefault(b['name'], {})
        for c in b['columns']:
            t.setdefault(c['label'], c.get('title') or '')
        car['calc'].setdefault(b['name'], sorted({b['columns'][i]['label'] for i in b['calc']}))
for k, p in sorted(people.items(), key=lambda x: int(x[0][2:])):
    entry = {'name': p['name'], 'teams': p['teams']}
    if p.get('games'):
        entry['games'] = p['games']
    if len(p.get('aliases', [])) > 1:
        entry['aliases'] = p['aliases']
    car['people'][k] = entry
    if k in career:
        car['players'][k] = career[k]
    if calc_rows.get(k):
        car.setdefault('calc_rows', {})[k] = sorted(set(calc_rows[k]))
with open(f'{OUT}/career.json', 'w') as fh:
    json.dump(car, fh, ensure_ascii=False, separators=(',', ':'))

index['seasons'].sort(key=lambda s: s['name'], reverse=True)
index['calc_note'] = ('Werte mit dem Hinweis „berechnet“ sind in den Hockeydata-Ranglisten nicht enthalten und '
                      'wurden aus den Spielprotokollen (EGREP-AF) berechnet.')
with open(f'{OUT}/index.json', 'w') as fh:
    json.dump(index, fh, ensure_ascii=False, indent=1)

# ---------------------------------------------------------------- Bericht
with open(f'{REPORT_DIR}/report.json', 'w') as fh:
    json.dump({k: v for k, v in report.items()}, fh, ensure_ascii=False, indent=0)
st = Counter(l['conf'].split(':')[0] for l in links)
print('Personen im Archiv:', len(car['people']), '| mit Statistikwerten:', len(car['players']), '| verknüpft mit Clubee:', len(player_map), '| Status:', dict(st))
print('zusammengeführte Doppel-IDs:', sum(len(v) - 1 for v in dup_groups.values()), '| zur Prüfung:', len(dup_review))


def dup_label(i):
    r = dup_records[i]
    return [f"hd{i}", clean_name(f"{r['first']} {r['last']}"), r['birth'] or '',
            f"{min(r['seasons'])}–{max(r['seasons'])}", ', '.join(sorted({t for ts in r['team_by_season'].values() for t in ts}))]


with open(f'{REPORT_DIR}/Doppelte-IDs-zusammengefuehrt.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh, delimiter=';')
    w.writerow(['Person (Archiv-Schlüssel)', 'ID', 'Name', 'Geburtsdatum', 'Saisons', 'Teams'])
    for r, ids in sorted(dup_groups.items(), key=lambda x: dup_records[x[0]]['last']):
        for i in ids:
            w.writerow([f'hd{r}'] + dup_label(i))
with open(f'{REPORT_DIR}/Pruefliste-Doppelte-IDs.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh, delimiter=';')
    w.writerow(['ID A', 'Name A', 'Geburtsdatum A', 'Saisons A', 'Teams A', 'ID B', 'Name B', 'Geburtsdatum B',
                'Saisons B', 'Teams B', 'Hinweis'])
    for a, b, f in dup_review:
        note = ', '.join(x for x in (f.get('last_kind'), 'gleiche Saison' if f.get('same_season') else '',
                                     'gleiches Team' if f.get('shared_team') else 'anderes Team') if x)
        w.writerow(dup_label(a) + dup_label(b) + [note])
for f in sorted(glob.glob(f'{OUT}/*.json')):
    print(os.path.basename(f), os.path.getsize(f))
