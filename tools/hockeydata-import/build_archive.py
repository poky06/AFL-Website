#!/usr/bin/env python3
"""
Hockeydata-Archiv (AFL 2014–2025) -> Website-Dateien im Clubee-Format.

Aufruf:  python3 build_archive.py <DataPackage-Ordner> <Zielordner data/archive> <data/afl.json> [Berichtsordner]

Quellen (alle aus dem AFBÖ-Datenexport von Hockeydata):
  PlayerStats/*, TeamStats/*          offizielle Saisonwerte (werden 1:1 übernommen)
  AFL-EGREP-Gamereports/*.xml         Spielprotokolle – daraus werden fehlende Clubee-Spalten berechnet
  GameReportsJSON/*.json              offizielle Team-Boxscores je Spiel (2023–2025)
  AlleSpieleMitErgebnis.json          Ergebnisse (Punkte, Spielstatus)
  Spieler.json, Team-Bewerb-Zuordnung.json

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

if len(sys.argv) < 4:
    sys.exit('Aufruf: python3 build_archive.py <DataPackage-Ordner> <Zielordner data/archive> <data/afl.json> [Berichtsordner]')
RAW, OUT, AFL_JSON = sys.argv[1], sys.argv[2], sys.argv[3]
REPORT_DIR = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.getcwd(), 'hockeydata-bericht')
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


def official(yr, kind, cat):
    base = 'PlayerStats' if kind == 'players' else 'TeamStats'
    path = f'{RAW}/{base}/Saison {yr}/{cat}.json'
    return json.load(open(path))['data']['rows'] if os.path.exists(path) else []


gamereports = {}
for f in glob.glob(f'{RAW}/GameReportsJSON/*/*.json'):
    gamereports[os.path.basename(f)[:-5]] = f

# ---------------------------------------------------------------- Spielprotokolle
print('Spielprotokolle einlesen …')
parsed = defaultdict(list)
seen = set()
for f in sorted(glob.glob(f'{RAW}/AFL-EGREP-Gamereports/*/*.xml')):
    g, P, PS, T = egrep.parse(f)
    if g.guid in seen or g.guid not in all_games:
        continue
    seen.add(g.guid)
    parsed[all_games[g.guid]['SeasonName'][-4:]].append((g, P, PS, T))
print({k: len(v) for k, v in sorted(parsed.items())})


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
career = defaultdict(lambda: defaultdict(dict))   # key -> yr -> cat -> values
seasons_out = {}
report = defaultdict(list)


def person_key(pid):
    return f'hd{pid}'


def note_person(pid, yr, team_label):
    k = person_key(pid)
    sp = spieler.get(pid, {})
    nm = clean_name(f"{sp.get('Firstname', '')} {sp.get('Lastname', '')}") or f'Spieler {pid}'
    p = people.setdefault(k, {'name': nm, 'ids': [pid], 'teams': {}})
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
    SORT = {'Penalties': 'Penalty Against Yards', 'Scoring Offense': 'Points', 'Scoring Defense': 'Points Allowed',
            'Special Teams': 'Field Goals Made', 'Turnover Margin': 'Turnover Margin', 'Total Offense': 'Yards per Game',
            'Passing Offense': 'Passing Yards', 'Rushing Offense': 'Rushing Yards', 'Total Defense': 'Points against',
            'Passing Defense': 'Completion Yards Against', 'Rushing Defense': 'Rush Yards Allowed'}
    order = [b['name'] for b in afl['stats']['teams']]
    out = []
    for cat in order:
        if cat not in rows:
            continue
        b = block('teams', cat, rows[cat], CALC.get(cat, set()), SORT[cat])
        if cat in ('Scoring Defense', 'Total Defense', 'Passing Defense', 'Rushing Defense', 'Penalties'):
            # "weniger ist besser": aufsteigend
            si = [c['title'] for c in b['columns']].index(SORT[cat])
            b['rows'].sort(key=lambda r: (r['values'][si] is None, r['values'][si] or 0))
        out.append(b)
    return out, sorted(tids)


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

# ---------------------------------------------------------------- Personen zusammenführen (Doppel-IDs im LOS)
groups = defaultdict(list)
for k, p in people.items():
    pid = p['ids'][0]
    sp = spieler.get(pid, {})
    groups[norm(sp.get('Firstname')) + '|' + norm(sp.get('Lastname'))].append(k)
merge_into = {}
for name, keys in groups.items():
    if len(keys) < 2:
        continue
    keys = sorted(keys, key=lambda k: int(k[2:]))
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            ra, rb = merge_into.get(a, a), merge_into.get(b, b)
            if ra == rb:
                continue
            pa, pb = people[ra], people[rb]
            ba = (spieler[int(a[2:])].get('Birthdate') or '')[:10]
            bb = (spieler[int(b[2:])].get('Birthdate') or '')[:10]
            weak = lambda x: (not x) or x.endswith('-01-01')  # noqa: E731
            same_birth = ba and bb and ba == bb
            teams_a = {t for ts in pa['teams'].values() for t in ts}
            teams_b = {t for ts in pb['teams'].values() for t in ts}
            overlap_season = set(pa['teams']) & set(pb['teams'])
            if overlap_season:
                continue
            if same_birth or ((weak(ba) or weak(bb)) and teams_a & teams_b):
                merge_into[rb] = ra
                report['merged'].append((ra, rb, pa['name'], ba, bb))


def root(k):
    while k in merge_into:
        k = merge_into[k]
    return k


for k in list(people):
    r = root(k)
    if r == k:
        continue
    pr, pk = people[r], people.pop(k)
    pr['ids'] = sorted(set(pr['ids'] + pk['ids']))
    for yr, n in pk.get('games', {}).items():
        pr.setdefault('games', {})[yr] = max(pr.get('games', {}).get(yr, 0), n)
    for yr, ts in pk['teams'].items():
        for t in ts:
            if t not in pr['teams'].setdefault(yr, []):
                pr['teams'][yr].append(t)
    for yr, cats in career.pop(k, {}).items():
        for cat, vals in cats.items():
            career[r][yr].setdefault(cat, vals)
# Schlüssel in den Saisondateien nachziehen
if merge_into:
    for yr in list(seasons_out):
        path = f'{OUT}/season-{yr}.json'
        data = json.load(open(path))
        for b in data['stats']['players']:
            for r in b['rows']:
                r['pid'] = root(r['pid'])
        json.dump(data, open(path, 'w'), ensure_ascii=False, separators=(',', ':'))

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
             'hd365': 977542, 'hd261': 988253}                    # Roman Seybold, Aaron Schernig
for l in links:
    if l['key'] in CONFIRMED and CONFIRMED[l['key']] == l['user_id']:
        l['conf'] = 'sicher: manuell bestätigt'
for k, u in CONFIRMED.items():
    if k in people and u in clubee and not any(l['key'] == k and l['user_id'] == u for l in links):
        links.append({'user_id': u, 'key': k, 'conf': 'sicher: manuell bestätigt', 'c': clubee[u], 'full': people[k]['name']})

# Konflikte: ein Archiv-Spieler -> mehrere Clubee-Profile
cnt = Counter(l['key'] for l in links if l['key'] and not l['conf'].startswith(('abgelehnt', 'mehrdeutig')))
player_map = {}
for l in links:
    if not l['key'] or l['conf'].startswith(('abgelehnt', 'mehrdeutig')):
        continue
    if cnt[l['key']] > 1:
        l['conf'] = 'KONFLIKT: mehrere Clubee-Profile – nicht verknüpft'
        continue
    player_map[l['key']] = l['user_id']

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
    car['people'][k] = entry
    if k in career:
        car['players'][k] = career[k]
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
print('zusammengeführte Doppel-IDs:', len(report['merged']))
for f in sorted(glob.glob(f'{OUT}/*.json')):
    print(os.path.basename(f), os.path.getsize(f))
