"""
Doppelte Spieler-IDs im Hockeydata-Archiv finden.

Im alten System wurde dieselbe Person teils mehrfach angelegt (andere Schreibweise, fehlendes Geburtsdatum,
neu erfasst beim Vereinswechsel). Dieses Modul vergleicht alle IDs, die in AFL-Spielprotokollen im Kader
stehen, und liefert:
  groups   – sichere Zusammenführungen  {kanonische_id: [ids…]}
  review   – unsichere Kandidaten zur Prüfung durch das Ligamanagement

Eine Person kann nie zwei IDs haben, die im selben Spiel im Kader stehen – das ist die wichtigste Bremse.
"""
import collections
import difflib
import itertools
import re
import unicodedata

SUFFIX = {'jr', 'sr', 'ii', 'iii', 'iv'}
NICK = {('nick', 'nicholas'), ('nick', 'nikolaus'), ('nico', 'nicolas'), ('nico', 'nikolaus'), ('alex', 'alexander'),
        ('max', 'maximilian'), ('mike', 'michael'), ('chris', 'christoph'), ('chris', 'christopher'),
        ('chris', 'christian'), ('flo', 'florian'), ('tom', 'thomas'), ('tommy', 'thomas'), ('dan', 'daniel'),
        ('dani', 'daniel'), ('matt', 'matthew'), ('matt', 'matthias'), ('eddie', 'edwin'), ('ed', 'edward'),
        ('bob', 'robert'), ('rob', 'robert'), ('bill', 'william'), ('will', 'william'), ('jim', 'james'),
        ('jimmy', 'james'), ('joe', 'joseph'), ('tony', 'anthony'), ('sam', 'samuel'), ('ben', 'benjamin'),
        ('andi', 'andreas'), ('andy', 'andreas'), ('andy', 'andrew'), ('fabi', 'fabian'), ('basti', 'sebastian'),
        ('steve', 'stephen'), ('steve', 'steven'), ('dave', 'david'), ('kris', 'kristopher'), ('pat', 'patrick'),
        ('rick', 'richard'), ('ricky', 'richard'), ('dom', 'dominik'), ('jonny', 'jonathan'), ('johnny', 'john'),
        ('jon', 'jonathan'), ('zach', 'zachary'), ('zack', 'zachary'), ('nate', 'nathan'), ('rudi', 'rudolf'),
        ('toni', 'anton'), ('manu', 'manuel'), ('hanz', 'hans'), ('jake', 'jacob'), ('jake', 'jakob'),
        ('josh', 'joshua'), ('danny', 'daniel'), ('mo', 'mohamed'), ('sepp', 'josef'), ('seppi', 'josef'),
        ('nick', 'nikolas'), ('nick', 'niklas'), ('nick', 'nicolas'), ('niko', 'nikolas'), ('niko', 'nikolaus')}


def norm(s):
    s = str(s or '').replace('ß', 'ss').replace('ẞ', 'ss')
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def phon(s):
    s = norm(s).replace(' ', '')
    for a, b in (('sch', 's'), ('ph', 'f'), ('ck', 'k'), ('tz', 'z'), ('dt', 't'), ('th', 't'), ('ie', 'i'),
                 ('ei', 'ai'), ('ey', 'ai'), ('ay', 'ai'), ('ae', 'a'), ('oe', 'o'), ('ue', 'u'), ('y', 'i'),
                 ('w', 'v'), ('c', 'k'), ('q', 'k'), ('x', 'ks'), ('z', 's'), ('h', '')):
        s = s.replace(a, b)
    return re.sub(r'(.)\1+', r'\1', s)


def weak_birth(b):
    return (not b) or b.endswith('-01-01') or b.startswith('1900') or b == '1969-12-31'


def lastparts(s):
    return [x for x in norm(s).replace('-', ' ').split() if x not in SUFFIX]


def last_sim(a, b):
    ta, tb = lastparts(a), lastparts(b)
    if not ta or not tb:
        return 0.0, ''
    ja, jb = ''.join(ta), ''.join(tb)
    if ja == jb:
        return 1.0, 'gleich'
    if phon(ja) == phon(jb):
        return 0.95, 'Schreibweise'
    common = set(ta) & set(tb)
    if common and max(len(x) for x in common) >= 4 and (len(ta) > 1 or len(tb) > 1):
        return 0.9, 'Doppelname'
    r = difflib.SequenceMatcher(None, ja, jb).ratio()
    return r, 'ähnlich' if r >= 0.8 else ''


def first_sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.6, 'fehlt'
    ta, tb = set(a.split()), set(b.split())
    if ta & tb:
        return 1.0, 'gleich'
    ca, cb = a.replace(' ', ''), b.replace(' ', '')
    if ca == cb:
        return 1.0, 'gleich'
    # Initiale ("R" / "Romed")
    if (len(ca) == 1 and cb.startswith(ca)) or (len(cb) == 1 and ca.startswith(cb)):
        return 0.85, 'Initiale'
    if min(len(ca), len(cb)) >= 4 and (ca.startswith(cb) or cb.startswith(ca)):
        return 0.9, 'Kurzform'
    for x in ta:
        for y in tb:
            if (x, y) in NICK or (y, x) in NICK:
                return 0.9, 'Spitzname'
            if phon(x) == phon(y):
                return 0.9, 'Schreibweise'
    r = difflib.SequenceMatcher(None, ca, cb).ratio()
    return r, 'ähnlich' if r >= 0.8 else ''


def birth_rel(a, b):
    if weak_birth(a) or weak_birth(b):
        # Platzhalter "1995-01-01" zählt, wenn das Jahr passt
        if a and b and not a.startswith(('1900', '2019-01-01')) and not b.startswith(('1900', '2019-01-01')) \
                and a[:4] != b[:4] and a != '1969-12-31' and b != '1969-12-31':
            return 'Jahr verschieden'
        return 'unbekannt'
    if a == b:
        return 'gleich'
    ya, ma, da = a.split('-')
    yb, mb, db = b.split('-')
    if ya == yb and ma == db and da == mb:
        return 'Tag/Monat vertauscht'
    if sum(1 for x, y in zip(a, b) if x != y) == 1:
        return 'Tippfehler'
    return 'verschieden'


def age_ok(birth, seasons):
    if weak_birth(birth):
        return True
    y = int(birth[:4])
    return all(15 <= int(s) - y <= 50 for s in seasons)


class Person:
    def __init__(self, pid, rec):
        self.id = pid
        self.first = rec['first']
        self.last = rec['last']
        self.birth = rec['birth']
        self.games = set(rec['games'])
        self.seasons = set(rec['seasons'])
        # Geburtsdatum, das nicht zu den eigenen Saisons passt (z. B. mit 12 in der AFL), ist falsch erfasst
        if not age_ok(self.birth, self.seasons):
            self.birth = ''
        self.team_by_season = rec['team_by_season']      # season -> set(teams)
        self.teams = {t for ts in self.team_by_season.values() for t in ts}
        self.jerseys = set(rec.get('jerseys', {}))


def compare(p, q):
    """Merkmale eines Kandidatenpaars."""
    if p.games & q.games:
        return None                                      # gleichzeitig im Kader -> zwei Personen
    ls, lk = last_sim(p.last, q.last)
    fs, fk = first_sim(p.first, q.first)
    # vertauschte Vor-/Nachnamen ("Liepert David")
    ls2, _ = last_sim(p.last, q.first)
    fs2, _ = first_sim(p.first, q.last)
    swapped = ls2 >= 0.95 and fs2 >= 0.95
    if swapped:
        ls, lk, fs, fk = 1.0, 'vertauscht', 1.0, 'vertauscht'
    br = birth_rel(p.birth, q.birth)
    same_season = sorted(p.seasons & q.seasons)
    same_team_same_season = all(p.team_by_season[s] & q.team_by_season[s] for s in same_season)
    return {
        'last': round(ls, 2), 'last_kind': lk, 'first': round(fs, 2), 'first_kind': fk, 'birth': br,
        'shared_team': bool(p.teams & q.teams), 'same_season': same_season,
        'same_season_ok': same_team_same_season,
        'age_ok': age_ok(p.birth, q.seasons) and age_ok(q.birth, p.seasons),
        'jersey': bool(p.jerseys & q.jerseys),
    }


def classify(f):
    """'sicher', 'prüfen' oder None."""
    if f is None or not f['age_ok'] or f['birth'] in ('verschieden', 'Jahr verschieden'):
        return None
    if f['same_season'] and not f['same_season_ok']:
        return None                                      # gleiche Saison, verschiedene Teams
    L, F, B, T = f['last'], f['first'], f['birth'], f['shared_team']
    if L < 0.8 or F < 0.8:
        return None
    if B == 'gleich' and L >= 0.8 and F >= 0.8:
        return 'sicher'
    if B in ('Tag/Monat vertauscht', 'Tippfehler') and L >= 0.95 and F >= 0.9 and T:
        return 'sicher'
    if B == 'unbekannt' and T and L >= 0.9 and F >= 0.85 and f['last_kind'] != 'Doppelname':
        return 'sicher'
    if B == 'unbekannt' and T and f['last_kind'] == 'Doppelname' and F >= 0.9:
        return 'prüfen'
    if B == 'unbekannt' and not T and L >= 0.95 and F >= 0.9:
        return 'prüfen'                                  # anderer Verein – Vereinswechsel möglich
    if B == 'unbekannt' and T and L >= 0.8:
        return 'prüfen'
    if B in ('Tag/Monat vertauscht', 'Tippfehler') and L >= 0.9 and F >= 0.85:
        return 'prüfen'
    return None


def find_duplicates(records, confirmed=(), rejected=()):
    """records: {id: {first,last,birth,games,seasons,team_by_season,jerseys}}
    confirmed/rejected: Paare (a, b), die das Ligamanagement bestätigt/abgelehnt hat."""
    P = {i: Person(i, r) for i, r in records.items()}
    blocks = collections.defaultdict(set)
    for i, p in P.items():
        lp = lastparts(p.last)
        if lp:
            j = ''.join(lp)
            blocks['L' + j].add(i)
            blocks['P' + phon(j)].add(i)
            blocks['S' + j[:4]].add(i)
            blocks['E' + j[-4:]].add(i)
            for t in lp:
                if len(t) >= 4:
                    blocks['T' + t].add(i)
        fn = norm(p.first)
        if fn and lp:
            blocks['F' + fn.split()[0] + '|' + lp[0][:2]].add(i)
            blocks['X' + ''.join(lp) + '|' + fn.split()[0]].add(i)
            blocks['X' + fn.replace(' ', '') + '|' + (lp[0] if lp else '')].add(i)   # vertauscht
        if not weak_birth(p.birth):
            blocks['B' + p.birth].add(i)
    pairs = set()
    for s in blocks.values():
        if 1 < len(s) < 300:
            pairs.update(itertools.combinations(sorted(s), 2))
    rejected = {tuple(sorted(x)) for x in rejected}
    found = []
    for a, b in pairs:
        if (a, b) in rejected:
            continue
        f = compare(P[a], P[b])
        c = classify(f)
        if (a, b) in {tuple(sorted(x)) for x in confirmed}:
            c = 'sicher'
        if c:
            found.append((a, b, c, f))
    for a, b in confirmed:
        a, b = sorted((a, b))
        if a in P and b in P and not any(x[0] == a and x[1] == b for x in found):
            found.append((a, b, 'sicher', compare(P[a], P[b]) or {}))

    # Zusammenführen (Union-Find) – nur wenn die ganze Gruppe widerspruchsfrei bleibt
    parent = {i: i for i in P}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    members = {i: {i} for i in P}

    def group_ok(ra, rb):
        A, B = members[ra], members[rb]
        ga = set().union(*(P[i].games for i in A))
        gb = set().union(*(P[i].games for i in B))
        if ga & gb:
            return False
        births = {P[i].birth for i in A | B if not weak_birth(P[i].birth)}
        if len(births) > 1:
            bl = sorted(births)
            if not all(birth_rel(bl[0], x) in ('gleich', 'Tag/Monat vertauscht', 'Tippfehler') for x in bl[1:]):
                return False
        for s in {s for i in A for s in P[i].seasons} & {s for i in B for s in P[i].seasons}:
            ta = set().union(*(P[i].team_by_season.get(s, set()) for i in A))
            tb = set().union(*(P[i].team_by_season.get(s, set()) for i in B))
            if not ta & tb:
                return False
        return True

    order = sorted([x for x in found if x[2] == 'sicher'], key=lambda x: (x[0], x[1]))
    merged_pairs = []
    for a, b, c, f in order:
        ra, rb = root(a), root(b)
        if ra == rb:
            continue
        if not group_ok(ra, rb):
            continue
        lo, hi = sorted((ra, rb))
        parent[hi] = lo
        members[lo] |= members.pop(hi)
        merged_pairs.append((a, b, f))
    groups = {r: sorted(m) for r, m in members.items() if len(m) > 1}
    review = [(a, b, f) for a, b, c, f in found if c == 'prüfen' and root(a) != root(b)]
    return groups, merged_pairs, review, {i: root(i) for i in P}
