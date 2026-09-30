#!/usr/bin/env python3
"""
StatCrew-Statistiken der AFBÖ-Website (AFL 2013) -> Rohwerte je Spieler und Team.

Quellen (Kopien aus der Wayback Machine, Ordner „Statistiken/2013“):
  Austrian Football League 2013 Play Off - <Team>.html   Saisonwerte Grunddurchgang (10 Spiele je Team),
                                                         inkl. Spiel-für-Spiel-Seiten (Einsätze, Fumbles, Sacks je QB)
  13031.htm, 13032.htm, 13033.htm                         Boxscores Halbfinale und Austrian Bowl
  13030.htm                                               letztes Spiel des Grunddurchgangs (nur zur Kontrolle)

Die Teamseiten enthalten die Play-offs nicht („AFL Conf Games 2013“); sie werden aus den Boxscores addiert.

Aufruf zum Testen:  python3 statcrew.py <Ordner 2013>
"""
import glob
import html
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

POSITIONS = {'QB', 'RB', 'FB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB', 'K', 'P', 'LS', 'DE', 'DT', 'CB', 'S', 'SS', 'FS',
             'ATH', 'OT', 'OG', 'C', 'KR', 'PR', 'H'}


def norm(s):
    s = str(s or '').replace('ß', 'ss')
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def num(t):
    """'.' / '-' -> 0, '1.5' -> 1.5, '12' -> 12"""
    t = t.strip()
    if t in ('.', '-', '', '--'):
        return 0
    try:
        v = float(t)
    except ValueError:
        return 0
    return int(v) if v == int(v) else v


def pair(t, sep='-'):
    """'6-119' -> (6, 119); '1.5-14' -> (1.5, 14); '1-minus 5' etc. nicht erwartet; '.' -> (0, 0)"""
    t = t.strip()
    if t in ('.', '-', ''):
        return 0, 0
    m = re.match(r'^(-?[\d.]+)' + re.escape(sep) + r'(-?[\d.]+)$', t)
    if not m:
        return 0, 0
    return num(m.group(1)), num(m.group(2))


# ---------------------------------------------------------------- HTML -> Textabschnitte
def sections(path):
    """Text der <pre>-Blöcke, gruppiert nach dem jeweils letzten Anker (<a name=…>)."""
    s = open(path, encoding='latin-1').read()
    out = defaultdict(str)
    cur = 'start'
    for m in re.finditer(r'(?is)<a\s+name="?([^"\s>]+)"?[^>]*>|<pre[^>]*>(.*?)</pre>', s):
        if m.group(1) is not None:
            cur = m.group(1)
        else:
            out[cur] += html.unescape(re.sub(r'<[^>]+>', '', m.group(2))) + '\n'
    return out


def table(text, header, nvals, start=0):
    """Zeilen einer Textabelle: Kopfzeile beginnt mit `header`, danach Strichlinie, dann Zeilen bis zur Leerzeile.
    Gibt [(name_tokens, value_tokens)] zurück; der Name darf Leerzeichen enthalten."""
    lines = text.splitlines()
    for i in range(start, len(lines)):
        if re.match(r'^\s*' + re.escape(header) + r'(\s|$)', lines[i]):
            j = i + 1
            if j < len(lines) and lines[j].strip() and set(lines[j].strip()) <= set('-'):
                j += 1
            rows = []
            while j < len(lines) and lines[j].strip():
                toks = lines[j].split()
                if len(toks) > nvals:
                    rows.append((toks[:-nvals], toks[-nvals:]))
                j += 1
            return rows
    return []


def is_total(name):
    n = name.lower().rstrip('.')
    return n.startswith('total') or n.startswith('opponent')


PLACEHOLDER_NAMES = {'nobody', 'unknown', 'nn', 'n n', 'n.n.', 'tbd', 'player'}


def is_team_row(name):
    """Team-Zeilen und Platzhalter ohne echten Spielernamen"""
    n = name.lower().strip()
    return n.startswith('team ') or n.startswith('tm ') or n == 'tm' or n in PLACEHOLDER_NAMES


def strip_pos(name):
    t = name.split()
    if len(t) > 1 and t[-1] in POSITIONS:
        t = t[:-1]
    return ' '.join(t)


def two_cols(text):
    """'LABEL.......   own    opp' -> {label: (own, opp)}"""
    out = {}
    for line in text.splitlines():
        m = re.match(r'^\s*(.+?)(?:\.{2,}|\.?\s{2,})\s*(\S.*)$', line)
        if not m:
            continue
        label = m.group(1).strip().rstrip(':').strip()
        vals = [v for v in re.split(r'\s{2,}', m.group(2).strip()) if v]
        if len(vals) >= 2 and label not in out:
            out[label] = (vals[0], vals[1])
    return out


# ---------------------------------------------------------------- Teams
TEAM_CANON = {'vienna vikings': 'Vikings', 'vikings': 'Vikings', 'tyrolean raiders': 'Raiders', 'raiders': 'Raiders',
              'swarco raiders tirol': 'Raiders', 'graz giants': 'Giants', 'giants': 'Giants',
              'danube dragons': 'Dragons', 'dragons': 'Dragons', 'prague panthers': 'Panthers', 'panthers': 'Panthers',
              'prague black panthers': 'Panthers', 'rangers': 'Rangers', 'moedling rangers': 'Rangers',
              'salzburg bulls': 'Bulls', 'bulls': 'Bulls', 'st poelten invaders': 'Invaders', 'invaders': 'Invaders',
              'carinthian lions': 'Lions', 'lions': 'Lions', 'car black lions': 'Lions',
              'carinthian black lions': 'Lions', 'vikings vienna': 'Vikings', 'raiders tirol': 'Raiders',
              'raiders tyrol': 'Raiders', 'blue devils': 'Blue Devils', 'blue devils hohenems': 'Blue Devils',
              'hohenems blue devils': 'Blue Devils', 'cineplexx blue devils': 'Blue Devils',
              'carinthian cowboys': 'Cowboys', 'carinthian falcons': 'Falcons'}
TEAM_IDS = {'Dragons': 1, 'Giants': 2, 'Panthers': 3, 'Vikings': 4, 'Raiders': 5, 'Blue Devils': 16, 'Rangers': 18,
            'Bulls': 901, 'Invaders': 902, 'Lions': 903, 'Cowboys': 904, 'Falcons': 905}


# Eindeutige Tippfehler in StatCrew-Tabellen (gleiche Person, gleiche Saison, gleiches Team)
NAME_TYPOS = {
    'Sivstko G.': 'Gabor Sviatko',     # Panthers 2011 (Kicker/Punter, sonst "Gabor Sviatko"/"G.Sviatko")
}


def canon_team(name):
    return TEAM_CANON.get(norm(name), name.strip())


# ---------------------------------------------------------------- Namen
def abbrev_parts(a):
    """'A.Good' -> ('a', 'good'); 'J.W.Liebmann' -> ('j', 'liebmann'); 'Ponce de Leon' -> (None, 'ponce de leon');
    'WERNER S.' -> ('s', 'werner') (Nachname zuerst)"""
    a = a.strip()
    m = re.match(r'^([A-Za-zÄÖÜäöü]{1,3})(?:[.\-][A-Za-z]{1,2})*\.\s*(\S.*)$', a)
    if m:
        return norm(m.group(1)), norm(m.group(2))
    m = re.match(r'^([A-Za-zÄÖÜäöü\-]+)\s+([A-Za-z])\.$', a)
    if m:
        return m.group(2).lower(), norm(m.group(1))
    return None, norm(a)


def looks_abbrev(name):
    return bool(re.match(r'^[A-Za-z]{1,3}(?:[.\-][A-Za-z]{1,2})*\.\s*\S', name) or re.search(r'\s[A-Za-z]\.$', name))


def pretty_abbrev(a):
    """'A.Ponce de Leon' -> 'A. Ponce de Leon'; 'UHL M.' -> 'M. Uhl'"""
    a = a.strip()
    m = re.match(r'^([A-Za-z]{1,3})(?:[.\-][A-Za-z]{1,2})*\.\s*(\S.*)$', a)
    if not m:
        m2 = re.match(r'^([A-Za-zÄÖÜäöü\-]+)\s+([A-Za-z])\.$', a)
        if not m2:
            return a
        ini, last = m2.group(2), m2.group(1)
    else:
        ini, last = m.group(1), m.group(2)
    if last.isupper():
        last = last.title()
    return f'{ini[0].upper()}{ini[1:].lower()}. {last}'


def full_matches_abbrev(full, a):
    ini, last = abbrev_parts(a)
    f = norm(full)
    if not last or not f:
        return False
    if not (f == last or f.endswith(' ' + last)):
        return False
    return ini is None or f.startswith(ini)


def abbrev_match_len(full, a):
    """Länge der passenden Vornamen-Initiale (0 = passt nicht, 99 = Kurzform ohne Initiale)"""
    if not full_matches_abbrev(full, a):
        return 0
    ini = abbrev_parts(a)[0]
    return len(ini) if ini else 99


class Roster:
    """Spieler eines Teams: Schlüssel = laufende Nummer; Namen (voll/abgekürzt), Trikotnummern, Einsätze."""

    def __init__(self, team):
        self.team = team
        self.players = []          # dicts: full, abbrevs, jerseys, gp_reg, games_po (set)
        self.full_only = False     # Kader nur mit vollen Namen (Teamseite ohne Einsatzliste, z. B. 2011)

    def _new(self):
        p = {'full': None, 'abbrevs': set(), 'jerseys': set(), 'gp_reg': 0, 'games_reg': set(), 'games_po': set(),
             'names': set()}
        self.players.append(p)
        return p

    def find(self, name, jersey=None, date=None):
        """Spieler zu einem Namen aus einer Tabelle (voll oder abgekürzt), ohne neu anzulegen.
        date: Spiel, in dem der Spieler laut Einsatzliste dabei war (bevorzugt bei gleichen Kurzformen)."""
        name = name.strip()
        if not name or re.match(r'^\d+$', name) or is_team_row(name) or is_total(name):
            return None
        if looks_abbrev(name):
            return self.by_jersey_abbrev(jersey, name, date=date) or self.by_full(name, jersey, date=date)
        return self.by_full(name, jersey, date=date)

    def merge_same_names(self):
        """Gleiche Kurzform (Initiale + Nachname) im selben Team ohne gemeinsames Spiel = dieselbe Person
        (StatCrew-Eingabe mit wechselnder Schreibweise/Trikotnummer, z. B. 'M.Wenzel' und 'WENZEL M.')."""
        merged = True
        while merged:
            merged = False
            for i, a in enumerate(self.players):
                ka = {abbrev_parts(x) for x in a['abbrevs']}
                for b in self.players[i + 1:]:
                    kb = {abbrev_parts(x) for x in b['abbrevs']}
                    if any(k[0] for k in ka & kb) and not (a['games_reg'] & b['games_reg']):
                        a['abbrevs'] |= b['abbrevs']; a['jerseys'] |= b['jerseys']; a['games_reg'] |= b['games_reg']
                        a['gp_reg'] = len(a['games_reg'])
                        self.players.remove(b)
                        merged = True
                        break
                if merged:
                    break

    def display(self, p):
        if p['full'] and not looks_abbrev(p['full']):
            return p['full']
        a = p['full'] or sorted(p['abbrevs'], key=lambda x: (not re.match(r'^[A-Za-z]\.', x), x))[0]
        return pretty_abbrev(a)

    def by_jersey_abbrev(self, jersey, ab, create=False, date=None, new_game=False):
        """new_game: Einsatzliste eines Spiels – gleiche Kurzform mit anderer Trikotnummer gilt als derselbe Spieler,
        solange er in diesem Spiel noch nicht erfasst ist (Trikotwechsel im Lauf der Saison)."""
        ini, last = abbrev_parts(ab)
        pool = self.players
        if date and not new_game:
            here = [p for p in self.players if date in p['games_po']]
            pool = here + [p for p in self.players if date not in p['games_po']]
        for p in pool:
            if jersey in p['jerseys'] and any(abbrev_parts(x)[1] == last for x in p['abbrevs']) \
                    and not (new_game and date in p['games_po']):
                return p
        for p in pool:
            if any(abbrev_parts(x) == (ini, last) for x in p['abbrevs']) and (
                    not jersey or not p['jerseys'] or jersey in p['jerseys']
                    or (new_game and ini and date not in p['games_po'])) and not (new_game and date in p['games_po']):
                if jersey and new_game:
                    p['jerseys'].add(jersey)
                return p
        if self.full_only:
            # Kurzform aus dem Boxscore gegen die vollen Namen der Teamseite ('C.Gross' -> Christoph Gross,
            # 'A.Ponce de Leon' -> Armando Ponce deLeon, Tippfehler 'C.Gros' -> Christoph Gross)
            import difflib

            def sq(x):
                return x.replace(' ', '')

            def fits(p, fuzzy):
                if not p['full'] or looks_abbrev(p['full']) or (new_game and date in p['games_po']):
                    return False
                f = norm(p['full'])
                rest = sq(' '.join(f.split()[1:])) or sq(f)
                if ini and not f.startswith(ini):
                    return False
                if fuzzy:
                    return difflib.SequenceMatcher(None, rest, sq(last)).ratio() >= 0.85
                return sq(f).endswith(sq(last))
            for fuzzy in (False, True):
                cands = [p for p in pool if fits(p, fuzzy)]
                if jersey and len(cands) > 1:
                    cj = [p for p in cands if jersey in p['jerseys']]
                    cands = cj if len(cj) == 1 else [p for p in cands if not p['jerseys'] or jersey in p['jerseys']]
                if len(cands) == 1:
                    if jersey and new_game:
                        cands[0]['jerseys'].add(jersey)
                    return cands[0]
                if cands:
                    break
        if create:
            p = self._new()
            p['abbrevs'].add(ab)
            if jersey:
                p['jerseys'].add(jersey)
            return p
        return None

    def by_full(self, full, jersey=None, fuzzy=True, date=None):
        f = norm(full)
        if not f:
            return None
        exact = [p for p in self.players if p['full'] and norm(p['full']) == f or f in {norm(n) for n in p['names']}]
        if date and len(exact) > 1:
            exact = [p for p in exact if date in p['games_po']] or exact
        if len(exact) == 1:
            return exact[0]
        score = {id(p): max([abbrev_match_len(full, a) for a in p['abbrevs']] or [0]) for p in self.players}
        best_len = max(score.values() or [0])
        cands = [p for p in self.players if best_len and score[id(p)] == best_len]
        if date and len(cands) > 1:
            cands = [p for p in cands if date in p['games_po']] or cands
        if jersey:
            cj = [p for p in cands if jersey in p['jerseys']]
            if len(cj) == 1:
                return cj[0]
            cj = [p for p in self.players if jersey in p['jerseys']]
            if len(cj) == 1 and fuzzy and _similar_name(full, cj[0]):
                return cj[0]
        if len(cands) == 1:
            return cands[0]
        if fuzzy:
            # Tippfehler / Schreibvarianten ("Fanian Seeber", "Korbinian Hofmann" / "K.Hoffmann")
            best = [p for p in self.players if _similar_name(full, p)]
            if len(best) == 1:
                return best[0]
        return None

    def attach_full(self, p, full):
        p['names'].add(full)
        if not p['full'] or (looks_abbrev(p['full']) and not looks_abbrev(full)) \
                or (' ' not in p['full'].strip() and ' ' in full.strip() and not looks_abbrev(full)):
            p['full'] = full        # volle Namen vor Kurzformen, "Dan Krejbich" vor "DanKrejbich"


def _similar_name(full, p):
    import difflib
    f = norm(full).split()
    if not f:
        return False
    for a in p['abbrevs']:
        ini, last = abbrev_parts(a)
        if ini and not f[0].startswith(ini):
            continue
        if difflib.SequenceMatcher(None, ' '.join(f[1:]) or f[0], last).ratio() >= 0.8:
            return True
    for n in p['names']:
        if difflib.SequenceMatcher(None, norm(n), norm(full)).ratio() >= 0.9:
            return True
    return False


# ---------------------------------------------------------------- Teamseite (Grunddurchgang)
def parse_team_page(path):
    sec = sections(path)
    mt = re.search(r'^\s*(\S.*?) Game Results', sec.get('tgbg.res', '') or sec.get('start', ''), re.M)
    team = canon_team(mt.group(1)) if mt else canon_team(re.search(r' - (.+?)\.html?$', os.path.basename(path)).group(1))
    R = Roster(team)
    R.full_only = 'igbg.ply' not in sec     # nur volle Namen (keine Einsatzliste mit Kurzformen)
    stats = defaultdict(Counter)     # id(player) -> Werte
    longs = defaultdict(dict)
    pid = id

    # Spiele laut "Game Results" (inkl. noch nicht gespielter); Play-off-Spiele, die in den Saisonsummen fehlen
    # ("Statistics do not include N post-season game(s)"), stecken nur in den Spiel-für-Spiel-Seiten
    results = parse_results(sec.get('tgbg.res', '') or sec.get('start', ''))
    mnote = re.search(r'do not include (\d+) post-season', sec.get('team.tem', '') + sec.get('team.ind', ''))
    n_post = int(mnote.group(1)) if mnote else 0
    played_nonconf = [g for g in results if g['played'] and not g['conf']]
    post = {g['idx'] for g in played_nonconf[-n_post:]} if n_post else set()
    post_dates = {g['date'] for g in results if g['idx'] in post}

    # Einsätze (Spiel-für-Spiel): Trikot, Kurzname, Spiele (ohne Play-off-Spalten)
    for line in sec.get('igbg.ply', '').splitlines():
        toks = line.split()
        gi = next((i for i, t in enumerate(toks) if re.match(r'^\d+/[\d-]+$', t)), None)
        if gi is None or gi == 0 or toks[0] == '##':
            continue
        jersey = toks[0] if re.match(r'^\d+$', toks[0]) else None
        name = ' '.join(toks[1:gi] if jersey else toks[:gi])
        if re.match(r'^\d+$', name):
            continue          # ohne Namen erfasst (nur Trikotnummer) – nicht zuordenbar
        all_games = {i for i, t in enumerate(toks[gi + 1:]) if t == 'XXX'}
        games_ = all_games - post
        gp_token = int(toks[gi].split('/')[0])    # offizielle Spielzahl (wie in den Einzeltabellen)
        gp = gp_token - len(all_games & post)
        if gp <= 0 and not games_:
            continue
        p = R._new()
        p['abbrevs'].add(name)
        if jersey:
            p['jerseys'].add(jersey)
        p['games_reg'] = games_
        p['gp_reg'] = gp
    R.merge_same_names()

    ind, dfn = sec.get('team.ind', ''), sec.get('team.def', '')

    def player(name, jersey=None, table_gp=None):
        if is_total(name) or is_team_row(name) or re.match(r'^\d+$', name.strip()):
            return None
        name = NAME_TYPOS.get(name.strip(), name)
        p = R.find(name, jersey)
        if p is None:
            p = R._new()
            if jersey:
                p['jerseys'].add(jersey)
            if looks_abbrev(name):
                p['abbrevs'].add(name)
        R.attach_full(p, name)
        if table_gp and not p['gp_reg']:
            p['gp_reg'] = table_gp
        return p

    totals = {'own': Counter(), 'opp': Counter()}

    def tot(name, key, v):
        n = name.lower()
        if n.startswith('total'):
            totals['own'][key] += v
        elif n.startswith('opponent'):
            totals['opp'][key] += v

    # Verteidigung zuerst (hat Trikotnummern -> sichere Zuordnung)
    for nt, v in table(dfn, 'DEFENSIVE LEADERS', 13):
        if nt and (re.match(r'^\d+$', nt[0]) or nt[0] == 'TM'):
            jersey, name = nt[0], ' '.join(nt[1:])
        else:
            jersey, name = None, ' '.join(nt)
        if is_total(name):
            if name.lower().startswith('total'):
                totals['own']['blk_kicks'] += num(v[11])
            else:
                totals['opp']['blk_kicks'] += num(v[11])
            continue
        if jersey == 'TM' or is_team_row(name) or re.match(r'^\d+$', name):
            continue
        p = player(name, jersey, int(num(v[0])))
        s = stats[pid(p)]
        s['solo'] += num(v[1]); s['ast'] += num(v[2]); s['tot'] += num(v[3])
        s['tfl'] += pair(v[4])[0]; s['sacks'] += pair(v[5])[0]
        s['int'] += pair(v[6])[0]; s['pbu'] += num(v[7]); s['qbh'] += num(v[8])
        s['fr'] += pair(v[9])[0]; s['ff'] += num(v[10]); s['blk'] += num(v[11]); s['saf_def'] += num(v[12])
        s['def_seen'] += 1

    for nt, v in table(ind, 'RUSHING', 9):
        name = ' '.join(nt)
        tot(name, 'rush_long', 0)
        if is_total(name):
            if name.lower().startswith('total'):
                longs['team']['rush_long'] = num(v[7])
            else:
                longs['team']['opp_rush_long'] = num(v[7])
            continue
        p = player(name, table_gp=int(num(v[0])))
        if p is None:
            continue
        s = stats[pid(p)]
        s['rush_att'] += num(v[1]); s['rush_yds'] += num(v[4]); s['rush_td'] += num(v[6])
        longs[pid(p)]['rush_long'] = max(longs[pid(p)].get('rush_long', -99), num(v[7]))
    att_first = bool(re.search(r'^PASSING\s+GP\s+Effic\s+Att-Cmp-Int', ind, re.M))
    for nt, v in table(ind, 'PASSING', 8):
        name = ' '.join(nt)
        c, a, i = [int(x) for x in v[2].split('-')]
        if att_first:             # ältere Seiten (bis 2007): "Att-Cmp-Int"
            a, c = c, a
        if is_total(name):
            if name.lower().startswith('opponent'):
                longs['team']['opp_pass_long'] = num(v[6])
            else:
                longs['team']['pass_long'] = num(v[6])
            continue
        p = player(name, table_gp=int(num(v[0])))
        if p is None or a == 0:
            continue
        s = stats[pid(p)]
        s['pass_att'] += a; s['pass_cmp'] += c; s['pass_int'] += i; s['pass_yds'] += num(v[4]); s['pass_td'] += num(v[5])
    for nt, v in table(ind, 'RECEIVING', 7):
        name = ' '.join(nt)
        if is_total(name):
            continue
        p = player(name, table_gp=int(num(v[0])))
        if p is None:
            continue
        s = stats[pid(p)]
        s['rec'] += num(v[1]); s['rec_yds'] += num(v[2]); s['rec_td'] += num(v[4])
    for hdr, pre in (('PUNT RETURNS', 'pr'), ('KICK RETURNS', 'kr'), ('INTERCEPTIONS', 'ir'), ('FUMBLE RETURNS', 'fret')):
        for nt, v in table(ind, hdr, 5):
            name = ' '.join(nt)
            if is_total(name):
                tot(name, pre, num(v[0])); tot(name, pre + '_yds', num(v[1])); tot(name, pre + '_td', num(v[3]))
                continue
            p = player(name)
            if p is None:
                continue
            s = stats[pid(p)]
            s[pre] += num(v[0]); s[pre + '_yds'] += num(v[1]); s[pre + '_td'] += num(v[3])
    for nt, v in table(ind, 'SCORING', 9):
        name = ' '.join(nt)
        fgm, fga = pair(v[1]); xpm, xpa = pair(v[2]); r2m, r2a = pair(v[3]); p2m, p2a = pair(v[5])
        if is_total(name):
            side = 'own' if name.lower().startswith('total') else 'opp'
            T = totals[side]
            T['td'] += num(v[0]); T['fgm'] += fgm; T['fga'] += fga; T['xpm'] += xpm; T['xpa'] += xpa
            T['two_made'] += r2m + p2m; T['two_att'] += r2a + p2a; T['dxp'] += num(v[6]); T['saf'] += num(v[7])
            T['pts'] += num(v[8])
            continue
        p = player(name)
        if p is None:
            continue
        s = stats[pid(p)]
        s['fgm'] += fgm; s['fga'] += fga; s['xpm'] += xpm; s['xpa'] += xpa
    for nt, v in table(ind, 'FIELD GOALS', 9):
        name = ' '.join(nt)
        p = R.find(NAME_TYPOS.get(name, name))
        if p is not None:
            longs[pid(p)]['fg_long'] = num(v[7])
    for nt, v in table(ind, 'PUNTING', 8):
        name = ' '.join(nt)
        if is_total(name):
            continue
        p = player(name)
        if p is None:
            continue
        s = stats[pid(p)]
        s['punt'] += num(v[0]); s['punt_yds'] += num(v[1]); s['punt_tb'] += num(v[4]); s['punt_fc'] += num(v[5])
        s['punt_i20'] += num(v[6]); s['punt_blk'] += num(v[7])
    for nt, v in table(ind, 'ALL PURPOSE', 8):
        name = ' '.join(nt)
        if not is_total(name):
            player(name, table_gp=int(num(v[0])))

    # Sacks je Quarterback (Spiel-für-Spiel Passing). Die Spiel-für-Spiel-Seiten enthalten auch Play-off-Spiele, die
    # in den Saisonsummen fehlen ("do not include N post-season games") -> deren Anteil je Datum merken (post_extra),
    # damit er abgezogen werden kann, wenn es für das Spiel keinen Boxscore gibt.
    played = [g for g in results if g['played']]
    post_extra = defaultdict(lambda: defaultdict(Counter))    # id(player) -> Datum -> Werte

    def row_dates(opps):
        """Zeilen je Gegner (chronologisch) -> Spieldaten (Gegner können mehrfach vorkommen)"""
        out, j = [], 0
        for o in opps:
            no = norm(o)
            k = j
            while k < len(played) and not (norm(played[k]['opp']).startswith(no) or no.startswith(norm(played[k]['opp']))
                                            or canon_team(played[k]['opp']) == canon_team(o)):
                k += 1
            if k < len(played):
                out.append(played[k]['date'])
                j = k + 1
            else:
                out.append(None)
        return out

    cur, rows, sep_cols = None, [], True
    for line in sec.get('igbg.pas', '').splitlines() + ['']:
        m = re.match(r'^\s*#(\S*)\s+(.+?)\s+Att\s+Comp', line)
        if m:
            cur, rows = (m.group(1) or None, m.group(2).strip()), []
            sep_cols = 'Sack-Yds' not in line        # ältere Seiten (2004–2006): "Sack  Yds" in zwei Spalten
            continue
        if not cur:
            continue

        def sacks(toks):
            return (num(toks[-2]), num(toks[-1])) if sep_cols else pair(toks[-2])
        if line.strip().startswith('TOTALS'):
            sk, sky = sacks(line.split())
            p = R.find(cur[1], cur[0])
            if p is not None:
                stats[pid(p)]['sacked'] += sk
                stats[pid(p)]['sacked_yds'] += sky
                if post_dates:
                    for d, (a, b) in zip(row_dates([r[0] for r in rows]), [r[1] for r in rows]):
                        if d in post_dates:
                            post_extra[pid(p)][d]['sacked'] += a
                            post_extra[pid(p)][d]['sacked_yds'] += b
            cur = None
            continue
        mr = re.match(r'^\s*(\S.*?)\.{2,}\s+(-?\d.*)$', line)
        if mr:
            rows.append((mr.group(1).strip(), sacks(mr.group(2).split())))
    # Fumbles je Spieler (Anzahl-verloren), Spalten = Spiele in der Reihenfolge der Ergebnisse
    fsec = sec.get('igbg.fmb', '')
    fcols = []
    for line in fsec.split('FUMBLES FORCED')[0].splitlines():
        mh = re.match(r'^\s*FUMBLES\s+No-Lost\s+(.*)$', line)
        if mh:
            fcols = mh.group(1).split()
            continue
        m = re.match(r'^\s*(.+?)\.{2,}\s*(\d+)-(\d+)\s', line + ' ')
        if not m:
            continue
        name = strip_pos(m.group(1).strip())
        if is_team_row(name):
            continue
        p = R.find(name)
        if p is not None:
            stats[pid(p)]['fum'] += int(m.group(2)); stats[pid(p)]['fum_lost'] += int(m.group(3))
            vals = line[m.end():].split()
            if post_dates and len(fcols) == len(played) and len(vals) == len(played):
                for g, v in zip(played, vals):
                    if g['date'] in post_dates:
                        a, b = pair(v)
                        post_extra[pid(p)][g['date']]['fum'] += a
                        post_extra[pid(p)][g['date']]['fum_lost'] += b

    # Punkte wie in der AFBÖ-Rangliste aus den Einzelteilen (TD, XP, FG, 2-Pt, Safety, DXP). Die Summe der Teamseite
    # enthält manchmal Punkte eines Spiels ohne Statistik (Lions 2009: 27:36 in St. Pölten) oder weicht um einen
    # Extra Point ab (Raiders 2008).
    for side in ('own', 'opp'):
        T = totals[side]
        calc = 6 * T['td'] + T['xpm'] + 3 * T['fgm'] + 2 * T['two_made'] + 2 * T['saf'] + 2 * T['dxp']
        if T['pts'] != calc:
            T['pts_page'] = T['pts']
            T['pts'] = calc

    # Teamwerte
    tc = two_cols(sec.get('team.tem', ''))

    def tv(label, side):
        return tc.get(label, ('0', '0'))[0 if side == 'own' else 1]
    for side in ('own', 'opp'):
        T = totals[side]
        T['rush_net'] = num(tv('RUSHING YARDAGE', side)); T['rush_att'] = num(tv('Rushing Attempts', side))
        T['rush_td'] = num(tv('TDs Rushing', side))
        a, c, i = [int(x) for x in tv('Att-Comp-Int', side).split('-')]
        T['pass_att'], T['pass_cmp'], T['pass_int'] = a, c, i
        T['pass_yds'] = num(tv('PASSING YARDAGE', side)); T['pass_td'] = num(tv('TDs Passing', side))
        T['tot_yds'] = num(tv('TOTAL OFFENSE', side)); T['plays'] = num(tv('Total Plays', side))
        T['fum'], T['fum_lost'] = pair(tv('FUMBLES-LOST', side))
        T['pen'], T['pen_yds'] = pair(tv('PENALTIES-YARDS', side))
        T['punts'], T['punt_yds'] = pair(tv('PUNTS-YARDS', side))
        T['punt_net_yds'] = round(num(tv('Net punt average', side)) * T['punts'], 1)
        T['d3_conv'], T['d3_att'] = pair(tv('3RD-DOWN CONVERSIONS', side), '/')
        T['sacks_by'], T['sacks_by_yds'] = pair(tv('SACKS BY-YARDS', side))
        T['td_scored'] = num(tv('TOUCHDOWNS SCORED', side))
        T['games'] = 0
    # Spiele (Grunddurchgang bzw. alle, die in den Saisonsummen stecken)
    uniq = [{'date': g['date'], 'opp': g['opp'], 'pf': g['pf'], 'pa': g['pa']} for g in results
            if g['played'] and g['idx'] not in post]
    totals['own']['games'] = totals['opp']['games'] = len(uniq)
    totals['own']['rush_long'] = longs['team'].get('rush_long', 0)
    totals['own']['pass_long'] = longs['team'].get('pass_long', 0)
    totals['opp']['rush_long'] = longs['team'].get('opp_rush_long', 0)
    totals['opp']['pass_long'] = longs['team'].get('opp_pass_long', 0)
    # Spiel-für-Spiel Teamwerte (für "Spiele mit Kick/Punt" bei nur einem Kicker/Punter)
    kick_games, punt_games = 0, 0
    tg = sec.get('tgbg.tem', '')
    blocks = tg.split('|---------TACKLES')
    if len(blocks) > 1:
        rest = blocks[1]
        kpart, ppart = rest.split('|------------------PUNTING')[0], ('|---' + rest.split('|------------------PUNTING')[1]) if 'PUNTING' in rest else ''
        kg = {}
        for line in kpart.splitlines():
            m = re.match(r'^\s*(\w{3}[ .]\d{1,2},\s?\d{4})\s.*?\s(\d+)-(\d+)\s+\d+\s+\d+\s+\d+\s+\d+\s*$', line)
            if m and norm_date(m.group(1)) not in post_dates:
                kg[m.group(1)] = int(m.group(2)) > 0
        pg, fg = {}, {}
        for line in ppart.splitlines():
            m = re.match(r'^\s*(\w{3}[ .]\d{1,2},\s?\d{4})\s+\S.*?\.{2,}\s+(.*)$', line)
            if m and norm_date(m.group(1)) not in post_dates:
                toks = m.group(2).split()
                pg[m.group(1)] = int(toks[0]) > 0
                fa = toks[9] if len(toks) > 9 else '0-0'
                fg[m.group(1)] = pair(fa)[0] > 0
        kick_games = sum(1 for d in set(kg) | set(fg) if kg.get(d) or fg.get(d))
        punt_games = sum(1 for v in pg.values() if v)
    else:
        kick_games = punt_games = None     # keine Spiel-für-Spiel-Teamwerte (z. B. 2011)
    # Ohne Spiel-für-Spiel-Seiten (2011: nur Saisonsummen) gibt es keine Einsatzliste, keine Sacks je Quarterback und
    # keine Fumbles je Spieler. Einsätze: Spielzahl (GP) aus den Tabellen; als Spiele-Menge ein Platzhalter für den
    # ganzen Grunddurchgang (zwei Einträge desselben Teams gelten damit immer als "gemeinsam gespielt").
    no_gbg = 'igbg.ply' not in sec
    if no_gbg:
        for p in R.players:
            if p['gp_reg'] or id(p) in stats:
                p['games_reg'] = {'GD'}
    return {'team': team, 'roster': R, 'stats': stats, 'longs': longs, 'totals': totals, 'games': uniq,
            'kick_games': kick_games, 'punt_games': punt_games, 'post_dates': post_dates, 'no_gbg': no_gbg,
            'post_extra': post_extra, 'name': mt.group(1).strip() if mt else team,
            'has_sacks': bool(sec.get('igbg.pas')), 'has_fum': bool(sec.get('igbg.fmb'))}


def norm_date(s):
    m = re.match(r'^\s*(\w{3})[ .,]\s*(\d+),\s*(\d{4})', s)
    return f'{m.group(1)} {int(m.group(2)):02d}, {m.group(3)}' if m else s.strip()


def parse_results(text):
    """Zeilen der "Game Results": Datum, Gegner, Conference-Spiel (*), gespielt, Punkte"""
    out = []
    for line in text.splitlines():
        m = re.match(r'^\s*(\*?)\s*(\w{3}[ .]\d{1,2},\s?\d{4})\s+((?:at|vs)\s+)?(\S.*?)\s{2,}(.*)$', line)
        if not m:
            continue
        rest = m.group(5)
        # "W  23-14", "6-24  L", Wertungen "WO 56-55" / "O 55-56  L" – das eigene Ergebnis steht immer zuerst
        sm = re.match(r'^(?:[A-Z]{1,2}\s+)?(\d+)-(\d+)(?:\s|$)', rest)
        opp = re.sub(r'^#\d+\s+', '', m.group(4).strip())      # Fußnotenzeichen "#1 Vienna Vikings"
        g = {'idx': len(out), 'conf': m.group(1) == '*', 'date': norm_date(m.group(2)), 'opp': opp.title(),
             'played': bool(sm), 'pf': None, 'pa': None}
        if sm:
            g['pf'], g['pa'] = int(sm.group(1)), int(sm.group(2))
        out.append(g)
    return out


# ---------------------------------------------------------------- Boxscore (einzelnes Spiel)
def box_header(path):
    """(Team 1, Team 2, Datum 'Mon DD, YYYY') aus dem Boxscore – Namen wie im Boxscore"""
    sec = sections(path)
    pat = r'(?:^|\n)\s*(\S.*?) vs (\S.*?) \((\w{3})[ ,.]\s*(\d+),\s*(\d{4})'
    m = re.search(pat, sec.get('GAME.TEM', '')) or re.search(pat, '\n'.join(sec.values()))
    if not m:
        t = re.search(r'(?is)<title>(.*?)</title>', open(path, encoding='latin-1').read())
        m = re.search(pat, html.unescape(t.group(1))) if t else None
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip(), f'{m.group(3)} {int(m.group(4)):02d}, {m.group(5)}'


def starting_lineups(pre, raw):
    """Startaufstellungen im Participation Report (nur manche Boxscores, z. B. Austrian Bowl 2011):
    zwei Spalten 'POS  ## OFFENSE' / 'POS  ## DEFENSE' -> {Team: [(Trikot, Kurzname), …]}"""
    out = defaultdict(list)
    lines = pre.splitlines()
    for i, line in enumerate(lines):
        if not re.match(r'^\s*POS\s+##\s+(OFFENSE|DEFENSE)', line):
            continue
        cut = line.find('POS', line.find('POS') + 3)
        # Reihenfolge der Teams: Kopfzeile mit beiden Namen über den Tabellen
        head = next((l for l in reversed(lines[:i]) if all(raw[t] in l for t in raw)), None)
        order = sorted(raw, key=lambda t: head.find(raw[t])) if head else list(raw)
        for l in lines[i + 1:]:
            if not l.strip():
                break
            for part, t in ((l[:cut], order[0]), (l[cut:], order[1])):
                m = re.match(r'^\s*[A-Z/]{1,4}\s+(\d+)\s+(\S.*?)\s*$', part) if cut > 0 else None
                if m:
                    out[t].append((m.group(1), m.group(2)))
    return out


def parse_box(path, rosters, create_rosters=False):
    """rosters: {Team: Roster} – Spieler werden den Kadern der Teamseiten zugeordnet (neu angelegt, wenn unbekannt).
    Teams werden auf die Kurzform abgebildet (canon_team); create_rosters legt fehlende Kader an (Saisons nur mit
    Boxscores, z. B. 2010)."""
    sec = sections(path)
    tem = sec.get('GAME.TEM', '')
    raw1, raw2, date = box_header(path)
    t1, t2 = canon_team(raw1), canon_team(raw2)
    for t in (t1, t2):
        if t not in rosters and create_rosters:
            rosters[t] = Roster(t)
    raw = {t1: raw1, t2: raw2}
    hdr = re.search(r'^\s+([A-Z]{2,4})\s+([A-Z]{2,4})\s*$', tem, re.M)
    abbr = {hdr.group(1): t1, hdr.group(2): t2}
    teams = (t1, t2)
    split_re = r'\n\s*(' + '|'.join(re.escape(raw[t]) for t in teams) + r')\s*\n'
    by_raw = {raw[t]: t for t in teams}
    tc = two_cols(tem)
    out = {'date': date, 'teams': teams, 'raw_names': raw, 'players': {t: defaultdict(Counter) for t in teams},
           'longs': {t: defaultdict(dict) for t in teams}, 'totals': {t: Counter() for t in teams},
           'played': {t: set() for t in teams}, 'unresolved': []}

    def P(team, name, jersey=None, create=True):
        R = rosters[team]
        if is_total(name) or is_team_row(name) or re.match(r'^\d+$', name.strip()):
            return None
        name = NAME_TYPOS.get(name.strip(), name)
        p = R.find(name, jersey, date=date)
        if p is None and create:
            p = R._new()
            if jersey:
                p['jerseys'].add(jersey)
            out['unresolved'].append((team, name, jersey))
        if p is not None:
            R.attach_full(p, name)
        return p

    # Teilnahme
    pre = sec.get('GAME.PRE', '')
    starters = starting_lineups(pre, raw)
    for t in teams:
        m = re.search(re.escape(raw[t]) + r':(.*?)(?:\n\s*\n|\Z)', pre, re.S)
        items = [x.strip() for x in re.sub(r'\s+', ' ', m.group(1)).split(', ')] if m else []
        if items and items[-1].endswith('.') and not re.search(r'\s[A-Z]\.$', items[-1]):
            items[-1] = items[-1][:-1]
        items = [f'{j}-{ab}' for j, ab in starters.get(t, [])] + items
        for it in items:
            mm = re.match(r'^(\d+)-(.+)$', it)
            if not mm:
                continue
            R, j, ab = rosters[t], mm.group(1), mm.group(2).strip()
            p = R.by_jersey_abbrev(j, ab, date=date, new_game=True)
            if p is None:
                q = R.find(ab)
                p = q if q is not None and date not in q['games_po'] else None
            if p is None:
                if R.players and not create_rosters:
                    out['unresolved'].append((t, 'nur Play-offs: ' + it, None))
                p = R._new()
                p['jerseys'].add(j)
            p['abbrevs'].add(ab)
            out['played'][t].add(id(p))
            p['games_po'].add(date)

    # Einzelstatistik
    ind = sec.get('GAME.IND', '')
    parts = re.split(split_re, '\n' + ind)
    blocks = {}
    for i in range(1, len(parts) - 1, 2):
        blocks[by_raw[parts[i]]] = parts[i + 1]
    for t, txt in blocks.items():
        S, L = out['players'][t], out['longs'][t]
        for nt, v in table(txt, 'Rushing', 7):
            name = ' '.join(nt)
            if is_total(name):
                out['totals'][t]['rush_long'] = num(v[5])
                continue
            p = P(t, name)
            if p is None:
                continue
            s = S[id(p)]
            s['rush_att'] += num(v[0]); s['rush_yds'] += num(v[3]); s['rush_td'] += num(v[4])
            L[id(p)]['rush_long'] = max(L[id(p)].get('rush_long', -99), num(v[5]))
        for nt, v in table(txt, 'Passing', 5):
            name = ' '.join(nt)
            a, c, i = [int(x) for x in v[0].split('-')]
            if is_total(name):
                out['totals'][t]['pass_long'] = num(v[3])
                continue
            p = P(t, name)
            if p is None or (a == 0 and not num(v[4])):
                continue
            s = S[id(p)]
            s['pass_att'] += a; s['pass_cmp'] += c; s['pass_int'] += i; s['pass_yds'] += num(v[1])
            s['pass_td'] += num(v[2]); s['sacked'] += num(v[4])
        for nt, v in table(txt, 'Receiving', 4):
            name = ' '.join(nt)
            if is_total(name):
                continue
            p = P(t, name)
            if p is None:
                continue
            s = S[id(p)]
            s['rec'] += num(v[0]); s['rec_yds'] += num(v[1]); s['rec_td'] += num(v[2])
        for nt, v in table(txt, 'Punting', 6):
            name = ' '.join(nt)
            if is_total(name):
                continue
            p = P(t, name)
            if p is None:
                continue
            s = S[id(p)]
            s['punt'] += num(v[0]); s['punt_yds'] += num(v[1]); s['punt_i20'] += num(v[4]); s['punt_tb'] += num(v[5])
            s['punt_games'] += 1 if num(v[0]) else 0
        for nt, v in table(txt, 'All Returns', 9):
            name = ' '.join(nt)
            if is_total(name):
                continue
            p = P(t, name)
            if p is None:
                continue
            s = S[id(p)]
            s['pr'] += num(v[0]); s['pr_yds'] += num(v[1]); s['kr'] += num(v[3]); s['kr_yds'] += num(v[4])
            s['ir'] += num(v[6]); s['ir_yds'] += num(v[7])
        fg_part = txt.split('Field goal attempts')[1].split('Kickoffs')[0] if 'Field goal attempts' in txt else ''
        for line in fg_part.splitlines():
            mm = re.match(r'^\s*(.+?)\s+(1st|2nd|3rd|4th|OT)\s+\d+:\d+\s+(\d+) yds - (.+)$', line)
            if not mm:
                continue
            p = P(t, mm.group(1).strip())
            if p is None:
                continue
            s = S[id(p)]
            s['fga'] += 1
            if mm.group(4).strip().lower().startswith('good'):
                s['fgm'] += 1
                L[id(p)]['fg_long'] = max(L[id(p)].get('fg_long', 0), int(mm.group(3)))
            s['kick_game'] = 1
    # Fumbles
    new = sec.get('GAME.NEW', '')
    fm = re.search(r'FUMBLES:(.*?)(?:\n\s*\n)', new, re.S)
    if fm:
        txt = re.sub(r'\s+', ' ', fm.group(1))
        for t in teams:
            mt = re.search(re.escape(raw[t]) + r'-(.*?)(?:\.\s+(?:' + '|'.join(re.escape(raw[x]) for x in teams) + r')-|\.$|$)', txt)
            if not mt:
                continue
            for it in mt.group(1).split(';'):
                mm = re.match(r'^\s*(.+?)\s+(\d+)-(\d+)\s*$', it.strip().rstrip('.'))
                if not mm or mm.group(1).lower() == 'none':
                    continue
                p = P(t, mm.group(1).strip())
                if p is None:
                    continue
                out['players'][t][id(p)]['fum'] += int(mm.group(2))
                out['players'][t][id(p)]['fum_lost'] += int(mm.group(3))
    # Verteidigung
    dfn = sec.get('GAME.DEF', '')
    parts = re.split(split_re, '\n' + dfn)
    for i in range(1, len(parts) - 1, 2):
        t = by_raw[parts[i]]
        for nt, v in table(parts[i + 1], '##', 11):
            jersey, name = (nt[0], ' '.join(nt[1:])) if re.match(r'^\d+$', nt[0]) else (None, ' '.join(nt))
            if is_team_row(name):
                out['totals'][t]['blk_kicks'] += num(v[8])
                continue
            p = P(t, name, jersey)
            if p is None:
                continue
            s = out['players'][t][id(p)]
            s['solo'] += num(v[0]); s['ast'] += num(v[1]); s['tot'] += num(v[2])
            s['tfl'] += pair(v[3], '/')[0]; s['ff'] += num(v[4]); s['fr'] += pair(v[5])[0]
            s['int'] += pair(v[6])[0]; s['pbu'] += num(v[7]); s['blk'] += num(v[8])
            s['sacks'] += pair(v[9], '/')[0]; s['qbh'] += num(v[10])
            out['totals'][t]['blk_kicks'] += num(v[8])
            s['def_seen'] += 1
    # Punkte und Touchdowns aus der Scoring Summary
    for t in teams:
        out['totals'][t].update({'td': 0, 'rush_td_s': 0, 'pass_td_s': 0, 'pr_td': 0, 'kr_td': 0, 'ir_td': 0,
                                 'fret_td': 0, 'xpm': 0, 'xpa': 0, 'two_made': 0, 'two_att': 0, 'saf': 0, 'dxp': 0})
    body = new.split('Scoring Summary:')[1] if 'Scoring Summary:' in new else ''
    body = body.split('\n\n\n')[0]
    for line in body.splitlines():
        mm = re.match(r'^\s*(?:1st|2nd|3rd|4th|OT)?\s*\d+:\d+\s+([A-Z]{2,4}) - (.+?)(?:,\s*[^,]*)?,\s*[A-Z]{2,4} \d+ - [A-Z]{2,4} \d+\s*$', line)
        if not mm:
            continue
        t = abbr.get(mm.group(1))
        if t is None:
            continue
        T = out['totals'][t]
        d = mm.group(2)
        pm = re.search(r'\((.*)\)\s*$', d)
        play = d[:pm.start()].strip() if pm else d
        pat = pm.group(1) if pm else ''
        m2 = re.match(r'^(.+?) (-?\d+) yd (run|pass from (.+)|punt return|kickoff return|interception return|fumble return|'
                      r'fumble recovery|field goal|(?:blocked|missed) (?:fg|field goal|punt|kick|pat) return|[a-z ]*return|[a-z ]*recovery)$',
                      play, re.I)
        if 'safety' in play.lower():
            T['saf'] += 1
            continue
        if not m2:
            out['unresolved'].append((t, 'Scoring: ' + play, None))
            continue
        who, kind = m2.group(1), m2.group(3).lower()
        if kind == 'field goal':
            continue
        T['td'] += 1
        pl = P(t, who)
        if kind == 'run':
            T['rush_td_s'] += 1
        elif kind.startswith('pass from'):
            T['pass_td_s'] += 1
        elif kind == 'punt return':
            T['pr_td'] += 1
            if pl is not None:
                out['players'][t][id(pl)]['pr_td'] += 1
        elif kind == 'kickoff return':
            T['kr_td'] += 1
            if pl is not None:
                out['players'][t][id(pl)]['kr_td'] += 1
        elif kind == 'interception return':
            T['ir_td'] += 1
            if pl is not None:
                out['players'][t][id(pl)]['ir_td'] += 1
        else:
            T['fret_td'] += 1
            if pl is not None:
                out['players'][t][id(pl)]['fret_td'] += 1
        if pat:
            km = re.match(r'^(.+?) kick(?: (failed|blockd|blocked|no good))?$', pat)
            if km:
                T['xpa'] += 1
                kp = P(t, km.group(1).strip())
                if kp is not None:
                    out['players'][t][id(kp)]['xpa'] += 1
                    out['players'][t][id(kp)]['kick_game'] = 1
                if not km.group(2):
                    T['xpm'] += 1
                    if kp is not None:
                        out['players'][t][id(kp)]['xpm'] += 1
            else:
                T['two_att'] += 1
                if not re.search(r'fail|intcpt|intercept|incomplete|no good|block|fumbl', pat.lower()):
                    T['two_made'] += 1
    # Teamwerte
    for idx, t in enumerate(teams):
        T = out['totals'][t]
        g = lambda label: tc.get(label, ('0', '0'))[idx]   # noqa: E731
        T['games'] = 1
        T['rush_net'] = num(g('NET YARDS RUSHING')); T['rush_att'] = num(g('Rushing Attempts'))
        T['rush_td'] = num(g('Rushing Touchdowns'))
        c, a, i = [int(x) for x in g('Completions-Attempts-Int').split('-')]
        T['pass_att'], T['pass_cmp'], T['pass_int'] = a, c, i
        T['pass_yds'] = num(g('NET YARDS PASSING')); T['pass_td'] = num(g('Passing Touchdowns'))
        T['tot_yds'] = num(g('TOTAL OFFENSE YARDS')); T['plays'] = num(g('Total offense plays'))
        T['fum'], T['fum_lost'] = pair(g('Fumbles: Number-Lost'))
        T['pen'], T['pen_yds'] = pair(g('Penalties: Number-Yards'))
        T['punts'], T['punt_yds'] = pair(g('PUNTS-YARDS'))
        T['punt_net_yds'] = round(num(g('Net Yards Per Punt')) * T['punts'], 1)
        pr = g('Punt returns: Number-Yards-TD').split('-')
        kr = g('Kickoff returns: Number-Yds-TD').split('-')
        ir = g('Interceptions: Number-Yds-TD').split('-')
        fr = g('Fumble Returns: Number-Yds-TD').split('-')
        T['pr'], T['pr_yds'] = num(pr[0]), num(pr[1]); T['kr'], T['kr_yds'] = num(kr[0]), num(kr[1])
        T['ir'], T['ir_yds'] = num(ir[0]), num(ir[1]); T['fret'], T['fret_yds'] = num(fr[0]), num(fr[1])
        d3 = re.match(r'(\d+) of (\d+)', g('Third-Down Conversions'))
        T['d3_conv'], T['d3_att'] = int(d3.group(1)), int(d3.group(2))
        T['sacks_by'], T['sacks_by_yds'] = pair(g('Sacks By: Number-Yards'))
        T['fgm'], T['fga'] = pair(g('Field Goals'))
        pk = pair(g('PAT Kicks'))
        T['xpm_box'], T['xpa_box'] = pk
        if 'PAT Kicks' in ' '.join(tc):     # offizielle PAT-Zeile des Boxscores (zählt abgebrochene Kicks mit)
            T['xpm'], T['xpa'] = pk
        T['fair_catch'] = num(g('Fair catch'))
    for line in new.splitlines():
        mm = re.match(r'^\s*(\S.*?)\.*\s+(?:\d+\s+){4,5}-\s+(\d+)\b', line)
        if not mm:
            continue
        for t in teams:
            nm = mm.group(1).strip().rstrip('.')
            if raw[t].startswith(nm) or nm.startswith(raw[t]) or nm == t:
                out['totals'][t].setdefault('pts', int(mm.group(2)))
    return out


# ---------------------------------------------------------------- Saison zusammensetzen
def load_season(team_pages=(), box_files=(), check_file=None):
    """Teamseiten (Saisonwerte) + Boxscores weiterer Spiele (Play-offs bzw. alle Spiele, wenn es keine Teamseiten
    gibt). Teams ohne Teamseite bekommen einen Kader aus den Boxscores."""
    T = {}
    for p in team_pages:
        d = parse_team_page(p)
        T[d['team']] = d
    rosters = {t: d['roster'] for t, d in T.items()}
    boxes = [parse_box(f, rosters, create_rosters=True) for f in box_files]
    for t, R in rosters.items():
        if t not in T:
            T[t] = {'team': t, 'roster': R, 'stats': {}, 'longs': {}, 'games': [], 'kick_games': 0, 'punt_games': 0,
                    'totals': {'own': Counter(), 'opp': Counter()}}
    check = parse_box(check_file, {t: _clone_roster(r) for t, r in rosters.items()}) if check_file else None
    return T, boxes, check


def find_files(folder):
    """Teamseiten (Anker team.ind) und Boxscores (Anker GAME.TEM) in einem Ordner"""
    pages, boxes = [], []
    for f in sorted(glob.glob(os.path.join(folder, '*.htm')) + glob.glob(os.path.join(folder, '*.HTM'))
                    + glob.glob(os.path.join(folder, '*.html'))):
        s = open(f, encoding='latin-1').read()
        if re.search(r'(?i)<a\s+name="?team\.ind', s):
            pages.append(f)
        elif re.search(r'(?i)<a\s+name="?GAME\.TEM', s):
            boxes.append(f)
    return pages, boxes


def _clone_roster(R):
    import copy
    return copy.deepcopy(R)


# ---------------------------------------------------------------- Werte im Clubee-Format
def _div(a, b, f=1.0, n=1):
    if not b:
        return None
    v = round(a / b * f, n)
    return int(v) if v == int(v) else v


def _r(v, n=1):
    if v is None:
        return None
    v = round(float(v), n)
    return int(v) if v == int(v) else v


def player_values(s, L, gp, sp_kick, sp_punt, partial=False):
    """Rohwerte eines Spielers (Summen) -> Werte je Clubee-Kategorie (Spaltentitel wie in Clubee).
    partial: Sacks/Fumbles je Spieler nicht erfasst (Saison ohne Spiel-für-Spiel-Seiten) -> leer statt 0;
    True (beides) oder {'sk': bool, 'fum': bool}"""
    s = Counter(s)
    v = {}
    miss_sk = partial if isinstance(partial, bool) else partial.get('sk', False)
    miss_fum = partial if isinstance(partial, bool) else partial.get('fum', False)
    if s['pass_att'] > 0:
        a_, c_, y_, td_, i_ = s['pass_att'], s['pass_cmp'], s['pass_yds'], s['pass_td'], s['pass_int']
        v['Passing'] = {'Games': gp, 'Pass Attempts': a_, 'Completions': c_, 'Passing Yards': y_,
                        'Pass Touchdowns': td_, 'Interceptions Thrown': i_,
                        'Completion Percentage': _div(c_, a_, 100), 'Sacks Taken': None if miss_sk else s['sacked'],
                        'Passer Rating': _r((8.4 * y_ + 330 * td_ + 100 * c_ - 200 * i_) / a_, 1)}
    if s['rec'] > 0:
        v['Receiving'] = {'Games': gp, 'Receptions': s['rec'], 'Targets': None, 'Catch Percentage': None,
                          'Receiving Yards': s['rec_yds'], 'Yards per Reception': _div(s['rec_yds'], s['rec']),
                          'Receiving Touchdowns': s['rec_td']}
    if s['rush_att'] > 0:
        v['Rushing'] = {'Games': gp, 'Rush Attempts': s['rush_att'], 'Rushing Yards': s['rush_yds'],
                        'Yards per Attempt': _div(s['rush_yds'], s['rush_att']), 'Rush Touchdown': s['rush_td'],
                        'Fumbles': None if miss_fum else s['fum']}
    if s['solo'] + s['ast'] + s['int'] + s['pbu'] + s['sacks'] > 0:
        v['Defense'] = {'Games': gp, 'Total Tackles': _r(s['solo'] + s['ast'] * 0.5), 'Solo Tackles': s['solo'],
                        'Assisted Tackles': _r(s['ast'] * 0.5), 'Tackles for Loss': _r(s['tfl']),
                        'Sacks': _r(s['sacks']), 'Interceptions For': s['int'], 'Pass Breakups': s['pbu'],
                        'Defensive Touchdowns': s['ir_td'] + s['fret_td']}
    if s['kr'] + s['pr'] > 0:
        v['Returns'] = {'Games': gp, 'Kickoff Return Yards': s['kr_yds'],
                        'Kickoff Return Average': _div(s['kr_yds'], s['kr']), 'Kickoff Return Touchdowns': s['kr_td'],
                        'Punt Return Yards': s['pr_yds'], 'Punt Return Average': _div(s['pr_yds'], s['pr']),
                        'Punt Return Touchdowns': s['pr_td']}
    if s['fga'] + s['xpa'] > 0:
        v['Kicking'] = {'Spiele mit Kick': sp_kick, 'Field Goals verwandelt': s['fgm'], 'Field-Goal-Versuche': s['fga'],
                        'Field-Goal-Quote': _div(s['fgm'], s['fga'], 100),
                        'Längstes Field Goal (Yards, berechnet)': (L.get('fg_long') or None) if s['fgm'] else None,
                        'Extra Points verwandelt': s['xpm'], 'Extra Points verschossen': s['xpa'] - s['xpm'],
                        'Extra-Point-Quote': _div(s['xpm'], s['xpa'], 100),
                        'Punkte durch Kicks (FG × 3 + XP)': s['fgm'] * 3 + s['xpm']}
    if s['punt'] > 0:
        v['Punting'] = {'Spiele mit Punt': sp_punt, 'Punts': s['punt'], 'Geblockt': s['punt_blk'], 'Ins Aus': None,
                        'Mit Return': None, 'Fair Catch': s['punt_fc'], 'Touchback': s['punt_tb']}
    return v


def merge_players(entries):
    """Mehrere 2013-Einträge derselben Person (ohne gemeinsames Spiel) zusammenfassen"""
    raw, L = Counter(), {}
    for e in entries:
        raw.update(e['raw'])
        for k, v in e['longs'].items():
            L[k] = max(L.get(k, -99), v)
    games = sorted({g for e in entries for g in e['games']})
    gp = sum(e['gp'] for e in entries)

    def sp(key):
        vals = [e[key] for e in entries]
        return None if any(x is None for x in vals) else sum(vals)
    m = dict(entries[0])
    m.update({'raw': dict(raw), 'longs': L, 'games': games, 'gp': gp, 'sp_kick': sp('sp_kick'), 'sp_punt': sp('sp_punt'),
              'names': sorted({n for e in entries for n in e['names']}),
              'abbrevs': sorted({n for e in entries for n in e['abbrevs']})})
    def miss(k):
        return any((e.get('partial') if isinstance(e.get('partial'), bool) else (e.get('partial') or {}).get(k))
                   for e in entries)
    m['partial'] = {'sk': miss('sk'), 'fum': miss('fum')}
    m['v'] = player_values(raw, L, gp, m['sp_kick'], m['sp_punt'], m['partial'])
    return m


def season_from_folder(folder, exclude=(), fixes=None):
    """Alle Teamseiten eines Ordners + die Boxscores der Spiele, die nicht schon in den Saisonsummen der Teamseiten
    stecken (z. B. Play-offs). Boxscores bereits enthaltener Spiele dienen nur zur Kontrolle (Rückgabe 'covered').
    exclude: Dateinamen von Spielen, die nicht zur AFL-Saison zählen (Europacup, Freundschaftsspiele …)."""
    pages, boxes = find_files(folder)
    covered = set()
    for p in pages:
        sec = sections(p)
        mt = re.search(r'^\s*(\S.*?) Game Results', sec.get('tgbg.res', '') or sec.get('start', ''), re.M)
        team = canon_team(mt.group(1)) if mt else None
        res = parse_results(sec.get('tgbg.res', '') or sec.get('start', ''))
        mnote = re.search(r'do not include (\d+) post-season', sec.get('team.tem', '') + sec.get('team.ind', ''))
        n_post = int(mnote.group(1)) if mnote else 0
        nonconf = [g for g in res if g['played'] and not g['conf']]
        post = {g['idx'] for g in nonconf[-n_post:]} if n_post else set()
        for g in res:
            if g['played'] and g['idx'] not in post:
                covered.add((g['date'], frozenset((team, canon_team(g['opp'])))))
    use, checks = [], []
    for b in boxes:
        if os.path.basename(b) in exclude:
            continue
        h = box_header(b)
        key = (h[2], frozenset((canon_team(h[0]), canon_team(h[1]))))
        (checks if key in covered else use).append(b)
    S = season(pages, use, fixes=fixes)
    S['files'] = {'pages': [os.path.basename(x) for x in pages], 'boxes': [os.path.basename(x) for x in use],
                  'covered': [os.path.basename(x) for x in checks], 'excluded': sorted(exclude)}
    return S


def season(team_pages=(), box_files=(), check_file=None, fixes=None):
    """Eine StatCrew-Saison im Aufbau der Clubee-Kategorien (Spaltentitel wie in Clubee).
    team_pages: Teamseiten mit Saisonwerten; box_files: Boxscores der Spiele, die nicht in den Teamseiten stecken.
    Rückgabe: {'players': [...], 'teams': [...], 'games': n, 'report': {...}}"""
    T, boxes, check = load_season(team_pages, box_files, check_file)
    fixes = fixes or {}
    # Fehler der Quelle: Spiele, die eine Teamseite fälschlich enthält (z. B. Lions 2007: Spiel der Raiders)
    for t, dte in fixes.get('drop_games', ()):
        before = len(T[t]['games'])
        T[t]['games'] = [g for g in T[t]['games'] if g['date'] != dte]
        for side in ('own', 'opp'):
            T[t]['totals'][side]['games'] -= before - len(T[t]['games'])
    out_players, out_teams = [], []
    report = {'unresolved': [u for b in boxes for u in b['unresolved']], 'teams': {}}
    for t, d in T.items():
        R = d['roster']
        st = d['stats']
        kickers = [p for p in R.players if st.get(id(p), {}).get('fga', 0) + st.get(id(p), {}).get('xpa', 0) > 0]
        punters = [p for p in R.players if st.get(id(p), {}).get('punt', 0) > 0]
        # Play-offs dieses Teams
        my_boxes = [b for b in boxes if t in b['teams']]
        for b in my_boxes:   # Fair Catches (nur Teamwert im Boxscore) dem einzigen Punter des Spiels zuordnen
            ps = [pid_ for pid_, x in b['players'][t].items() if x.get('punt', 0) > 0]
            if len(ps) == 1:
                b['players'][t][ps[0]]['punt_fc'] += b['totals'][t].get('fair_catch', 0)
        for p in R.players:
            s = Counter(st.get(id(p), {}))
            L = dict(d['longs'].get(id(p), {}))
            po_kick = po_punt = 0
            for b in my_boxes:
                bs = b['players'][t].get(id(p))
                if not bs:
                    continue
                skip = ('kick_game', 'punt_games', 'def_seen')
                if b['date'] in d.get('post_dates', ()):
                    skip += ('sacked', 'fum', 'fum_lost')   # stecken schon in den Spiel-für-Spiel-Summen der Teamseite
                for k, v in bs.items():
                    if k not in skip:
                        s[k] += v
                po_kick += 1 if bs.get('kick_game') else 0
                po_punt += 1 if bs.get('punt', 0) > 0 else 0
                for k, v in b['longs'][t].get(id(p), {}).items():
                    L[k] = max(L.get(k, -99), v)
            box_dates = {b['date'] for b in my_boxes}
            for dte, c in d.get('post_extra', {}).get(id(p), {}).items():
                if dte not in box_dates:     # Play-off-Spiel ohne Boxscore: nicht zählen (wie in den Saisonsummen)
                    for k, v in c.items():
                        s[k] -= v
            gp = (p['gp_reg'] or 0) + len(p['games_po'])
            if not gp and not any(s.values()):
                continue
            name = R.display(p)
            if s['fga'] + s['xpa'] > 0:
                if len(kickers) == 1 and kickers[0] is p:
                    sp_kick = None if d['kick_games'] is None else d['kick_games'] + po_kick
                elif not kickers:
                    sp_kick = po_kick
                else:
                    sp_kick = None      # mehrere Kicker im Grunddurchgang: Spiele je Kicker nicht erfasst
            else:
                sp_kick = 0
            if s['punt'] > 0:
                if len(punters) == 1 and punters[0] is p:
                    sp_punt = None if d['punt_games'] is None else d['punt_games'] + po_punt
                elif not punters:
                    sp_punt = po_punt
                else:
                    sp_punt = None
            else:
                sp_punt = 0
            games = sorted({f'{t}#{i}' for i in p['games_reg']} | set(p['games_po']))
            # ohne Spiel-für-Spiel-Seiten (Passing/Fumbles): Sacks (QB) bzw. Fumbles je Spieler fehlen im Grunddurchgang
            on_page = bool(p['gp_reg'] or id(p) in st)
            partial = {'sk': on_page and not d.get('has_sacks', True), 'fum': on_page and not d.get('has_fum', True)}
            out_players.append({'team': t, 'tid': TEAM_IDS.get(t), 'name': name, 'abbrevs': sorted(p['abbrevs']),
                                'names': sorted(p['names']), 'jerseys': sorted(p['jerseys']), 'gp': gp,
                                'games': games, 'raw': dict(s), 'longs': L, 'sp_kick': sp_kick, 'sp_punt': sp_punt,
                                'full_name': bool(p['full']) and not looks_abbrev(p['full']), 'partial': partial,
                                'v': player_values(s, L, gp, sp_kick, sp_punt, partial)})
        # Teamwerte: Grunddurchgang (Teamseite) + Play-offs (Boxscores)
        own, opp = Counter(d['totals']['own']), Counter(d['totals']['opp'])
        lng = {'rush_long': own['rush_long'], 'pass_long': own['pass_long'], 'opp_pass_long': opp['pass_long']}
        for b in my_boxes:
            o = [x for x in b['teams'] if x != t][0]
            for k, val in b['totals'][t].items():
                if isinstance(val, (int, float)) and not k.endswith('_long') and not k.endswith('_box') and k != 'fair_catch':
                    own[k] += val
            for k, val in b['totals'][o].items():
                if isinstance(val, (int, float)) and not k.endswith('_long') and not k.endswith('_box') and k != 'fair_catch':
                    opp[k] += val
            lng['rush_long'] = max(lng['rush_long'], b['totals'][t].get('rush_long', 0))
            lng['pass_long'] = max(lng['pass_long'], b['totals'][t].get('pass_long', 0))
            lng['opp_pass_long'] = max(lng['opp_pass_long'], b['totals'][o].get('pass_long', 0))
        g = own['games']
        def_td = max(0, own['td'] - own['rush_td'] - own['pass_td'] - own['kr_td'] - own['pr_td'])
        opp_def_td = max(0, opp['td'] - opp['rush_td'] - opp['pass_td'] - opp['kr_td'] - opp['pr_td'])
        mar = own['ir'] + opp['fum_lost'] - own['pass_int'] - own['fum_lost']
        tv = {
            'Penalties': {'Games': g, 'Penalties Against': own['pen'], 'Penalty Against Yards': own['pen_yds'],
                          'Penalty Against Yds/Game': _div(own['pen_yds'], g, 1, 2), 'Penalties For': opp['pen'],
                          'Penalty For Yards': opp['pen_yds'], 'Penalty For Yds/Game': _div(opp['pen_yds'], g, 1, 2)},
            'Scoring Offense': {'Games': g, 'Rush Touchdown': own['rush_td'], 'Pass Touchdowns': own['pass_td'],
                                'Defensive Touchdowns': def_td, 'Punt Return Touchdowns': own['pr_td'],
                                'Kickoff Return Touchdowns': own['kr_td'], 'Total Touchdowns': own['td'],
                                'Field Goal': own['fgm'], '2-Point Conversion': own['two_made'], 'Safeties': own['saf'],
                                'Extra Point Kick': own['xpm'], 'Defensive Extra Points': own['dxp'], 'Points': own['pts'],
                                'Average Points per Game': _div(own['pts'], g, 1, 2)},
            'Scoring Defense': {'Games': g, 'Rush TDs Allowed': opp['rush_td'], 'Pass TDs Allowed': opp['pass_td'],
                                'Defensive TDs Allowed': opp_def_td, 'Punt Return TDs Allowed': opp['pr_td'],
                                'Kickoff Return TDs Allowed': opp['kr_td'], 'Total TDs Allowed': opp['td'],
                                'Field Goals Allowed': opp['fgm'], '2-Point Conversions Allowed': opp['two_made'],
                                'Safeties Conceded': opp['saf'], 'Extra Points Allowed': opp['xpm'],
                                'Def. Extra Points Allowed': opp['dxp'], 'Points Allowed': opp['pts'],
                                'Avg Points Allowed per Game': _div(opp['pts'], g, 1, 2)},
            'Special Teams': {'Games': g, 'Field Goals Made': own['fgm'], 'Field Goal Attempts': own['fga'],
                              'Field Goal Percentage': _div(own['fgm'], own['fga'], 100), 'Extra Points Made': own['xpm'],
                              'Extra Point Attempts': own['xpa'], 'Extra Point Percentage': _div(own['xpm'], own['xpa'], 100),
                              'Punt Average': _div(own['punt_yds'], own['punts']),
                              'Net Punt Average': _div(own['punt_net_yds'], own['punts']),
                              'Kickoff Return Average': _div(own['kr_yds'], own['kr']),
                              'Punt Return Average': _div(own['pr_yds'], own['pr']), 'Blocked Kicks': own['blk_kicks'],
                              'Punt Return Touchdowns': own['pr_td'], 'Kickoff Return Touchdowns': own['kr_td']},
            'Turnover Margin': {'Games': g, 'Interceptions For': own['ir'], 'Fumbles Recovered': opp['fum_lost'],
                                'Interceptions Against': own['pass_int'], 'Fumbles Lost': own['fum_lost'],
                                'Turnover Margin': mar, 'Turnover Margin/Game': _div(mar, g, 1, 2)},
            'Total Offense': {'Games': g, 'Points per Game': _div(own['pts'], g, 1, 2), 'Yards per Game': _div(own['tot_yds'], g),
                              'Rush Yards per Game': _div(own['rush_net'], g), 'Pass Yards per Game': _div(own['pass_yds'], g),
                              'Rush Touchdown': own['rush_td'], 'Pass Touchdowns': own['pass_td'],
                              'Interceptions Against': own['pass_int'], 'Sacks Allowed': opp['sacks_by'],
                              '3rd Down Percentage': _div(own['d3_conv'], own['d3_att'], 100)},
            'Passing Offense': {'Games': g, 'Pass Attempts': own['pass_att'], 'Completions': own['pass_cmp'],
                                'Completion Percentage': _div(own['pass_cmp'], own['pass_att'], 100),
                                'Passing Yards': own['pass_yds'], 'Pass Yards per Game': _div(own['pass_yds'], g),
                                'Pass Touchdowns': own['pass_td'], 'Interceptions Against': own['pass_int'],
                                'Yards per Completion': _div(own['pass_yds'], own['pass_cmp'])},
            'Rushing Offense': {'Games': g, 'Rush Attempts': own['rush_att'], 'Rushing Yards': own['rush_net'],
                                'Rush Yards per Game': _div(own['rush_net'], g), 'Rush Touchdown': own['rush_td'],
                                'Yards per Attempt': _div(own['rush_net'], own['rush_att']), 'Longest Play': lng['rush_long'],
                                'Fumbles': own['fum']},
            'Total Defense': {'Games': g, 'Points against': opp['pts'], 'Points Against per Game': _div(opp['pts'], g, 1, 2),
                              'Rush Yards Allowed': opp['rush_net'], 'Rush Yards Allowed per Game': _div(opp['rush_net'], g),
                              'Total Yards Allowed': opp['tot_yds'], 'Pass Yards Allowed per Game': _div(opp['pass_yds'], g),
                              'Sacks': _r(own['sacks_by']), 'Interceptions For': own['ir'],
                              '3rd Down Stop %': _r(100 - opp['d3_conv'] / opp['d3_att'] * 100, 1) if opp['d3_att'] else None},
            'Passing Defense': {'Games': g, 'Completions Against': opp['pass_cmp'], 'Pass Attempts Against': opp['pass_att'],
                                'Completion Yards Against': opp['pass_yds'],
                                'Opponent Completion %': _div(opp['pass_cmp'], opp['pass_att'], 100),
                                'Pass Yards Allowed per Game': _div(opp['pass_yds'], g), 'Pass TDs Allowed': opp['pass_td'],
                                'Longest Completion Allowed': lng['opp_pass_long'], 'Interceptions For': own['ir'],
                                'Sacks': _r(own['sacks_by'])},
            'Rushing Defense': {'Games': g, 'Rush Attempts Against': opp['rush_att'], 'Rush Yards Allowed': opp['rush_net'],
                                'Rush Yards Allowed per Game': _div(opp['rush_net'], g),
                                'Rush Yards per Attempt Allowed': _div(opp['rush_net'], opp['rush_att']),
                                'Rush TDs Allowed': opp['rush_td']},
        }
        if t in fixes.get('no_team_stats', ()):
            report['teams'][t] = {'regular': len(d['games']), 'playoffs': len(my_boxes), 'points': None,
                                  'points_against': None, 'omitted': True}
            continue
        out_teams.append({'team': t, 'tid': TEAM_IDS.get(t), 'name': d.get('name', t), 'v': tv, 'own': dict(own), 'opp': dict(opp),
                          'games': d['games'], 'playoffs': [b['date'] for b in my_boxes]})
        report['teams'][t] = {'regular': len(d['games']), 'playoffs': len(my_boxes), 'points': own['pts'],
                              'points_against': opp['pts']}
    n_games = len({(g_['date'], frozenset((t, canon_team(g_['opp'])))) for t, d in T.items() for g_ in d['games']}) + len(boxes)
    return {'players': out_players, 'teams': out_teams, 'games': n_games, 'report': report, 'check': check,
            'team_names': {TEAM_IDS.get(t): d.get('name', t) for t, d in T.items()}}



if __name__ == '__main__':
    folder = sys.argv[1]
    pages, boxes_ = find_files(folder)
    S = season(pages, [b for b in boxes_ if b not in sys.argv[2:]])
    print('Spiele:', S['games'])
    for t in S['teams']:
        print(t['team'], 'Punkte', t['v']['Scoring Offense']['Points'], ':', t['v']['Scoring Defense']['Points Allowed'],
              'G', t['v']['Scoring Offense']['Games'])
    print('ungeklärt:', S['report']['unresolved'])
