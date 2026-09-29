# EGREP-AF XML -> Spieler- und Teamwerte je Spiel (Hockeydata-Rechenregeln nachgebildet)
#
# Koordinaten: alle Aktionen eines Spielzugs stehen im System des Teams "TeamOnOffenseSide"
# (-50 = eigene Goal Line, +50 = gegnerische Goal Line).
# Hockeydata-Regel (aus den offiziellen Werten abgeleitet): Raumgewinn eines Spielzugs =
#   ToYards der LETZTEN Aktion des Spielzugs (inkl. Strafen) - Line of Scrimmage;
#   endet der Spielzug mit einem Touchdown, zählt bis zur Goal Line (+/-50).
import xml.etree.ElementTree as ET
from collections import defaultdict

XSI = '{http://www.w3.org/2001/XMLSchema-instance}type'
OTHER = {'Home': 'Away', 'Away': 'Home'}
SCRIM = ('RushAction', 'CompletePassAction', 'IncompletePassAction', 'InterceptedPassAction',
         'QuarterbackSackAction', 'KneeDownAction')
IGNORE = ('TimeoutAction', 'TimeoutByTeamAction', 'TimeoutByGameOfficialAction', 'CoinTossAction',
          'HalftimeAction', 'EndOfGameAction')


def _int(x, default=None):
    try:
        return int(str(x).strip())
    except Exception:
        return default


def _players(el):
    out = []
    for ch in el:
        v = ch.text.strip() if ch.text else None
        if v and v != '0':
            out.append(v)
    return out


class Game:
    def __init__(self, path):
        r = ET.parse(path).getroot()
        self.path = path
        self.guid = r.findtext('GUID')
        self.team, self.roster, self.names, self.on_roster, self.pos = {}, {}, {}, {}, {}
        for side, tag in (('Home', 'HomeTeam'), ('Away', 'AwayTeam')):
            t = r.find(tag)
            self.team[side] = (_int(t.findtext('id')), t.findtext('LongName'), t.findtext('ShortName'))
            on, off_ = {}, {}
            self.on_roster[side] = set()
            for pl in t.find('Players'):
                j = (pl.findtext('JerseyNr') or '').strip()
                pid = _int(pl.findtext('id'))
                if not pid or pid <= 0:
                    continue
                self.names[pid] = ((pl.findtext('FirstName') or '').strip(), (pl.findtext('LastName') or '').strip(), j)
                self.pos[pid] = (pl.findtext('Position') or '').strip()
                if pl.findtext('isOnRoster') == 'true':
                    on.setdefault(j, pid)
                    self.on_roster[side].add(pid)
                else:
                    off_.setdefault(j, pid)
            for j, pid in off_.items():
                on.setdefault(j, pid)
            self.roster[side] = on
        self.plays = []
        for p in r.find('SerializationPlays'):
            acts = []
            for a in p.find('ActionListe'):
                d = {'type': a.get(XSI)}
                for ch in a:
                    if ch.tag in ('TackledByPlayers', 'QuarterbackHurryForcedByPlayers'):
                        d[ch.tag] = _players(ch)
                    else:
                        d[ch.tag] = ch.text.strip() if ch.text else None
                for k in ('RecoveringTeam', 'PenalizedTeam', 'TakenByTeam'):
                    if k in d and d[k] not in ('Home', 'Away'):
                        d[k] = None
                acts.append(d)
            self.plays.append({
                'off': p.findtext('TeamOnOffenseSide'),
                'down': _int(p.findtext('down'), 0),
                'togo': _int(p.findtext('yards2go'), 0),
                'los': _int(p.findtext('lineOfScrimmage'), 0),
                'afterTD': p.findtext('isAfterTouchdown') == 'true',
                'hs': _int(p.findtext('HomeScore'), 0),
                'as': _int(p.findtext('AwayScore'), 0),
                'acts': acts,
            })

    def pid(self, side, jersey):
        if jersey is None or side not in self.roster:
            return None
        return self.roster[side].get(str(jersey).strip())


def _to(a, default):
    v = _int(a.get('ToYards'))
    return default if v is None else v


def _dd():
    return defaultdict(float)


def parse(path):
    g = Game(path)
    P = defaultdict(_dd)   # pid -> Werte
    PS = {}                                        # pid -> Seite
    T = {'Home': defaultdict(float), 'Away': defaultdict(float)}

    def st(side, jersey):
        pid = g.pid(side, jersey)
        if pid is None:
            return None
        PS.setdefault(pid, side)
        return P[pid]

    def mx(d, k, v):
        d[k] = max(d[k], v) if k in d else v

    plays = g.plays
    for pi, p in enumerate(plays):
        off = p['off']
        if off not in ('Home', 'Away'):
            continue
        de = OTHER[off]
        acts = [a for a in p['acts'] if a['type'] not in IGNORE]
        if not acts:
            continue
        types = [a['type'] for a in acts]
        los = p['los']

        # --- Strafen ---
        nullified = False
        for a in acts:
            if a['type'] != 'PenaltyAction':
                continue
            side = a.get('PenalizedTeam')
            if a.get('IsDeclined') == 'true':
                if side:
                    T[side]['pen_declined'] += 1
                continue
            if a.get('NoPlay') == 'true':
                nullified = True
            if side:
                T[side]['pen'] += 1
                T[side]['pen_yds'] += _int(a.get('YardsPenalty'), 0) or 0
                ty = _int(a.get('ToYards'))
                if ty is not None:
                    T[side]['pen_yds_los'] += abs(ty - los)
        if nullified:
            T[off]['nullified'] += 1
            continue

        # --- Art des Spielzugs ---
        if 'KickoffAction' in types or 'KickoffOnsideAction' in types:
            kind = 'ko'
        elif 'PuntAction' in types or 'PuntIsBlockedAction' in types:
            kind = 'punt'
        elif 'FieldGoalAction' in types:
            kind = 'fg'
        elif 'PATAction' in types:
            kind = 'pat'
        elif any(t in types for t in SCRIM):
            kind = 'two' if p['afterTD'] else 'scrim'
        else:
            continue

        # --- Wer hatte den Ball zuletzt? ---
        holder = off
        for a in acts:
            t = a['type']
            if t in ('InterceptedPassAction', 'KickoffReturnAction', 'PuntReturnAction', 'FieldGoalIsReturnedAction', 'FairCatchAction'):
                holder = de
            elif t in ('FumbleAction', 'KickoffOnsideAction', 'PuntIsBlockedAction', 'FieldGoalIsBlockedAction', 'PATIsBlockedAction'):
                if a.get('RecoveringTeam'):
                    holder = a['RecoveringTeam']
        if kind == 'ko' and holder == off and any(a['type'] == 'KickoffReturnAction' for a in acts):
            holder = de

        # --- Ende des Spielzugs (Hockeydata-Regel) ---
        td_act = next((a for a in acts if a['type'] == 'TouchdownAction'), None)
        saf_act = next((a for a in acts if a['type'] == 'SafetyAction'), None)

        def play_end(lst):
            if not lst:
                return los
            last = lst[-1]
            if last['type'] == 'TouchdownAction':
                return 50 if holder == off else -50
            if last['type'] == 'SafetyAction':
                return -50 if holder == off else 50
            return _to(last, los)
        # mit Strafen (Pass-Spielzüge) / ohne Strafen (Läufe, Sacks)
        end_wp = play_end([a for a in acts if not (a['type'] == 'PenaltyAction' and a.get('IsDeclined') == 'true')])
        end_np = play_end([a for a in acts if a['type'] != 'PenaltyAction'])
        end = end_np
        scored_td = td_act is not None
        td_side = holder if scored_td else None

        # --- Tackles (nur zur Kontrolle gegen offizielle Defense-Werte) ---
        cur = off
        for a in acts:
            t = a['type']
            if t in ('InterceptedPassAction', 'KickoffReturnAction', 'PuntReturnAction', 'FieldGoalIsReturnedAction'):
                cur = de
            elif t in ('FumbleAction', 'KickoffOnsideAction', 'PuntIsBlockedAction', 'FieldGoalIsBlockedAction') and a.get('RecoveringTeam'):
                cur = a['RecoveringTeam']
            elif t in ('TackleAction', 'OutOfBoundsAction'):
                lst = a.get('TackledByPlayers') or []
                if len(lst) == 1:
                    s = st(OTHER[cur], lst[0])
                    if s is not None:
                        s['solo'] += 1
                elif len(lst) > 1:
                    for j in lst:
                        s = st(OTHER[cur], j)
                        if s is not None:
                            s['ast'] += 1

        # ================= Scrimmage =================
        if kind == 'scrim':
            primary = None
            for a in acts:
                t = a['type']
                if t == 'RushAction':
                    s = st(off, a.get('RushingPlayer'))
                    T[off]['rush_att'] += 1
                    if s is not None:
                        s['rush_att'] += 1
                    primary = ('rush', s, None)
                    break
                if t == 'KneeDownAction':
                    T[off]['kneel'] += 1
                    primary = ('kneel', None, None)
                    break
                if t in ('CompletePassAction', 'IncompletePassAction', 'InterceptedPassAction'):
                    qb = st(off, a.get('FromPlayer'))
                    tj = a.get('ToPlayer')
                    tg = st(off, tj) if tj not in (None, '0') else None
                    T[off]['pass_att'] += 1
                    if qb is not None:
                        qb['pass_att'] += 1
                    if tg is not None:
                        tg['tgt'] += 1
                    if t == 'CompletePassAction':
                        T[off]['pass_cmp'] += 1
                        if qb is not None:
                            qb['pass_cmp'] += 1
                        if tg is not None:
                            tg['rec'] += 1
                        primary = ('rec', tg, qb)
                    elif t == 'IncompletePassAction':
                        d = a.get('DisruptedByPlayer')
                        if d not in (None, '0'):
                            ds = st(de, d)
                            if ds is not None:
                                ds['pbu'] += 1
                        primary = ('inc', None, qb)
                    else:
                        T[off]['pass_int'] += 1
                        T[de]['int_for'] += 1
                        if qb is not None:
                            qb['pass_int'] += 1
                        ij = a.get('InterceptedByPlayer')
                        s = st(de, ij)
                        if s is not None:
                            s['int'] += 1
                        rj = a.get('ReturnedByPlayer')
                        rs = st(de, rj) if rj not in (None, '0') else s
                        yds = _to(a, los) - end
                        T[de]['int_ret_yds'] += yds
                        if rs is not None:
                            rs['int_ret_yds'] += yds
                        primary = ('int', rs, qb)
                    break
                if t == 'QuarterbackSackAction':
                    qb = st(off, a.get('FromPlayer'))
                    T[off]['sacked'] += 1
                    if qb is not None:
                        qb['sacked'] += 1
                    sk = a.get('TackledByPlayers') or []
                    if not sk:
                        nxt = next((b for b in acts if b['type'] == 'TackleAction'), None)
                        sk = (nxt or {}).get('TackledByPlayers') or []
                    for j in sk:
                        s = st(de, j)
                        if s is not None:
                            s['sacks'] += 1 / len(sk)
                    T[de]['sacks_for'] += 1
                    primary = ('sack', qb, None)
                    break

            role = primary[0] if primary else None
            yds = (end_wp if role == 'rec' else end_np) - los
            if role == 'kneel':
                T[off]['kneel_yds'] += yds
            if role == 'rush':
                T[off]['rush_yds'] += yds
                mx(T[off], 'rush_long', yds)
                if primary[1] is not None:
                    primary[1]['rush_yds'] += yds
            elif role == 'sack':
                T[off]['sack_yds'] += -yds
                if primary[1] is not None:
                    primary[1]['sack_yds'] += -yds
            elif role == 'rec':
                T[off]['pass_yds'] += yds
                mx(T[off], 'pass_long', yds)
                if primary[1] is not None:
                    primary[1]['rec_yds'] += yds
                    mx(primary[1], 'rec_long', yds)
                if primary[2] is not None:
                    primary[2]['pass_yds'] += yds

            # Fumbles
            carrier_side = off
            carrier = primary[1] if role in ('rush', 'rec', 'sack') else None
            for a in acts:
                t = a['type']
                if t == 'InterceptedPassAction':
                    carrier_side = de
                    carrier = st(de, a.get('ReturnedByPlayer') or a.get('InterceptedByPlayer'))
                elif t == 'ContinueAction':
                    carrier = st(carrier_side, a.get('FromPlayer'))
                elif t == 'FumbleAction':
                    rt = a.get('RecoveringTeam')
                    T[carrier_side]['fum'] += 1
                    if carrier is not None:
                        carrier['fum'] += 1
                    ff = a.get('ForcedByPlayer')
                    if ff not in (None, '0'):
                        fs = st(OTHER[carrier_side], ff)
                        if fs is not None:
                            fs['ff'] += 1
                    if rt and rt != carrier_side:
                        T[carrier_side]['fum_lost'] += 1
                        T[rt]['fum_rec_for'] += 1
                        if carrier is not None:
                            carrier['fum_lost'] += 1
                        rs = st(rt, a.get('RecoveringPlayer'))
                        if rs is not None:
                            rs['fum_rec'] += 1
                        carrier_side, carrier = rt, rs
                    elif rt:
                        carrier = st(rt, a.get('RecoveringPlayer'))

            # Touchdowns
            if scored_td:
                if td_side == off:
                    if role in ('rush', 'kneel', 'sack'):
                        T[off]['td_rush'] += 1
                        if primary[1] is not None:
                            primary[1]['rush_td'] += 1
                    elif role == 'rec':
                        T[off]['td_pass'] += 1
                        if primary[1] is not None:
                            primary[1]['rec_td'] += 1
                        if primary[2] is not None:
                            primary[2]['pass_td'] += 1
                    else:
                        T[off]['td_other'] += 1
                else:
                    T[de]['td_def'] += 1
                    if carrier is not None and carrier_side == de:
                        carrier['def_td'] += 1
            if saf_act is not None:
                T[OTHER[holder]]['safety'] += 1

            # 3./4. Versuch
            if p['down'] in (3, 4) and role not in ('kneel', 'sack'):
                k = 'd3' if p['down'] == 3 else 'd4'
                T[off][k + '_att'] += 1
                conv = scored_td and td_side == off
                if not conv:
                    nxt = next((q for q in plays[pi + 1:] if q['off'] in ('Home', 'Away') and
                                any(b['type'] not in IGNORE for b in q['acts'])), None)
                    if nxt is not None and nxt['off'] == off and nxt['down'] == 1 and not nxt['afterTD']:
                        conv = True
                if conv:
                    T[off][k + '_conv'] += 1

        # ================= Kickoff =================
        elif kind == 'ko':
            ko = next((a for a in acts if a['type'] == 'KickoffAction'), None)
            kspot = _int((ko or {}).get('FromYards'), los)
            k = st(off, (ko or {}).get('FromPlayer'))
            T[off]['ko'] += 1
            if k is not None:
                k['ko'] += 1
            ret = next((a for a in acts if a['type'] == 'KickoffReturnAction'), None)
            rs = st(de, ret.get('ReturnedByPlayer')) if ret is not None else None
            if ret is not None:
                yds = _to(ret, kspot) - end
                T[de]['kr'] += 1
                T[de]['kr_yds'] += yds
                T[de]['kr_yds_wp'] += _to(ret, kspot) - end_wp
                T[off]['ko_ret'] += 1
                T[off]['ko_ret_yds'] += yds
                if rs is not None:
                    rs['kr'] += 1
                    rs['kr_yds'] += yds
                    rs['kr_yds_wp'] += _to(ret, kspot) - end_wp
                    mx(rs, 'kr_long', yds)
            if 'TouchbackAction' in types:
                T[off]['ko_tb'] += 1
            if 'KickoffOnsideAction' in types:
                T[off]['ko_onside'] += 1
            if scored_td:
                if td_side == de and ret is not None:
                    T[de]['td_kr'] += 1
                    if rs is not None:
                        rs['kr_td'] += 1
                else:
                    T[td_side]['td_other'] += 1
            for a in acts:
                if a['type'] == 'FumbleAction':
                    rt = a.get('RecoveringTeam')
                    T[de]['fum'] += 1
                    if rs is not None:
                        rs['fum'] += 1
                        if rt and rt != de:
                            rs['fum_lost'] += 1
                    if rt and rt != de:
                        T[de]['fum_lost'] += 1
                        T[rt]['fum_rec_for'] += 1
            if saf_act is not None:
                T[OTHER[holder]]['safety'] += 1

        # ================= Punt =================
        elif kind == 'punt':
            pa = next((a for a in acts if a['type'] in ('PuntAction', 'PuntIsBlockedAction')), None)
            k = st(off, (pa or {}).get('FromPlayer'))
            T[off]['punt'] += 1
            if k is not None:
                k['punt'] += 1
            blocked = 'PuntIsBlockedAction' in types
            ret = next((a for a in acts if a['type'] == 'PuntReturnAction'), None)
            fc = next((a for a in acts if a['type'] == 'FairCatchAction'), None)
            res = None
            if blocked:
                res = 'blk'
                T[de]['blk_for'] += 1
                b = next(a for a in acts if a['type'] == 'PuntIsBlockedAction')
                bs = st(de, b.get('BlockedByPlayer'))
                if bs is not None:
                    bs['blk'] += 1
            elif ret is not None:
                res = 'ret'
            elif fc is not None:
                res = 'fc'
            elif 'TouchbackAction' in types:
                res = 'tb'
            elif 'OutOfBoundsAction' in types:
                res = 'oob'
            elif 'DownedAction' in types:
                res = 'downed'
            if res:
                T[off]['punt_' + res] += 1
                if k is not None:
                    k['punt_' + res] += 1
            if not blocked:
                if ret is not None:
                    pend = _to(ret, los)
                elif fc is not None:
                    pend = _to(fc, los)
                elif res == 'tb':
                    pend = 50
                else:
                    pend = end
                pyds = pend - los
                T[off]['punt_yds'] += pyds
                if k is not None:
                    k['punt_yds'] += pyds
                    mx(k, 'punt_long', pyds)
            rs = st(de, ret.get('ReturnedByPlayer')) if ret is not None else None
            if ret is not None:
                yds = _to(ret, los) - end
                T[de]['pr'] += 1
                T[de]['pr_yds'] += yds
                T[de]['pr_yds_wp'] += _to(ret, los) - end_wp
                if rs is not None:
                    rs['pr'] += 1
                    rs['pr_yds'] += yds
                    mx(rs, 'pr_long', yds)
            if fc is not None:
                fs = st(de, fc.get('CatchedByPlayer'))
                if fs is not None:
                    fs['fc'] += 1
            if scored_td:
                if td_side == de and ret is not None:
                    T[de]['td_pr'] += 1
                    if rs is not None:
                        rs['pr_td'] += 1
                elif td_side == de:
                    T[de]['td_def'] += 1
                else:
                    T[off]['td_other'] += 1
            for a in acts:
                if a['type'] == 'FumbleAction' and ret is not None:
                    rt = a.get('RecoveringTeam')
                    T[de]['fum'] += 1
                    if rs is not None:
                        rs['fum'] += 1
                        if rt and rt != de:
                            rs['fum_lost'] += 1
                    if rt and rt != de:
                        T[de]['fum_lost'] += 1
                        T[rt]['fum_rec_for'] += 1
            if saf_act is not None:
                T[OTHER[holder]]['safety'] += 1

        # ================= Field Goal =================
        elif kind == 'fg':
            fa = next(a for a in acts if a['type'] == 'FieldGoalAction')
            k = st(off, fa.get('FromPlayer'))
            dist = _int(fa.get('KickDistance'))
            T[off]['fga'] += 1
            if k is not None:
                k['fga'] += 1
            if 'FieldGoalIsGoodAction' in types:
                T[off]['fgm'] += 1
                if dist is not None:
                    mx(T[off], 'fg_long', dist)
                if k is not None:
                    k['fgm'] += 1
                    if dist is not None:
                        mx(k, 'fg_long', dist)
            if 'FieldGoalIsBlockedAction' in types:
                T[de]['blk_for'] += 1
                T[off]['fg_blk'] += 1
            if scored_td:
                if td_side == de:
                    T[de]['td_def'] += 1
                    rr = next((a for a in acts if a['type'] in ('FieldGoalIsReturnedAction', 'FieldGoalIsBlockedAction')), None)
                    if rr is not None:
                        rs = st(de, rr.get('ReturnedByPlayer') or rr.get('RecoveringPlayer'))
                        if rs is not None:
                            rs['def_td'] += 1
                else:
                    T[off]['td_other'] += 1

        # ================= PAT / 2-Punkte =================
        elif kind == 'pat':
            pa = next(a for a in acts if a['type'] == 'PATAction')
            k = st(off, pa.get('FromPlayer'))
            T[off]['xpa'] += 1
            if k is not None:
                k['xpa'] += 1
            if 'PATIsGoodAction' in types:
                T[off]['xpm'] += 1
                if k is not None:
                    k['xpm'] += 1
            if 'PATIsBlockedAction' in types:
                T[de]['blk_for'] += 1
                T[off]['xp_blk'] += 1
            if 'TwoPointConversionAction' in types and holder == de:
                T[de]['dxp'] += 1
        elif kind == 'two':
            T[off]['two_att'] += 1
            if 'TwoPointConversionAction' in types:
                if holder == off:
                    T[off]['two_made'] += 1
                else:
                    T[de]['dxp'] += 1

    T['Home']['pts'] = plays[-1]['hs'] if plays else 0
    T['Away']['pts'] = plays[-1]['as'] if plays else 0
    return g, P, PS, T
